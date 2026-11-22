import asyncio
import atexit
import logging
import os
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
