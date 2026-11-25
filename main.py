import asyncio
import atexit
import logging
import os
import random
import socket
import struct
import sys
import time
from pathlib import Path

import discord
from discord.ext import commands

from config import Config, _resolve_token
from database import DatabaseManager
from cogs.tickets import InsideTicketView, TicketPanel
from cogs.verification import VerificationView
from cleanup import cleanup_project_junk

LOCK_FILE = "vanilla_bot.lock"
_lock_fd = None


def acquire_process_lock() -> bool:
    """Гарантирует запуск ровно одного экземпляра бота, исключая дублирование сообщений и конфликты портов."""
    global _lock_fd
    lock_path = os.path.abspath(LOCK_FILE)
    try:
        if sys.platform == "win32":
            import msvcrt
            _lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
            try:
                msvcrt.locking(_lock_fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                logger.critical(
                    f"\n{'='*70}\n"
                    f"КРИТИЧЕСКАЯ ОШИБКА: ДРУГОЙ ЭКЗЕМПЛЯР БОТА УЖЕ ЗАПУЩЕН!\n"
                    f"Обнаружен активный файл блокировки {lock_path}.\n"
                    f"Запуск второго экземпляра отменён во избежание дублирования сообщений.\n"
                    f"{'='*70}"
                )
                return False
        else:
            import fcntl
            _lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                logger.critical(
                    f"\n{'='*70}\n"
                    f"КРИТИЧЕСКАЯ ОШИБКА: ДРУГОЙ ЭКЗЕМПЛЯР БОТА УЖЕ ЗАПУЩЕН!\n"
                    f"Обнаружен активный файл блокировки {lock_path}.\n"
                    f"Запуск второго экземпляра отменён во избежание дублирования сообщений.\n"
                    f"{'='*70}"
                )
                return False
        try:
            os.ftruncate(_lock_fd, 0)
            os.write(_lock_fd, str(os.getpid()).encode())
        except Exception:
            pass
        return True
    except Exception as e:
        logger.debug(f"Lock acquire note: {e}")
        return True


def release_process_lock():
    global _lock_fd
    if _lock_fd is not None:
        try:
            os.close(_lock_fd)
        except Exception:
            pass
        _lock_fd = None
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


atexit.register(release_process_lock)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("VanillaBot")

_ORIG_GETADDRINFO = socket.getaddrinfo
_DNS_CACHE: dict[str, tuple[float, list[str]]] = {}


def _resolve_via_public_dns(host: str, dns_servers: tuple[str, ...] = ("1.1.1.1", "8.8.8.8"), timeout: float = 2.0) -> list[str]:
    """Минимальный UDP DNS-клиент (A-записи) как резерв при сбоях системного /etc/resolv.conf."""
    if not host or any(c.isspace() for c in host):
        return []
    now = time.monotonic()
    cached = _DNS_CACHE.get(host)
    if cached and (now - cached[0]) < 300.0:
        return cached[1]

    labels = [p.encode("idna") for p in host.strip(".").split(".") if p]
    if not labels:
        return []
    tx_id = random.randint(1, 65535)
    header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(lb)]) + lb for lb in labels) + b"\x00"
    query = header + qname + struct.pack(">HH", 1, 1)

    for server in dns_servers:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(query, (server, 53))
            resp, _ = sock.recvfrom(1024)
            if len(resp) < 12:
                continue
            r_id, _flags, qdcount, ancount, _ns, _ar = struct.unpack(">HHHHHH", resp[:12])
            if r_id != tx_id or ancount == 0:
                continue

            offset = 12
            for _ in range(qdcount):
                while offset < len(resp):
                    ln = resp[offset]
                    if ln == 0:
                        offset += 1
                        break
                    if (ln & 0xC0) == 0xC0:
                        offset += 2
                        break
                    offset += 1 + ln
                offset += 4

            ips: list[str] = []
            for _ in range(ancount):
                if offset >= len(resp):
                    break
                if (resp[offset] & 0xC0) == 0xC0:
                    offset += 2
                else:
                    while offset < len(resp):
                        ln = resp[offset]
                        if ln == 0:
                            offset += 1
                            break
                        if (ln & 0xC0) == 0xC0:
                            offset += 2
                            break
                        offset += 1 + ln
                if offset + 10 > len(resp):
                    break
                rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", resp[offset : offset + 10])
                offset += 10
                if rtype == 1 and rdlen == 4 and offset + 4 <= len(resp):
                    ips.append(socket.inet_ntoa(resp[offset : offset + 4]))
                offset += rdlen

            if ips:
                _DNS_CACHE[host] = (now, ips)
                return ips
        except Exception:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return []


def install_dns_fallback() -> None:
    """Устанавливает резервный DNS (1.1.1.1 / 8.8.8.8) поверх socket.getaddrinfo при временных сбоях DNS хостинга."""
    def _fallback_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
        except socket.gaierror as orig_err:
            if isinstance(host, str) and host and not host.replace(".", "").isdigit() and ":" not in host:
                if family in (0, socket.AF_INET):
                    ips = _resolve_via_public_dns(host)
                    if ips:
                        logger.warning("Системный DNS не ответил для %s (%s) — использован резервный DNS -> %s", host, orig_err, ips[0])
                        return _ORIG_GETADDRINFO(ips[0], port, socket.AF_INET, type, proto, flags)
            raise

    socket.getaddrinfo = _fallback_getaddrinfo


class VanillaSupportBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=Config.COMMAND_PREFIXES,
            intents=intents,
            help_command=None,
            proxy=Config.DISCORD_PROXY,
        )

        self.start_time = time.time()
        self.db = DatabaseManager(Config.DB_PATH, Config.TRANSCRIPTS_DIR)

    async def setup_hook(self):
        # Гарантируем, что счётчик тикетов не обнуляется при рестарте контейнера и продолжается с 100+
        try:
            self.db.ensure_ticket_counter_at_least(100)
        except Exception as cnt_err:
            logger.debug("Ensure counter note: %s", cnt_err)

        # Персистентные кнопки (тикеты + верификация)
        self.add_view(TicketPanel(self.db))
        self.add_view(InsideTicketView(self.db))
        self.add_view(VerificationView())

        # Загрузка всех модулей (Cogs)
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.info")
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.utility")
        await self.load_extension("cogs.verification")
        await self.load_extension("cogs.logs")
        await self.load_extension("cogs.bridge")
        await self.load_extension("cogs.security")

        # Глобальный обработчик ошибок слэш-команд (предотвращает зависания)
        async def on_tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
            logger.error(f"Ошибка слэш-команды /{interaction.command.name if interaction.command else 'unknown'}: {error}")
            try:
                msg = "Произошла внутренняя ошибка при выполнении команды."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=(interaction.guild is not None))
                else:
                    await interaction.response.send_message(msg, ephemeral=(interaction.guild is not None))
            except Exception:
                pass

        self.tree.on_error = on_tree_error

        # Синхронизация слэш-команд
        try:
            synced = await self.tree.sync()
            logger.info(f"Синхронизировано команд: {len(synced)}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации команд: {e}")

    async def on_ready(self):
        logger.info(f"Бот успешно запущен как {self.user} (ID: {self.user.id})")
        # Очищаем локальные дубликаты с гильдий, чтобы не было задвоения с глобальными командами
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            except Exception:
                pass

        # Статус выставляет мост (техработы / онлайн / TPS), а не on_ready напрямую,
        # иначе после каждого реконнекта статус «Онлайн: N» затирается IP-адресом.
        bridge = self.get_cog("Мост Minecraft")
        if bridge and hasattr(bridge, "update_bot_presence"):
            try:
                await bridge.update_bot_presence(force=True)
            except Exception as e:
                logger.debug(f"Не удалось обновить статус через мост: {e}")
        else:
            await self.change_presence(
                activity=discord.CustomActivity(name=Config.SERVER_IP)
            )

    # --- ОБРАБОТЧИК НЕИЗВЕСТНЫХ КОМАНД И ОШИБОК ---
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if ctx.channel.id == Config.BRIDGE_CHANNEL_ID:
            return

        if isinstance(error, commands.CommandNotFound):
            # Игнорируем неизвестные префикс-команды, чтобы не спамить в общие чаты
            return

        if isinstance(error, commands.MissingPermissions):
            try:
                await ctx.send("У вас недостаточно прав для выполнения этой команды.", delete_after=5)
            except Exception:
                pass
            return

        if isinstance(error, commands.MissingRequiredArgument):
            try:
                await ctx.send(f"Не указан обязательный аргумент: `{error.param.name}`. Проверьте `!help`.", delete_after=5)
            except Exception:
                pass
            return

        logger.warning(f"Ошибка команды {ctx.command}: {error}")

    async def close(self):
        logger.info("Остановка бота...")
        try:
            self.db.close()
        except Exception as e:
            logger.debug("Ошибка закрытия БД: %s", e)
        await super().close()


async def main():
    install_dns_fallback()
    if not acquire_process_lock():
        sys.exit(0)

    # 1. Автоматическая очистка остаточного мусора из папки проекта
    try:
        cleanup_project_junk(Path(__file__).resolve().parent)
    except Exception as cl_err:
        logger.debug("Ошибка автоочистки мусора: %s", cl_err)

    token = Config.DISCORD_TOKEN or _resolve_token()
    if not token:
        logger.critical("ОШИБКА: Токен Discord бота не обнаружен в .env или переменных окружения!")
        sys.exit(1)

    if Config.DISCORD_PROXY:
        logger.info(f"Используется прокси для подключения к Discord: {Config.DISCORD_PROXY}")

    bot = VanillaSupportBot()

    # 2. Повторная проверка с передачей db_manager для восстановления повреждённых баз данных
    try:
        cleanup_project_junk(Path(__file__).resolve().parent, bot.db)
    except Exception:
        pass
    try:
        async with bot:
            await bot.start(token)
    except Exception as e:
        err_msg = str(e)
        if any(w in err_msg.lower() for w in ["cannot connect to host", "timeout", "connection refused", "ssl"]):
            logger.critical(
                f"\n{'='*70}\n"
                f"КРИТИЧЕСКАЯ ОШИБКА СЕТИ / БЛОКИРОВКИ DISCORD:\n{e}\n\n"
                f"Внимание: если бот запущен на хостинге в РФ (Москва), Discord заблокирован РКН!\n"
                f"Для работы на российском хостинге укажите прокси в переменной окружения:\n"
                f"DISCORD_PROXY=http://ip:port (или http://user:pass@ip:port)\n"
                f"Либо перенесите бота на зарубежный хостинг (bot-hosting.net, Hetzner, Oracle, Aeza EU).\n"
                f"{'='*70}"
            )
        else:
            logger.critical(f"Ошибка при запуске бота: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
