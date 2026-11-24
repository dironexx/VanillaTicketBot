import hmac
import asyncio
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
import uuid
from typing import Optional, Set, List, Dict, Tuple

import aiohttp
from aiohttp import web
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from config import Config
from database import DatabaseManager
from design import AG, Colors

logger = logging.getLogger("VanillaBot.Bridge")


def is_mod_or_admin(ctx) -> bool:
    author = ctx.author
    if not isinstance(author, discord.Member):
        return False
    guild = ctx.guild
    if author.guild_permissions.administrator or (guild and author.id == guild.owner_id):
        return True
    author_roles = {r.id for r in author.roles}
    return any(r_id in author_roles for r_id in Config.MOD_ROLE_IDS)


PROFANITY_ROOTS = re.compile(
    r'(?iu)\b([а-яa-zё]*?(?:[хx][уy][йjеяиюё]|п[иеё]зд|[её]б[аеёилытнщ]|бл[яе]д|бл[яе]т|[сs][уy][кk][аеиоу]|п[иеё]д[аое]р|г[ао]нд[оа]н|м[уy]д[аое]к|д[оа]лб[оа][её]б|шл[юе]х|дроч)[а-яa-zё]*)\b'
)

PROFANITY_FALSE_POSITIVES = {
    'страховка', 'страховой', 'страхование', 'подстраховка',
    'колебание', 'колебания', 'колебаться',
    'гребля', 'гребной', 'сабля', 'употребление', 'стебель',
    'рубль', 'рубля', 'рублями', 'рублях',
    'ястреб', 'теребить', 'скрести', 'погреб',
}


def mask_profanity_word(word: str) -> str:
    if len(word) <= 2:
        return word[0] + '*' if len(word) == 2 else '*'
    return word[0] + ('*' * (len(word) - 2)) + word[-1]


def censor_profanity(text: str) -> str:
    """Маскирует нецензурную лексику: первая буква + звёздочки + последняя буква (например, п*****с)."""
    if not text:
        return text

    def replace_match(m):
        w = m.group(1)
        w_low = w.lower().replace('ё', 'е')
        if w_low in PROFANITY_FALSE_POSITIVES:
            return w
        return mask_profanity_word(w)

    return PROFANITY_ROOTS.sub(replace_match, text)


def translate_death_message(death_msg: str, player_name: str) -> str:
    if not death_msg:
        return f"**{player_name}** погиб."

    msg = death_msg.strip()

    # Замена имени игрока на жирный ник
    def p():
        return f"**{player_name}**"

    # Поиск моба
    killer = ""
    for mob_en, mob_ru in MOB_TRANSLATIONS.items():
        if mob_en in msg.lower():
            killer = mob_ru
            break

    low = msg.lower()

    if "was slain by" in low:
        target = killer if killer else msg.split("was slain by")[-1].strip()
        return f"{p()} погиб в бою с **{target}**"
    if "was shot by" in low:
        target = killer if killer else msg.split("was shot by")[-1].strip()
        return f"{p()} был застрелен **{target}**"
    if "was blown up by creeper" in low:
        return f"{p()} взорван крипером"
    if "was blown up by" in low:
        return f"{p()} погиб от взрыва"
    if "fell from a high place" in low or "fell off a high place" in low:
        return f"{p()} разбился при падении с высоты"
    if "hit the ground too hard" in low:
        return f"{p()} разбился насмерть"
    if "fell off a ladder" in low:
        return f"{p()} упал с лестницы"
    if "fell off scaffolding" in low:
        return f"{p()} упал со строительных лесов"
    if "fell while climbing" in low:
        return f"{p()} сорвался с высоты"
    if "tried to swim in lava" in low:
        return f"{p()} утонул в лаве"
    if "burned to death" in low:
        return f"{p()} сгорел заживо"
    if "walked into fire whilst fighting" in low or "walked into a fire" in low:
        return f"{p()} сгорел в огне"
    if "drowned" in low:
        return f"{p()} утонул"
    if "suffocated in a wall" in low:
        return f"{p()} задохнулся в стене"
    if "starved to death" in low:
        return f"{p()} умер от голода"
    if "was killed by magic" in low:
        return f"{p()} погиб от магии"
    if "was poked to death by a sweet berry bush" in low:
        return f"{p()} заколот ягодным кустом"
    if "was pricked to death" in low:
        return f"{p()} укололся о кактус насмерть"
    if "experienced kinetic energy" in low:
        return f"{p()} разбился на элитрах"
    if "withered away" in low:
        return f"{p()} иссушен"
    if "was struck by lightning" in low:
        return f"{p()} поражен молнией"
    if "froze to death" in low:
        return f"{p()} замерз насмерть"
    if "was squashed by a falling anvil" in low:
        return f"{p()} раздавлен наковальней"
    if "was squashed by a falling block" in low:
        return f"{p()} раздавлен упавшим блоком"
    if "died" in low:
        return f"{p()} погиб"

    # Если неизвестный формат — оставляем аккуратно с выделением ника
    return msg.replace(player_name, f"**{player_name}**")


# --- МОДАЛЬНОЕ ОКНО И КНОПКА ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ (DM) ---
from cogs.bridge_views import (
    MOB_TRANSLATIONS,
    get_skin_avatar_url,
    get_skin_body_url,
    DmReplyView,
    TwoFactorVerifyView,
    TwoFactorPublicAlertView,
    LoginAlertView,
    AccountSecurityView,
    PermanentLinkPanelView,
)

class BridgeCog(commands.Cog, name="Мост Minecraft"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db

        self.app = web.Application(client_max_size=16 * 1024 * 1024)
        self.app.router.add_get("/", self.health_handler)
        self.app.router.add_get("/health", self.health_handler)
        self.app.router.add_get("/ws", self.websocket_handler)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

        self.active_sockets: Set[web.WebSocketResponse] = set()
        self._sockets_lock: asyncio.Lock = asyncio.Lock()
        self._webhook_lock: asyncio.Lock = asyncio.Lock()
        self._background_tasks: Set[asyncio.Task] = set()
        self.webhook: Optional[discord.Webhook] = None

        # Статистика сервера Minecraft
        self.mc_online: int = 0
        self.mc_max: int = 0
        self.mc_tps: float = 20.0
        self.mc_players: List[str] = []
        self._socket_stats: Dict[int, dict] = {}
        self.last_stats_time: float = 0.0
        self.mc_server_start_time: float = 0.0

        # Мониторинг, алерты и техработы
        self.was_connected: bool = False
        self.last_tps_alert_time: float = 0.0
        self.last_offline_alert_time: float = 0.0
        self.maintenance_enabled: bool = False
        self.maintenance_reason: str = "Технические работы"

        # Защита от спама и ложных анонсов старта при реконнекте моста
        self.bot_start_time: float = time.time()
        self.server_start_announced: bool = False
        self.had_explicit_server_stop: bool = False
        self._last_lifecycle_start_time: float = 0.0

        # Rate limit стрим-оповещений
        self.last_stream_alert: Dict[int, float] = {}

        # Rate limit контроль переименования голосовых каналов (5 минут)
        self.last_rename_time: float = 0.0
        self.pending_channel_update: bool = False

        self.mc_mspt: float = 20.0
        self.mc_mem_used: int = 0
        self.mc_mem_max: int = 0
        self.pending_queries: Dict[str, asyncio.Future] = {}

        # Временные 2FA сессии входов: player.lower() -> {code, ip, discord_id, expires_at, message}
        self.pending_2fa: Dict[str, dict] = {}

        # Anti-spoof: ожидаемые ответы alts_bans_result (player.lower() -> expires_at)
        self._alt_check_requests: Dict[str, float] = {}
        self._alt_check_manual: Dict[str, float] = {}

        # Rate limit ввода кодов привязки: user_id -> список timestamp попыток
        self._link_attempts: Dict[int, List[float]] = {}
        # Rate limit /code resend: player.lower() -> список timestamp
        self._resend_attempts: Dict[str, List[float]] = {}
        self.link_max_attempts: int = 5
        self.link_window_sec: float = 600.0

        # Кэш лидерборда и профилей игроков для надежности и нулевых задержек
        self.last_top_data: Optional[dict] = None
        self.cached_player_stats: Dict[str, Tuple[float, dict]] = {}

        # Дедупликация сообщений чата (защита от повторной отправки при сбоях сокета)
        self._recent_chat_in: Dict[str, float] = {}
        self._recent_chat_out: Dict[str, float] = {}

        self.update_vc_loop.start()
        self.create_tracked_task(self.start_web_server())

    def create_tracked_task(self, coro) -> asyncio.Task:
        """
        Создает фоновую задачу asyncio с сохранением сильной ссылки,
        предотвращая преждевременное уничтожение задачи сборщиком мусора (GC).
        """
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _recompute_stats(self) -> None:
        """Суммирует онлайн по всем подключённым серверам (main + vps)."""
        stats = [st for st in self._socket_stats.values() if st]
        if not stats:
            # Grace period (45 сек): если сокет кратковременно переподключается, не сбрасываем онлайн мгновенно
            if (time.time() - getattr(self, "last_disconnect_time", 0)) < 45.0 and getattr(self, "mc_online", 0) > 0:
                return
            self.mc_online = 0
            if not getattr(self, "mc_max", 0):
                self.mc_max = 0
            self.mc_tps = 20.0
            self.mc_mspt = 20.0
            self.mc_mem_used = 0
            self.mc_mem_max = 0
            self.mc_players = []
            return
        self.mc_online = sum(int(st.get("online", 0)) for st in stats)
        self.mc_max = sum(int(st.get("max", 0)) for st in stats)
        self.mc_tps = min(float(st.get("tps", 20.0)) for st in stats)
        self.mc_mspt = max(float(st.get("mspt", 20.0)) for st in stats)
        self.mc_mem_used = sum(int(st.get("mem_used", 0)) for st in stats)
        self.mc_mem_max = sum(int(st.get("mem_max", 0)) for st in stats)
        players: List[str] = []
        for st in stats:
            players.extend(st.get("players", []))
        self.mc_players = players

    @property
    def is_connected(self) -> bool:
        """Возвращает True, если сервер Minecraft подключен к мосту"""
        return len(self.active_sockets) > 0

    def register_alt_check(self, player: str, ttl: float = 30.0, manual: bool = False) -> None:
        """Регистрирует ожидаемый ответ alts_bans_result (защита от подделки и устаревших пакетов).

        Ключ — ник в нижнем регистре: ответ должен прийти именно на наш запрос.
        manual=True помечает ручные проверки модераторов (!whois / !alts), на них
        автосанкции не применяются.
        """
        key = str(player or "").strip().lower()
        if not key:
            return
        now = time.time()
        # Чистим просроченные записи, чтобы словарь не рос на долгоживущем процессе
        stale = [k for k, exp in self._alt_check_requests.items() if exp < now][:100]
        for k in stale:
            self._alt_check_requests.pop(k, None)
            self._alt_check_manual.pop(k, None)
        expires = now + max(1.0, float(ttl))
        self._alt_check_requests[key] = expires
        if manual:
            self._alt_check_manual[key] = expires

    def consume_alt_check(self, player: str) -> bool:
        """True, если ответ относится к нашему автоматическому запросу (можно применять санкции)."""
        key = str(player or "").strip().lower()
        if not key:
            return False
        now = time.time()
        expires = self._alt_check_requests.pop(key, 0.0)
        if expires < now:
            return False
        if self._alt_check_manual.pop(key, 0.0) > now:
            return False
        return True

    def resend_rate_ok(self, player: str) -> bool:
        """Не более 3 повторных отправок кода за 10 минут на игрока."""
        key = str(player or "").strip().lower()
        if not key:
            return False
        now = time.time()
        attempts = [t for t in self._resend_attempts.get(key, []) if now - t < 600.0]
        if len(attempts) >= 3:
            self._resend_attempts[key] = attempts[-3:]
            return False
        attempts.append(now)
        self._resend_attempts[key] = attempts[-3:]
        return True

    def link_rate_ok(self, user_id: int) -> bool:
        """Не более N попыток ввода кода привязки за окно (по умолчанию 5 за 10 минут)."""
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return False
        now = time.time()
        attempts = [t for t in self._link_attempts.get(uid, []) if now - t < self.link_window_sec]
        if len(attempts) >= self.link_max_attempts:
            self._link_attempts[uid] = attempts[-self.link_max_attempts:]
            return False
        attempts.append(now)
        self._link_attempts[uid] = attempts[-self.link_max_attempts:]
        return True

    async def query_minecraft(self, packet: dict, timeout: float = 3.0) -> Optional[dict]:
        if not self.active_sockets:
            return None
        query_id = str(uuid.uuid4().hex)
        packet["query_id"] = query_id
        fut = asyncio.get_running_loop().create_future()
        self.pending_queries[query_id] = fut
        await self.broadcast_packet(packet)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            return None
        finally:
            self.pending_queries.pop(query_id, None)

    async def health_handler(self, request: web.Request) -> web.Response:
        now = time.time()
        uptime_sec = int(now - getattr(self.bot, "start_time", self.bot_start_time))
        bot_latency = round(self.bot.latency * 1000, 1) if (self.bot.latency and math.isfinite(self.bot.latency)) else 0.0
        is_ready = bool(self.bot.is_ready())
        payload = {
            "status": "ok" if is_ready else "starting",
            "bot_ready": is_ready,
            "bot_user": str(self.bot.user) if self.bot.user else None,
            "bot_latency_ms": bot_latency,
            "uptime_seconds": max(0, uptime_sec),
            "minecraft_connected": len(self.active_sockets) > 0,
            "active_sockets_count": len(self.active_sockets),
            "online_players": self.mc_online,
            "max_players": self.mc_max,
            "tps": round(self.mc_tps, 2),
            "server_ip": Config.SERVER_IP,
        }
        return web.json_response(payload, headers={"Access-Control-Allow-Origin": "*"})

    async def start_web_server(self):
        secret = (Config.BRIDGE_SECRET or "").strip()
        if not secret:
            logger.critical(
                "BRIDGE_SECRET не задан — WebSocket-мост не запущен. "
                "Укажите секрет в .env и в config.yml плагина (bridge.token)."
            )
            return
        if secret == "vanillaland_secret_2026":
            logger.critical(
                "BRIDGE_SECRET использует значение по умолчанию — WebSocket-мост НЕ запущен. "
                "Сгенерируйте новый секрет (python -c \"import secrets;print(secrets.token_urlsafe(32))\") "
                "и обновите его в .env и в config.yml плагина (bridge.token)."
            )
            return
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            primary_port = Config.BRIDGE_PORT
            ports_to_bind = [primary_port]
            for alt_port in (25007, 25549):
                if alt_port not in ports_to_bind and alt_port > 0:
                    ports_to_bind.append(alt_port)

            self.sites: list[web.TCPSite] = []
            for p in ports_to_bind:
                try:
                    site = web.TCPSite(self.runner, "0.0.0.0", p, reuse_address=True)
                    await site.start()
                    self.sites.append(site)
                    logger.info(f"WebSocket-сервер моста запущен на 0.0.0.0:{p}")
                except Exception as port_err:
                    if p == primary_port:
                        logger.error(f"Не удалось запустить WebSocket-сервер моста на основном порту {p}: {port_err}")
                    else:
                        logger.debug(f"Дополнительный резервный порт {p} моста недоступен ({port_err}), пропускаем.")

            self.site = self.sites[0] if self.sites else None
        except Exception as e:
            logger.error(f"Критическая ошибка инициализации веб-сервера моста: {e}")

    def cog_unload(self):
        self.update_vc_loop.cancel()
        self.create_tracked_task(self.cleanup())

    async def cleanup(self):
        async with self._sockets_lock:
            sockets_to_close = list(self.active_sockets)
            self.active_sockets.clear()
        for ws in sockets_to_close:
            try:
                await ws.close()
            except Exception:
                pass
        if hasattr(self, "sites") and self.sites:
            for s in self.sites:
                try:
                    await s.stop()
                except Exception:
                    pass
            self.sites.clear()
        elif self.site:
            try:
                await self.site.stop()
            except Exception:
                pass
            self.site = None
        if self.runner:
            try:
                await self.runner.cleanup()
            except Exception:
                pass

    async def broadcast_packet(self, payload: dict):
        p_type = str(payload.get("type", ""))
        if p_type.startswith("maintenance") and not Config.BRIDGE_ENABLE_MAINTENANCE_SYNC:
            logger.debug("Синхронизация техработ отключена в конфиге, пакет %s пропущен", p_type)
            return
        if p_type == "check_alts_bans" and not Config.BRIDGE_ENABLE_ALTS_CHECK:
            logger.debug("Проверка альтов через мост отключена в конфиге, пакет check_alts_bans пропущен")
            return
        raw_json = json.dumps(payload, ensure_ascii=False)
        async with self._sockets_lock:
            sockets_to_remove = set()
            for ws in self.active_sockets:
                if ws.closed:
                    sockets_to_remove.add(ws)
                    continue
                try:
                    await ws.send_str(raw_json)
                except Exception as e:
                    logger.warning("Ошибка отправки пакета в сокет моста: %s", e)
                    try:
                        await ws.close()
                    except Exception as cl_err:
                        logger.debug("Ошибка закрытия сокета после сбоя отправки: %s", cl_err)
                    sockets_to_remove.add(ws)
            if sockets_to_remove:
                self.active_sockets.difference_update(sockets_to_remove)

    # --- WEBSOCKET HANDLER ---
    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        token = request.query.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        secret = Config.BRIDGE_SECRET or ""
        if not token or not hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8")):
            logger.warning("Попытка подключения к мосту с неверным токеном от %s", request.remote)
            return web.Response(status=401, text="Unauthorized: Invalid token")

        # Принудительно очищаем и закрываем старые сокеты, предотвращая задваивание сообщений
        async with self._sockets_lock:
            old_sockets = list(self.active_sockets)
            self.active_sockets.clear()
        for old_ws in old_sockets:
            try:
                if not old_ws.closed:
                    await old_ws.close()
            except Exception:
                pass

        # heartbeat=25.0 поддерживает постоянную активность в NAT/фаерволе хостинга
        # receive_timeout=None предотвращает обрыв при временном молчании сервера
        ws = web.WebSocketResponse(
            heartbeat=25.0,
            receive_timeout=None,
            max_msg_size=16 * 1024 * 1024,
        )
        await ws.prepare(request)

        async with self._sockets_lock:
            self.active_sockets.add(ws)
        self.was_connected = True
        client_ip = (
            request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote
        )
        logger.info(f"Minecraft сервер успешно подключился к мосту ({Config.SERVER_IP} / {client_ip})")

        # Если на боте активен режим техработ, сразу передаем его серверу
        if self.maintenance_enabled:
            init_maint = {"type": "maintenance", "enabled": True, "reason": self.maintenance_reason}
            try:
                await ws.send_str(json.dumps(init_maint, ensure_ascii=False))
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        self.create_tracked_task(self.sync_staff_to_minecraft())

        if getattr(self, "was_restarting", False):
            self.was_restarting = False
            self.maintenance_enabled = False
            self.create_tracked_task(self.update_bot_presence())
            events_ch = self.get_events_channel()
            if events_ch:
                embed = AG.embed(
                    title="Сервер успешно перезапущен • Vanilla Land",
                    description=(
                        "Сервер завершил перезагрузку и снова онлайн.\n"
                        "Вход открыт для всех желающих. Приятной игры на **Vanilla Land**."
                    ),
                    color=Colors.GREEN,
                )
                self.create_tracked_task(events_ch.send(embed=embed))

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_minecraft_packet(data, ws)
                    except json.JSONDecodeError as dec_err:
                        logger.debug("Получен невалидный JSON пакет от Minecraft: %s (ошибка: %s)", msg.data, dec_err)
                    except Exception as e:
                        logger.error(f"Ошибка при обработке пакета Minecraft: {e}", exc_info=True)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.warning(f"Ошибка сокета моста: {ws.exception()}")
        finally:
            async with self._sockets_lock:
                self.active_sockets.discard(ws)
            self._socket_stats.pop(id(ws), None)
            self.last_disconnect_time = time.time()
            self._recompute_stats()
            if not self.active_sockets:
                logger.info("Minecraft сервер отключился от моста.")
                self.create_tracked_task(self.update_bot_presence())

        return ws

    async def sync_staff_to_minecraft(self):
        """Синхронизирует ники администрации/модерации из Discord с сервером Minecraft"""
        try:
            guild = self.bot.get_guild(Config.GUILD_ID) if Config.GUILD_ID else (self.bot.guilds[0] if self.bot.guilds else None)
            if not guild:
                return
            staff_names = []
            for member in guild.members:
                if any(r.id in Config.MOD_ROLE_IDS for r in member.roles) or member.guild_permissions.administrator:
                    linked = self.db.get_linked_account_by_discord(member.id)
                    if linked and linked.get("player_name"):
                        staff_names.append(linked["player_name"])
            if staff_names:
                await self.broadcast_packet({"type": "sync_staff", "staff": staff_names})
        except Exception as e:
            logger.debug(f"Ошибка синхронизации персонала с Minecraft: {e}")

    async def update_bot_presence(self, force: bool = False):
        """Обновляет статус Discord бота в зависимости от режима техработ и онлайна (с защитой от Gateway Rate Limit).

        force=True игнорирует 10-секундный троттлинг (используется при on_ready).
        """
        now = time.monotonic()
        if not force and now - getattr(self, "_last_presence_time", 0.0) < 10.0:
            return
        self._last_presence_time = now
        try:
            if getattr(self, "maintenance_enabled", False):
                activity = discord.CustomActivity(name="Техработы • Vanilla Land")
                await self.bot.change_presence(status=discord.Status.dnd, activity=activity)
            else:
                has_active = bool(getattr(self, "active_sockets", None))
                cnt = getattr(self, "mc_online", 0)
                if not has_active:
                    activity = discord.CustomActivity(name=Config.SERVER_IP)
                    await self.bot.change_presence(status=discord.Status.online, activity=activity)
                elif cnt > 0:
                    activity = discord.CustomActivity(name=f"Онлайн: {cnt} • {Config.SERVER_IP}")
                    await self.bot.change_presence(status=discord.Status.online, activity=activity)
                else:
                    activity = discord.CustomActivity(name=Config.SERVER_IP)
                    await self.bot.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            logger.debug(f"Ошибка обновления статуса бота: {e}")

    async def send_login_push_alert(self, discord_id: int, player_name: str, ip: str):
        """Отправляет тихое пуш-уведомление в ЛС Discord при успешном входе с доверенного IP"""
        try:
            user = self.bot.get_user(discord_id) or await self.bot.fetch_user(discord_id)
            if not user:
                return
            now_ts = int(time.time())
            embed = discord.Embed(
                title="🔔 Вход в игру • Vanilla Land",
                description=(
                    f"Выполнен успешный вход в игровой аккаунт **`{player_name}`**.\n"
                    "Сессия с этого IP уже была подтверждена ранее.\n\n"
                    "> Если вы не заходили на сервер, нажмите кнопку экстренной блокировки ниже для немедленного отключения игрока и сброса доверенных IP."
                ),
                color=Colors.BLUE,
            )
            embed.add_field(name="👤 Аккаунт", value=f"**`{player_name}`**", inline=True)
            embed.add_field(name="🌐 IP-адрес", value=f"`{ip}`", inline=True)
            embed.add_field(name="🕒 Время входа", value=f"<t:{now_ts}:T> (<t:{now_ts}:R>)", inline=True)
            embed.set_footer(text="Vanilla Land Security • Push-уведомление о входе")
            skin_url = get_skin_avatar_url(player_name, None, self.db)
            if skin_url:
                embed.set_thumbnail(url=skin_url)

            view = LoginAlertView(self, player_name, discord_id)
            await user.send(embed=embed, view=view)
        except Exception as e:
            logger.debug(f"Не удалось отправить пуш-уведомление о входе пользователю {discord_id}: {e}")

    def get_events_channel(self) -> Optional[discord.TextChannel]:
        saved_id = self.db.get_setting("events_channel_id")
        if saved_id and saved_id.isdigit():
            ch = self.bot.get_channel(int(saved_id))
            if isinstance(ch, discord.TextChannel):
                return ch

        ch = self.bot.get_channel(Config.EVENTS_CHANNEL_ID)
        if ch and isinstance(ch, discord.TextChannel):
            return ch

        for guild in self.bot.guilds:
            for c in guild.text_channels:
                low = c.name.lower().strip()
                if any(k in low for k in ("событи", "events", "входы", "сервер-лог", "игровой-лог")):
                    return c

        # Fallback на bridge channel
        fb = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
        return fb if isinstance(fb, discord.TextChannel) else None

    # --- ОБРАБОТКА ПАКЕТОВ ОТ MINECRAFT ---
    async def handle_minecraft_packet(self, data: dict, ws=None):
        p_type = data.get("type")

        # При входе игрока сразу же фиксируем IP в базе данных до отправки событий
        if p_type == "join":
            join_p = data.get("player")
            join_ip = data.get("ip")
            if join_p and join_ip:
                self.db.record_player_ip(join_p, join_ip)

        self.bot.dispatch("bridge_packet", p_type, data)

        # 0. Application-level Keep-Alive Ping/Pong (гарантирует постоянную активность сокета)
        if p_type == "ping":
            await self.broadcast_packet({
                "type": "pong",
                "timestamp": data.get("time", time.time())
            })
            return
        elif p_type == "pong":
            return

        # 1. Глобальный чат из Minecraft (Идет строго в основной чат моста)
        if p_type == "chat":
            player = data.get("player", "Игрок")
            message = data.get("message", "").strip()
            skin = data.get("skin", "").strip()
            item_data = data.get("item")

            # Дедупликация входящих сообщений из Minecraft
            chat_in_key = f"{player}:{message}"
            now = time.time()
            if (now - self._recent_chat_in.get(chat_in_key, 0.0)) < 4.0:
                logger.debug("Игнорирование дублирующего сообщения чата из Minecraft от %s", player)
                return
            self._recent_chat_in[chat_in_key] = now
            if len(self._recent_chat_in) > 200:
                self._recent_chat_in = {k: v for k, v in self._recent_chat_in.items() if (now - v) < 60.0}

            if skin:
                self.db.record_player_skin(player, skin)
            if message:
                processed_msg = await self.process_minecraft_mentions(message)
                item_emb = self.build_item_preview_embed(item_data) if item_data else None
                await self.send_to_discord_webhook(player, processed_msg, skin, embed=item_emb)

        # 2. Переподключение сокета моста (без перезагрузки сервера)
        elif p_type == "bridge_reconnect":
            uptime_ms = data.get("uptime_ms", 0)
            if uptime_ms:
                self.mc_server_start_time = time.time() - (float(uptime_ms) / 1000.0)
            logger.info(f"Minecraft мост переподключился (сервер стабильно работает, uptime: {uptime_ms/1000:.1f}с)")
            self.server_start_announced = True
            self.create_tracked_task(self.update_bot_presence())
            return

        # 3. Жизненный цикл сервера (Старт / Рестарт)
        elif p_type == "lifecycle":
            event = data.get("event")
            now = time.time()
            if event == "start":
                uptime_ms = data.get("uptime_ms")
                if uptime_ms:
                    self.mc_server_start_time = time.time() - (float(uptime_ms) / 1000.0)
                # 1. Если сервер работает уже более 60 секунд (или это переподключение сокета) — НИКОГДА не шлем анонс старта
                if uptime_ms is not None and uptime_ms > 60000:
                    logger.info(f"Игнорирование повторного сигнала старта (uptime: {uptime_ms/1000:.1f}с — обычный реконнект)")
                    self.server_start_announced = True
                    self.create_tracked_task(self.update_bot_presence())
                    return

                # 2. Если анонс старта уже был сделан и сервер с тех пор НЕ останавливался — НИКОГДА не шлем дубль
                if self.server_start_announced and not self.had_explicit_server_stop:
                    logger.info("Пропущен повторный сигнал старта: сервер уже активен и не останавливался (реконнект)")
                    self.create_tracked_task(self.update_bot_presence())
                    return

                # 3. Если бот запустился/перезапустился и подключился к УЖЕ РАБОТАЮЩЕМУ серверу (не было stop) — не спамим
                if not self.had_explicit_server_stop and (now - self.bot_start_time) < 600:
                    logger.info("Первое подключение моста после рестарта бота к работающему серверу — анонс старта опущен")
                    self.server_start_announced = True
                    self.create_tracked_task(self.update_bot_presence())
                    return

                # 4. Cooldown минимум 300 секунд (5 минут) между любыми анонсами старта
                if now - getattr(self, "_last_lifecycle_start_time", 0) < 300:
                    logger.info("Пропущен сигнал старта сервера по таймауту (cooldown 300s)")
                    self.create_tracked_task(self.update_bot_presence())
                    return

                self._last_lifecycle_start_time = now
                self.server_start_announced = True
                self.had_explicit_server_stop = False
                text = "**Сервер запущен и доступен для игры!**"
            else:
                self.server_start_announced = False
                self.had_explicit_server_stop = True
                text = "**Сервер уходит на перезагрузку...**"

            self.create_tracked_task(self.update_bot_presence())
            events_ch = self.get_events_channel()
            # Отправляем ТОЛЬКО в канал событий, чтобы не засорять игровой чат моста
            if events_ch:
                await events_ch.send(text)
            else:
                bridge_ch = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
                if bridge_ch and isinstance(bridge_ch, discord.TextChannel):
                    await bridge_ch.send(text)

        # 4. Метрики (Онлайн, TPS, MSPT, память и список игроков)
        elif p_type == "stats":
            old_online = self.mc_online
            raw_players = data.get("players", [])
            sid = id(ws) if ws is not None else 0
            self._socket_stats[sid] = {
                "online": int(data.get("online", 0)),
                "max": int(data.get("max", 0)),
                "tps": float(data.get("tps", 20.0)),
                "mspt": float(data.get("mspt", 20.0)),
                "mem_used": int(data.get("mem_used", 0)),
                "mem_max": int(data.get("mem_max", 0)),
                "players": [str(p) for p in raw_players if p] if isinstance(raw_players, list) else [],
            }
            self._recompute_stats()
            online_changed = (self.mc_online != old_online)
            self.last_stats_time = time.time()
            self.pending_channel_update = True
            self.was_connected = True
            if not self.had_explicit_server_stop:
                self.server_start_announced = True

            if online_changed:
                self.create_tracked_task(self.update_bot_presence())

            # Мониторинг просадки TPS (< 16.0)
            now = time.time()
            if self.mc_tps < 16.0 and (now - self.last_tps_alert_time) > 600:
                self.last_tps_alert_time = now
                admin_ch = self.bot.get_channel(Config.ADMIN_LOG_CHANNEL_ID) or self.bot.get_channel(Config.LOG_CHANNEL_ID)
                if admin_ch and isinstance(admin_ch, discord.TextChannel):
                    embed = discord.Embed(
                        title="Внимание: Просадка TPS на сервере",
                        description=(
                            f"**Текущий TPS:** `{self.mc_tps:.2f}` (норма: 20.0)\n"
                            f"**Онлайн игроков:** `{self.mc_online} / {self.mc_max}`\n\n"
                            "На сервере возможна перегрузка или задержки."
                        ),
                        color=Colors.YELLOW,
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text="Vanilla Land • Мониторинг")
                    try:
                        await admin_ch.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Не удалось отправить TPS алерт: {e}")

        # 4. Вход игрока (Идет строго в канал событий 1556209087920873542)
        elif p_type == "join":
            player = data.get("player")
            ip = data.get("ip")
            skin = data.get("skin")
            if player:
                if ip:
                    self.db.record_player_ip(player, ip)
                if skin:
                    self.db.record_player_skin(player, skin)
                events_ch = self.get_events_channel()
                if events_ch:
                    clean_player = discord.utils.escape_markdown(str(player))
                    await events_ch.send(f"**{clean_player}** подключился к серверу.", allowed_mentions=discord.AllowedMentions.none())

                    # Проверка медиа/стримера
                    if self.is_streamer_player(events_ch.guild, player):
                        await events_ch.send(f"Стример **{clean_player}** зашёл на сервер.", allowed_mentions=discord.AllowedMentions.none())

        # 5. Выход игрока (Идет строго в канал событий 1556209087920873542)
        elif p_type == "quit":
            player = data.get("player")
            if player:
                events_ch = self.get_events_channel()
                if events_ch:
                    clean_player = discord.utils.escape_markdown(str(player))
                    await events_ch.send(f"**{clean_player}** вышел с сервера.", allowed_mentions=discord.AllowedMentions.none())

        # 6. Смерть игрока (Идет строго в канал событий 1556209087920873542 + пишется в базу с координатами)
        elif p_type == "death":
            player = data.get("player", "Игрок")
            raw_death = data.get("death_message", "")
            world = data.get("world", "world")
            try:
                x = int(round(float(data.get("x", 0))))
                y = int(round(float(data.get("y", 0))))
                z = int(round(float(data.get("z", 0))))
            except (ValueError, TypeError):
                x, y, z = 0, 0, 0
            translated_death = translate_death_message(raw_death, player)

            # Запись в статистику смертей («Премия Дарвина»)
            self.db.record_player_death(player, translated_death)
            self.db.record_death_coords(player, world, x, y, z, translated_death)

            events_ch = self.get_events_channel()
            if events_ch:
                await events_ch.send(f"{translated_death}")

        # 7. Ошибка доставки ЛС (Игрок оффлайн)
        elif p_type == "dm_error":
            target_id_str = data.get("target_id")
            player = data.get("player", "Игрок")
            if target_id_str:
                try:
                    target_id = int(target_id_str)
                    user = self.bot.get_user(target_id) or await self.bot.fetch_user(target_id)
                    if user:
                        await user.send(f"Игрок **{player}** сейчас не на сервере (оффлайн), сообщение не доставлено.")
                except Exception as suppressed_exc:
                    logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        # 8. Объявление из Minecraft (/bc, /vbc)
        elif p_type == "mc_broadcast":
            author = data.get("author", "Сервер")
            text = data.get("text", "").strip()
            if text:
                bridge_ch = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
                if bridge_ch and isinstance(bridge_ch, discord.TextChannel):
                    embed = discord.Embed(
                        title="Объявление сервера Minecraft",
                        description=text,
                        color=Colors.YELLOW,
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text=f"Отправил: {author} • Vanilla Land")
                    try:
                        await bridge_ch.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Не удалось отправить mc_broadcast в канал моста: {e}")

        # 9. Ответы на запросы данных из Minecraft (world_data, player_data, chunks_data, top_data)
        elif p_type in ("world_data", "player_data", "chunks_data", "top_data"):
            if p_type == "player_data":
                p_name = data.get("player")
                p_skin = data.get("skin")
                p_ip = data.get("ip")
                if p_name and p_skin:
                    self.db.record_player_skin(p_name, p_skin)
                if p_name and p_ip and p_ip != "N/A":
                    self.db.record_player_ip(p_name, p_ip)
            query_id = data.get("query_id")
            if query_id and query_id in self.pending_queries:
                fut = self.pending_queries.pop(query_id)
                if not fut.done():
                    fut.set_result(data)

        # 9. Ответ на ЛС из Minecraft в Discord (DM Reply)
        elif p_type == "dm_reply":
            target_id_str = data.get("target_id")
            player = data.get("player", "Игрок")
            content = data.get("content", "").strip()
            if target_id_str and content:
                try:
                    target_id = int(target_id_str)
                    user = self.bot.get_user(target_id) or await self.bot.fetch_user(target_id)
                    if user:
                        embed = discord.Embed(
                            title=f"Ответ из игры от {player}",
                            description=f"**{player}:** {content}",
                            color=Colors.GREEN,
                            timestamp=datetime.now(timezone.utc),
                        )
                        embed.set_footer(text="Vanilla Land • ЛС моста")
                        view = DmReplyView(self, player)
                        dm_msg = await user.send(embed=embed, view=view)
                        self.db.save_dm_reply_target(dm_msg.id, player)
                except Exception as e:
                    logger.error(f"Не удалось доставить ЛС пользователю {target_id_str}: {e}")

        # 10. Режим техработ из Minecraft (/maintenance в игре или консоли)
        elif p_type == "maintenance":
            enabled = bool(data.get("enabled", False))
            reason = str(data.get("reason", "Технические работы"))
            self.maintenance_enabled = enabled
            self.maintenance_reason = reason
            if not enabled:
                self.was_restarting = False
            self.create_tracked_task(self.update_bot_presence())

            events_ch = self.get_events_channel()
            if enabled:
                embed = discord.Embed(
                    title="🔧 Внимание! Сервер переведён в режим технических работ",
                    description=f"**Причина:** {reason}\n\n*Вход на сервер временно ограничен администрацией.*",
                    color=Colors.YELLOW,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text="Vanilla Land • Администрация")
            else:
                embed = discord.Embed(
                    title="Технические работы завершены",
                    description="Сервер снова открыт для всех желающих. Приятной игры!",
                    color=Colors.GREEN,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_footer(text="Vanilla Land")

            if events_ch:
                await events_ch.send(embed=embed)

        # 11. Запрос создания кода привязки из Minecraft (/link)
        elif p_type in ("mc_create_link_code", "mc_request_link_code"):
            player = data.get("player", "").strip()
            if not player:
                return

            already = self.db.get_linked_account_by_mc(player)
            if already:
                user_tag = "Discord"
                try:
                    u = self.bot.get_user(already["discord_user_id"])
                    if u:
                        user_tag = f"@{u.name}"
                except Exception as suppressed_exc:
                    logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
                await self.broadcast_packet({
                    "type": "link_result",
                    "player": player,
                    "success": False,
                    "message": f"Ваш игровой аккаунт уже привязан к {user_tag}! Повторная привязка невозможна. Сначала выполните !unlink в Discord.",
                })
                return

            code = data.get("code")
            if not code or p_type == "mc_request_link_code":
                code = f"{secrets.randbelow(900000) + 100000}"

            self.db.create_link_code(player_name=player, discord_user_id=None, code=code, lifetime_sec=600)
            logger.info(f"Создан одноразовый код привязки для игрока {player} из Minecraft: {code}")

            await self.broadcast_packet({
                "type": "mc_link_code_generated",
                "player": player,
                "code": code,
            })

        # 12. Попытка привязки аккаунта вводом кода в Minecraft (/link <код>)
        elif p_type == "link_attempt":
            player = data.get("player", "").strip()
            uuid_str = data.get("uuid", "").strip()
            code = data.get("code", "").strip()
            ip = data.get("ip", "127.0.0.1").strip()

            if player and code:
                # 1. Проверяем, не привязан ли уже этот Minecraft игрок
                already_mc = self.db.get_linked_account_by_mc(player)
                if already_mc:
                    user_tag = "Discord"
                    try:
                        u = self.bot.get_user(already_mc["discord_user_id"])
                        if u:
                            user_tag = f"@{u.name}"
                    except Exception as suppressed_exc:
                        logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
                    await self.broadcast_packet({
                        "type": "link_result",
                        "player": player,
                        "success": False,
                        "message": f"Ваш игровой аккаунт уже привязан к {user_tag}! Повторная привязка невозможна.",
                    })
                    return

                info = self.db.consume_link_code(code)
                if info and info.get("discord_user_id"):
                    target_discord_id = info["discord_user_id"]

                    # 2. Проверяем, не привязан ли уже этот Discord аккаунт
                    already_dc = self.db.get_linked_account_by_discord(target_discord_id)
                    if already_dc:
                        await self.broadcast_packet({
                            "type": "link_result",
                            "player": player,
                            "success": False,
                            "message": f"К этому Discord профилю уже привязан аккаунт {already_dc['player_name']}! Один Discord = один аккаунт.",
                        })
                        return

                    success = self.db.link_account(player, uuid_str, target_discord_id, two_factor=1)
                    if success:
                        self.db.trust_ip_session(player, ip, Config.IP_SESSION_HOURS)
                        user = self.bot.get_user(target_discord_id)
                        if not user:
                            try:
                                user = await self.bot.fetch_user(target_discord_id)
                            except Exception as suppressed_exc:
                                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
                        tag = str(user) if user else f"ID: {target_discord_id}"

                        await self.broadcast_packet({
                            "type": "link_result",
                            "player": player,
                            "success": True,
                            "discord_tag": tag,
                            "kick_relogin": True,
                            "message": "Аккаунт успешно привязан",
                        })

                        if user:
                            embed = AG.embed(
                                title="✨ Аккаунт успешно привязан • Vanilla Land",
                                description=(
                                    f"Ваш аккаунт Minecraft **`{player}`** успешно привязан к Discord!\n\n"
                                    f"• **Двухфакторная защита (2FA):** `[Включена]`\n"
                                    f"• **Доверенный IP:** `{ip}` *(сессия на {int(Config.IP_SESSION_HOURS)} ч.)*\n\n"
                                    "> Теперь при входе с новых IP-адресов бот будет присылать подтверждение в этот чат.\n"
                                    "> Управлять защитой и доверенными IP можно командой `!security`."
                                ),
                                color=Colors.GREEN,
                                thumbnail=get_skin_avatar_url(player, None, self.db),
                            )
                            view = AccountSecurityView(self, target_discord_id, player)
                            try:
                                await user.send(embed=embed, view=view)
                            except Exception as e:
                                logger.error(f"Не удалось отправить подтверждение привязки пользователю {target_discord_id}: {e}")
                    else:
                        await self.broadcast_packet({
                            "type": "link_result",
                            "player": player,
                            "success": False,
                            "message": "Ошибка: этот ник или Discord аккаунт уже привязан!",
                        })
                else:
                    await self.broadcast_packet({
                        "type": "link_result",
                        "player": player,
                        "success": False,
                        "message": "Неверный или просроченный код. Получите код через !link в Discord!",
                    })

        # 13. Проверка безопасности при входе (Check Login 2FA)
        elif p_type == "check_login":
            player = data.get("player", "").strip()
            uuid_str = data.get("uuid", "").strip()
            ip = data.get("ip", "127.0.0.1").strip()

            if not player:
                return

            # Если 2FA отключена в боте (авторизация выполняется прокси Victime / Selene)
            if not Config.ENABLE_LOGIN_2FA:
                self.db.record_login(player, ip, status="SUCCESS")
                await self.broadcast_packet({"type": "login_verdict", "player": player, "status": "2fa_disabled"})
                return

            linked = self.db.get_linked_account_by_mc(player)
            if not linked:
                # Аккаунт не привязан к Discord — свободный вход без 2FA
                await self.broadcast_packet({"type": "login_verdict", "player": player, "status": "not_linked"})
                return

            raw_trust = linked.get("trust_duration_hours", Config.IP_SESSION_HOURS)
            try:
                trust_hrs = int(round(float(raw_trust)))
            except (TypeError, ValueError):
                trust_hrs = int(round(float(Config.IP_SESSION_HOURS)))

            if not linked.get("two_factor_enabled", True):
                # Игрок отключил 2FA подтверждение входов в настройках (/security)
                self.db.record_login(player, ip, status="SUCCESS")
                if linked.get("login_alerts_enabled", True):
                    self.create_tracked_task(self.send_login_push_alert(linked["discord_user_id"], player, ip))
                await self.broadcast_packet({"type": "login_verdict", "player": player, "status": "2fa_disabled"})
                return

            # Проверяем, доверен ли IP и не истекли ли часы сессии
            if self.db.is_ip_trusted(player, ip):
                self.db.record_login(player, ip, status="SUCCESS")
                if linked.get("login_alerts_enabled", True):
                    self.create_tracked_task(self.send_login_push_alert(linked["discord_user_id"], player, ip))
                await self.broadcast_packet({
                    "type": "login_verdict",
                    "player": player,
                    "status": "trusted_session",
                    "ip": ip,
                    "trust_hours": trust_hrs,
                })
                return

            # Требуется подтверждение входа 2FA!
            code = f"{secrets.randbelow(900000) + 100000}"
            discord_id = linked["discord_user_id"]
            expires_at = time.time() + Config.LOGIN_2FA_TIMEOUT_SEC
            session_id = uuid.uuid4().hex
            self.pending_2fa[player.lower()] = {
                "code": code,
                "ip": ip,
                "discord_id": discord_id,
                "expires_at": expires_at,
                "session_id": session_id,
            }

            user = self.bot.get_user(discord_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(discord_id)
                except Exception as suppressed_exc:
                    logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

            dm_sent = False
            if user:
                view = TwoFactorVerifyView(self, player, ip, code, discord_id, expires_at, session_id=session_id)
                embed = view.build_verify_embed()
                try:
                    msg = await user.send(embed=embed, view=view)
                    view.message = msg
                    self.pending_2fa[player.lower()]["message"] = msg
                    self.pending_2fa[player.lower()]["view"] = view
                    dm_sent = True
                except discord.Forbidden:
                    logger.warning(f"У пользователя {discord_id} закрыты личные сообщения в Discord для 2FA.")
                except Exception as e:
                    logger.error(f"Не удалось отправить 2FA алерт пользователю {discord_id}: {e}")

            if not dm_sent:
                # Отправляем интерактивный алерт в канал верификации или команд с упоминанием игрока
                target_channel = self.bot.get_channel(Config.VERIFICATION_CHANNEL_ID) or self.bot.get_channel(Config.COMMANDS_CHANNEL_ID) or self.get_events_channel()
                if target_channel and isinstance(target_channel, discord.TextChannel):
                    pub_view = TwoFactorPublicAlertView(self, player, ip, code, discord_id, expires_at, session_id=session_id)
                    pub_embed = discord.Embed(
                        title="⚠️ Закрыты личные сообщения Discord • Vanilla Land 2FA",
                        description=(
                            f"🔔 <@{discord_id}>, зафиксирована попытка входа в аккаунт **`{player}`**, но бот не смог отправить код в ваши личные сообщения Discord!\n\n"
                            "**Как подтвердить вход прямо сейчас:**\n"
                            "1. Нажмите зелёную кнопку **`Подтвердить вход`** ниже;\n"
                            "2. Или откройте ЛС в Discord: *Настройки -> Конфиденциальность -> Личные сообщения от участников сервера* и введите в игре `/code resend`."
                        ),
                        color=Colors.YELLOW,
                    )
                    pub_embed.add_field(name="👤 Аккаунт", value=f"**`{player}`**", inline=True)
                    pub_embed.add_field(name="🌐 IP-адрес", value=f"`{ip}`", inline=True)
                    pub_embed.add_field(name="⏳ Истекает", value=f"<t:{int(expires_at)}:R>", inline=True)
                    pub_embed.set_footer(text="Vanilla Land Security • Личные сообщения закрыты")
                    skin_url = get_skin_avatar_url(player, None, self.db)
                    if skin_url:
                        pub_embed.set_thumbnail(url=skin_url)

                    try:
                        pub_msg = await target_channel.send(content=f"<@{discord_id}>", embed=pub_embed, view=pub_view)
                        pub_view.message = pub_msg
                        self.pending_2fa[player.lower()]["public_alert_msg"] = pub_msg
                    except Exception as e:
                        logger.warning(f"Не удалось отправить публичный 2FA алерт: {e}")

                await self.broadcast_packet({
                    "type": "login_verdict",
                    "player": player,
                    "status": "dm_closed",
                    "code": code,
                    "ip": ip,
                    "timeout": Config.LOGIN_2FA_TIMEOUT_SEC,
                    "trust_hours": trust_hrs,
                    "session_id": session_id,
                })
            else:
                await self.broadcast_packet({
                    "type": "login_verdict",
                    "player": player,
                    "status": "require_2fa",
                    "code": code,
                    "ip": ip,
                    "timeout": Config.LOGIN_2FA_TIMEOUT_SEC,
                    "trust_hours": trust_hrs,
                    "session_id": session_id,
                })

        # 14. Игрок подтвердил 2FA вводом кода в игре (/code <код>)
        elif p_type == "2fa_code_verified":
            player = data.get("player", "").strip()
            ip = data.get("ip", "127.0.0.1").strip()
            if player:
                linked = self.db.get_linked_account_by_mc(player)
                raw_trust = linked.get("trust_duration_hours", Config.IP_SESSION_HOURS) if linked else Config.IP_SESSION_HOURS
                try:
                    trust_hrs = int(round(float(raw_trust)))
                except (TypeError, ValueError):
                    trust_hrs = int(round(float(Config.IP_SESSION_HOURS)))
                self.db.trust_ip_session(player, ip, trust_hrs)
                self.db.record_login(player, ip, status="SUCCESS")
                pending = self.pending_2fa.pop(player.lower(), None)
                if pending:
                    # Удаляем публичный алерт если был
                    if "public_alert_msg" in pending and pending["public_alert_msg"]:
                        try:
                            await pending["public_alert_msg"].delete()
                        except Exception as suppressed_exc:
                            logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

                    # Обновляем сообщение в ЛС
                    if "message" in pending and pending["message"]:
                        msg = pending["message"]
                        try:
                            exp_session_ts = int(time.time() + (trust_hrs * 3600)) if trust_hrs > 0 else int(time.time())
                            exp_session_str = f"<t:{exp_session_ts}:F> (<t:{exp_session_ts}:R>)" if trust_hrs > 0 else "*Строгий режим (до следующего входа)*"

                            embed = discord.Embed(
                                title="✔ Вход успешно подтверждён • Vanilla Land",
                                description=(
                                    f"Вход в игровой аккаунт **`{player}`** подтверждён вводом кода на сервере!\n"
                                    "Игрок успешно авторизован, приятной игры!\n\n"
                                    f"• **Доверенный IP:** `{ip}`\n"
                                    f"• **Срок действия сессии:** {exp_session_str}"
                                ),
                                color=Colors.GREEN,
                            )
                            embed.set_footer(text="Vanilla Land Security • Вход подтверждён кодом")
                            skin_url = get_skin_avatar_url(player, None, self.db)
                            if skin_url:
                                embed.set_thumbnail(url=skin_url)
                            await msg.edit(embed=embed, view=None)
                        except Exception as suppressed_exc:
                            logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        # 14.1 Повторный запрос отправки кода из игры (/code resend)
        elif p_type == "2fa_resend_code":
            player = data.get("player", "").strip()
            if not player:
                return

            if not self.resend_rate_ok(player):
                await self.broadcast_packet({
                    "type": "2fa_resend_result",
                    "player": player,
                    "success": False,
                    "message": "Слишком часто. Повторная отправка кода — не более 3 раз за 10 минут.",
                })
                return

            pending = self.pending_2fa.get(player.lower())
            if not pending:
                await self.broadcast_packet({
                    "type": "2fa_resend_result",
                    "player": player,
                    "success": False,
                    "message": "Нет активной сессии подтверждения 2FA.",
                })
                return

            code = pending["code"]
            ip = pending["ip"]
            discord_id = pending["discord_id"]
            expires_at = pending["expires_at"]

            user = self.bot.get_user(discord_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(discord_id)
                except Exception as suppressed_exc:
                    logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

            dm_sent = False
            if user:
                view = TwoFactorVerifyView(
                    self, player, ip, code, discord_id, expires_at, session_id=pending.get("session_id", "")
                )
                embed = view.build_verify_embed()
                try:
                    msg = await user.send(embed=embed, view=view)
                    view.message = msg
                    pending["message"] = msg
                    pending["view"] = view
                    dm_sent = True
                except discord.Forbidden:
                    logger.warning(f"У пользователя {discord_id} всё ещё закрыты ЛС для 2FA.")
                except Exception as e:
                    logger.error(f"Ошибка повторной отправки 2FA в ЛС: {e}")

            if dm_sent:
                # Если ранее висел публичный алерт, удаляем его
                if "public_alert_msg" in pending and pending["public_alert_msg"]:
                    try:
                        await pending["public_alert_msg"].delete()
                    except Exception as suppressed_exc:
                        logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
                    pending["public_alert_msg"] = None

                await self.broadcast_packet({
                    "type": "2fa_resend_result",
                    "player": player,
                    "success": True,
                    "message": "Одноразовый код успешно отправлен в личные сообщения Discord!",
                })
            else:
                await self.broadcast_packet({
                    "type": "2fa_resend_result",
                    "player": player,
                    "success": False,
                    "message": "Личные сообщения в Discord всё ещё закрыты! Откройте ЛС в настройках конфиденциальности.",
                })

        # 15. Синхронизация таймера техработ/рестарта из Minecraft
        elif p_type == "maintenance_countdown":
            mode = data.get("mode", "lock")
            reason = data.get("reason", "Плановые работы на сервере")
            seconds = int(data.get("seconds", 0))
            self.maintenance_reason = reason
            if mode == "restart":
                self.was_restarting = True
                events_ch = self.get_events_channel()
                if events_ch:
                    if seconds == 5:
                        await events_ch.send("🔴 **РЕСТАРТ через 5 секунд!** Возвращайтесь — станет лучше!")
                    elif seconds > 0:
                        mins = seconds // 60
                        secs = seconds % 60
                        time_str = f"{mins} мин. {secs} сек." if mins > 0 else f"{secs} сек."
                        await events_ch.send(f"⚠️ **Запланирован рестарт сервера через {time_str}!** Причина: `{reason}`")

        # 17. Синхронизация отмены техработ/рестарта из Minecraft
        elif p_type == "maintenance_countdown_cancel":
            self.maintenance_enabled = False
            self.was_restarting = False
            await self.update_bot_presence()

        # 18. Внутриигровая почта: отправка письма (/mail send)
        elif p_type == "send_mail":
            sender = data.get("sender", "Неизвестный").strip()
            recipient = data.get("recipient", "").strip()
            text = data.get("text", "").strip()
            if sender and recipient and text:
                mail_id = self.db.send_offline_mail(sender, recipient, text)
                await self.broadcast_packet({
                    "type": "mail_result",
                    "sender": sender,
                    "recipient": recipient,
                    "success": True,
                    "mail_id": mail_id,
                })
                # Отправляем уведомление в ЛС Discord, если получатель привязан
                linked = self.db.get_linked_account_by_mc(recipient)
                if linked and linked.get("discord_user_id"):
                    user = self.bot.get_user(linked["discord_user_id"])
                    if user:
                        try:
                            emb = AG.embed(
                                title="✉️ Новое письмо в игре • Vanilla Land",
                                description=(
                                    f"Игрок **`{sender}`** отправил вам письмо на сервере:\n\n"
                                    f"> {text}\n\n"
                                    f"*Прочитать и ответить можно в игре: `/mail send {sender} <сообщение>`*"
                                ),
                                footer="Vanilla Land • Почта",
                            )
                            await user.send(embed=emb)
                        except Exception:
                            pass

        # 19. Внутриигровая почта: получение писем (/mail read)
        elif p_type == "get_mail":
            player = data.get("player", "").strip()
            if player:
                unread = self.db.get_unread_mail(player)
                self.db.mark_mail_read(player)
                await self.broadcast_packet({
                    "type": "mail_inbox",
                    "player": player,
                    "mails": unread,
                })

        # 20. Внутриигровая почта: проверка количества писем при входе
        elif p_type == "check_mail":
            player = data.get("player", "").strip()
            if player:
                count = self.db.count_unread_mail(player)
                await self.broadcast_packet({
                    "type": "mail_notify",
                    "player": player,
                    "count": count,
                })

    def is_streamer_player(self, guild: Optional[discord.Guild], player_name: str) -> bool:
        if not guild:
            return False
        for m in guild.members:
            if m.display_name.lower() == player_name.lower() or m.name.lower() == player_name.lower():
                if any(r.name.lower() in ("стример", "медиа", "youtube", "twitch") for r in m.roles):
                    return True
        return False

    # --- ОБРАБОТКА УПОМИНАНИЙ ИЗ MINECRAFT В DISCORD ---
    async def process_minecraft_mentions(self, text: str) -> str:
        text = text.replace("@everyone", "everyone").replace("@here", "here")
        channel = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
        if not channel or not hasattr(channel, "guild") or not channel.guild:
            return text

        guild = channel.guild
        words = text.split()
        new_words = []
        for word in words:
            if word.startswith("@") and len(word) > 2:
                target_name = word[1:].lower()
                matched_member = None
                for m in guild.members:
                    if m.display_name.lower() == target_name or m.name.lower() == target_name:
                        matched_member = m
                        break
                if matched_member:
                    new_words.append(matched_member.mention)
                    continue
            new_words.append(word)
        return " ".join(new_words)

    def build_item_preview_embed(self, item_data: dict) -> Optional[discord.Embed]:
        """Генерирует карточку предпросмотра предмета в руке игрока ([item])"""
        if not isinstance(item_data, dict):
            return None
        raw_name = item_data.get("name") or item_data.get("type", "Предмет")
        mat = item_data.get("type", "UNKNOWN")
        amount = item_data.get("amount", 1)
        durability = item_data.get("durability")
        max_durability = item_data.get("max_durability")
        enchants = item_data.get("enchants", [])
        lore = item_data.get("lore", [])

        title_qty = f" x{amount}" if amount > 1 else ""
        embed = discord.Embed(
            title=f"📦 {raw_name}{title_qty}",
            color=Colors.GOLD if enchants else Colors.BLUE,
        )

        desc_lines = []
        if durability is not None and max_durability:
            pct = int(round((durability / max_durability) * 100))
            desc_lines.append(f"• **Прочность:** `{durability} / {max_durability}` ({pct}%)")

        if enchants:
            ench_str = "\n".join([f"• `{e.get('name', 'Чар')} {e.get('level', 1)}`" for e in enchants])
            embed.add_field(name="Зачарования", value=ench_str, inline=False)

        if lore:
            lore_clean = "\n".join([f"*{l}*" for l in lore if l])
            if lore_clean:
                embed.add_field(name="Описание", value=lore_clean, inline=False)

        if desc_lines:
            embed.description = "\n".join(desc_lines)

        embed.set_footer(text=f"Vanilla Land • Предмет из руки • {mat}")
        return embed

    # --- ОТПРАВКА В DISCORD ЧЕРЕЗ ВЕБХУК В ОСНОВНОЙ ЧАТ МОСТА ---
    async def send_to_discord_webhook(
        self, player_name: str, content: str, skin: str = "", embed: Optional[discord.Embed] = None
    ):
        channel = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        if not self.webhook:
            async with self._webhook_lock:
                if not self.webhook:
                    try:
                        webhooks = await channel.webhooks()
                        for wh in webhooks:
                            if wh.name == "VanillaLand Bridge":
                                self.webhook = wh
                                break
                        if not self.webhook:
                            self.webhook = await channel.create_webhook(name="VanillaLand Bridge")
                    except Exception as e:
                        logger.error(f"Не удалось получить или создать вебхук: {e}")

        avatar_url = get_skin_avatar_url(player_name, skin, self.db)
        embeds = [embed] if embed else []

        try:
            if self.webhook:
                await self.webhook.send(
                    content=content,
                    username=player_name,
                    avatar_url=avatar_url,
                    embeds=embeds,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            else:
                if embed:
                    await channel.send(f"**<{player_name}>** {content}", embed=embed)
                else:
                    await channel.send(f"**<{player_name}>** {content}")
        except discord.NotFound:
            self.webhook = None
            try:
                self.webhook = await channel.create_webhook(name="VanillaLand Bridge")
                await self.webhook.send(
                    content=content,
                    username=player_name,
                    avatar_url=avatar_url,
                    embeds=embeds,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except Exception:
                if embed:
                    await channel.send(f"**<{player_name}>** {content}", embed=embed)
                else:
                    await channel.send(f"**<{player_name}>** {content}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения через вебхук: {e}")

    # --- ОТПРАВКА ИЗ DISCORD В MINECRAFT ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.webhook_id:
            return
        if message.channel.id != Config.BRIDGE_CHANNEL_ID:
            return

        raw_text = message.clean_content.strip()

        # 1. Перенаправление команд в специализированный канал команд
        command_prefixes = tuple(Config.COMMAND_PREFIXES + [".", "?", "!"])
        if raw_text.startswith(command_prefixes):
            try:
                await message.delete()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
            try:
                await message.channel.send(
                    f"{message.author.mention}, команды бота разрешены только в канале <#{Config.COMMANDS_CHANNEL_ID}>!",
                    delete_after=7,
                )
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
            return

        # 2. Обработка файлов и картинок
        if message.attachments:
            # В Discord с 2024 года ссылки CDN требуют параметры ?ex=...&is=...&hm=... для аутентификации.
            # Отрезать параметры нельзя, иначе сервер Discord выдаст 403 Forbidden.
            clean_att = [a.url for a in message.attachments]
            att_links = " ".join(clean_att)
            raw_text = f"{raw_text} {att_links}".strip() if raw_text else att_links

        if not raw_text:
            return

        # Защита от рекламы сторонних Discord-инвайтов (официальный инвайт Ba5cMK7F6a разрешен)
        if ("discord.gg/" in raw_text.lower() or "discord.com/invite/" in raw_text.lower()) and "ba5cmk7f6a" not in raw_text.lower():
            try:
                await message.delete()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
            try:
                await message.channel.send(
                    f"{message.author.mention}, сторонние ссылки-приглашения запрещены в чате!",
                    delete_after=5,
                )
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
            return

        text = re.sub(r'(.)\1{4,}', r'\1\1\1', raw_text)
        text = re.sub(r'[\r\n]+', ' ', text).strip()
        max_len = 800 if ("http://" in text or "https://" in text) else 250
        if len(text) > max_len:
            text = text[:max_len - 3] + "..."

        if not text:
            return

        author_name = message.author.display_name

        # Дедупликация исходящих сообщений из Discord в Minecraft
        chat_out_key = f"{author_name}:{text}"
        now_ts = time.time()
        if (now_ts - self._recent_chat_out.get(chat_out_key, 0.0)) < 4.0:
            return
        self._recent_chat_out[chat_out_key] = now_ts
        if len(self._recent_chat_out) > 200:
            self._recent_chat_out = {k: v for k, v in self._recent_chat_out.items() if (now_ts - v) < 60.0}

        # Цензура мата при отправке в чат игры (формат: п*****с)
        censored_text = censor_profanity(text)

        payload = {
            "type": "discord_chat",
            "author": author_name,
            "content": censored_text,
        }
        await self.broadcast_packet(payload)

    # --- ОПОВЕЩЕНИЕ О СТРИМЕ ПРИ СМЕНЕ СТАТУСА DISCORD ---
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if not after.guild or after.bot:
            return

        is_streaming_now = any(isinstance(act, discord.Streaming) for act in after.activities)
        was_streaming = any(isinstance(act, discord.Streaming) for act in before.activities) if before else False

        if is_streaming_now and not was_streaming:
            has_media_role = any(r.name.lower() in ("стример", "медиа", "youtube", "twitch") for r in after.roles)
            if not has_media_role:
                return

            now = time.time()
            if (now - self.last_stream_alert.get(after.id, 0)) < 21600:
                return

            self.last_stream_alert[after.id] = now
            stream_act = next(act for act in after.activities if isinstance(act, discord.Streaming))

            events_ch = self.get_events_channel()
            if events_ch:
                embed = discord.Embed(
                    title=f"Стример {after.display_name} проводит трансляцию",
                    description=f"**{stream_act.name}**\n\n[Смотреть трансляцию]({stream_act.url})",
                    color=0x9146FF,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.set_footer(text="Vanilla Land • Медиа")
                await events_ch.send(embed=embed)

    # --- ОБНОВЛЕНИЕ ГОЛОСОВЫХ КАНАЛОВ И МОНИТОРИНГ ОФФЛАЙНА ---
    @tasks.loop(seconds=30)
    async def update_vc_loop(self):
        now = time.time()

        # 1. Очистка просроченных 2FA сессий из оперативной памяти
        expired_2fa = [p for p, data in list(self.pending_2fa.items()) if now > data.get("expires_at", 0)]
        for p in expired_2fa:
            data = self.pending_2fa.pop(p, None)
            if data and isinstance(data, dict):
                view = data.get("view")
                msg = data.get("message")
                if view and hasattr(view, "stop"):
                    view.stop()
                    for item in getattr(view, "children", []):
                        if hasattr(item, "disabled"):
                            item.disabled = True
                    if msg:
                        try:
                            self.create_tracked_task(msg.edit(content="⏳ Время ожидания подтверждения входа истекло (таймаут).", view=view))
                        except Exception:
                            pass

        # 1.1. Очистка in-memory кэшей от утечек памяти (LRU sweep)
        if len(self.cached_player_stats) > 300:
            stale_stats = [k for k, (t, _) in self.cached_player_stats.items() if now - t > 300.0]
            for k in stale_stats:
                self.cached_player_stats.pop(k, None)
            if len(self.cached_player_stats) > 300:
                for k in list(self.cached_player_stats.keys())[:100]:
                    self.cached_player_stats.pop(k, None)

        if len(self.last_stream_alert) > 200:
            stale_streams = [uid for uid, t in self.last_stream_alert.items() if now - t > 21600.0]
            for uid in stale_streams:
                self.last_stream_alert.pop(uid, None)

        if len(self._link_attempts) > 500:
            stale_link = [uid for uid, atts in self._link_attempts.items() if not atts or now - atts[-1] > self.link_window_sec]
            for uid in stale_link:
                self._link_attempts.pop(uid, None)

        if len(self._resend_attempts) > 500:
            stale_resend = [k for k, atts in self._resend_attempts.items() if not atts or now - atts[-1] > 600.0]
            for k in stale_resend:
                self._resend_attempts.pop(k, None)

        # 2. Очистка просроченных одноразовых кодов и сессий в SQLite раз в 5 минут
        if int(now) % 300 < 30:
            try:
                self.db.cleanup_expired_codes()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        # 3. Сброс онлайна и алерт при потере соединения с сервером (только после истечения grace period 45s)
        if self.was_connected and len(self.active_sockets) == 0:
            if (now - getattr(self, "last_disconnect_time", now)) > 45.0:
                if self.mc_online != 0:
                    self.mc_online = 0
                    self.mc_players = []
                    self.create_tracked_task(self.update_bot_presence())
                    self.pending_channel_update = True

            if (now - self.last_stats_time) > 45 and (now - self.last_offline_alert_time) > 600:
                self.last_offline_alert_time = now
                admin_ch = self.bot.get_channel(Config.ADMIN_LOG_CHANNEL_ID) or self.bot.get_channel(Config.LOG_CHANNEL_ID)
                if admin_ch and isinstance(admin_ch, discord.TextChannel):
                    embed = discord.Embed(
                        title="Потеряна связь с сервером Minecraft • Vanilla Land",
                        description="Сервер отключился от моста или не отвечает более 45 секунд.",
                        color=Colors.RED,
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text="Vanilla Land • Мониторинг")
                    try:
                        await admin_ch.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Не удалось отправить алерт отключения: {e}")

        if not self.pending_channel_update:
            return

        if (now - self.last_rename_time) < 300:
            return

        guild = None
        bridge_ch = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
        if bridge_ch:
            guild = bridge_ch.guild
        elif self.bot.guilds:
            guild = self.bot.guilds[0]

        if not guild:
            return

        online_name = f"Онлайн: {self.mc_online}/{self.mc_max}"
        tps_name = f"TPS: {self.mc_tps:.2f}"
        ip_name = f"IP: {Config.SERVER_IP}"

        updated_any = await self.cleanup_and_sync_stats_channels(guild, online_name, tps_name, ip_name)
        if updated_any:
            self.last_rename_time = now
            self.pending_channel_update = False

    def get_or_create_vc_id(self, setting_key: str, config_val: int) -> int:
        saved = self.db.get_setting(setting_key)
        if saved and saved.isdigit() and int(saved) != 0:
            return int(saved)
        return config_val

    async def cleanup_and_sync_stats_channels(
        self, guild: discord.Guild, online_name: str = "", tps_name: str = "", ip_name: str = ""
    ) -> bool:
        """Находит существующие каналы статистики (онлайн, TPS, IP), удаляет дубликаты и обновляет имена"""
        if not Config.BRIDGE_ENABLE_STATS_CHANNELS:
            return False
        if not guild or not guild.me.guild_permissions.manage_channels:
            return False

        # Не обновляем голосовые каналы в 0/300 в первые секунды после реконнекта, пока сокет только поднялся
        if len(self.active_sockets) > 0 and not self._socket_stats:
            return False

        online_vc_id = self.get_or_create_vc_id("online_vc_id", Config.ONLINE_VOICE_CHANNEL_ID)
        tps_vc_id = self.get_or_create_vc_id("tps_vc_id", Config.TPS_VOICE_CHANNEL_ID)
        ip_vc_id = self.get_or_create_vc_id("ip_vc_id", Config.IP_VOICE_CHANNEL_ID)

        # Сканируем все существующие голосовые каналы сервера
        found_online_vcs: list[discord.VoiceChannel] = []
        found_tps_vcs: list[discord.VoiceChannel] = []
        found_ip_vcs: list[discord.VoiceChannel] = []

        for ch in guild.voice_channels:
            low = ch.name.lower().strip()
            if low.startswith("онлайн") or low.startswith("online") or "онлайн:" in low or "online:" in low:
                found_online_vcs.append(ch)
            elif low.startswith("tps") or "tps:" in low or "tps -" in low:
                found_tps_vcs.append(ch)
            elif (
                low.startswith("ip")
                or low.startswith("айпи")
                or "ip:" in low
                or "ip -" in low
                or "ip •" in low
                or "ru-mc" in low
                or "vanillaland" in low
                or "play." in low
            ):
                found_ip_vcs.append(ch)

        updated_any = False

        # --- КАНАЛ ОНЛАЙНА ---
        target_online: Optional[discord.VoiceChannel] = None
        if online_vc_id:
            target_online = guild.get_channel(online_vc_id)

        # Если по ID канал не найден, берем первый из найденных на сервере
        if not target_online and found_online_vcs:
            target_online = found_online_vcs[0]
            self.db.set_setting("online_vc_id", str(target_online.id))

        # Удаляем ВСЕ лишние дубликаты каналов онлайна
        for dup in found_online_vcs:
            if target_online and dup.id != target_online.id:
                try:
                    await dup.delete(reason="Очистка старого дубликата канала онлайна")
                    logger.info(f"Удален лишний дубликат канала онлайна: {dup.name} ({dup.id})")
                except Exception as e:
                    logger.warning(f"Не удалось удалить дубликат онлайна {dup.id}: {e}")

        # Категория для новых каналов (берем от существующего или из Config)
        stats_category: Optional[discord.CategoryChannel] = None
        if target_online and isinstance(target_online.category, discord.CategoryChannel):
            stats_category = target_online.category
        elif Config.STATS_VOICE_CATEGORY_ID:
            cat = guild.get_channel(Config.STATS_VOICE_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                stats_category = cat

        # Если канала онлайна вообще нет — создаем единственный
        if not target_online:
            initial_name = online_name or f"Онлайн: {self.mc_online}/{self.mc_max}"
            target_online = await self.create_stats_channel(guild, initial_name, category=stats_category)
            if target_online:
                self.db.set_setting("online_vc_id", str(target_online.id))
                if target_online.category:
                    stats_category = target_online.category
                updated_any = True
        elif online_name and target_online.name != online_name:
            try:
                await target_online.edit(name=online_name)
                updated_any = True
            except discord.HTTPException as e:
                logger.warning(f"Ошибка переименования канала онлайна: {e}")

        # --- КАНАЛ TPS ---
        target_tps: Optional[discord.VoiceChannel] = None
        if tps_vc_id:
            target_tps = guild.get_channel(tps_vc_id)

        # Если по ID канал не найден, берем первый из найденных на сервере
        if not target_tps and found_tps_vcs:
            target_tps = found_tps_vcs[0]
            self.db.set_setting("tps_vc_id", str(target_tps.id))

        # Удаляем ВСЕ лишние дубликаты каналов TPS
        for dup in found_tps_vcs:
            if target_tps and dup.id != target_tps.id:
                try:
                    await dup.delete(reason="Очистка старого дубликата канала TPS")
                    logger.info(f"Удален лишний дубликат канала TPS: {dup.name} ({dup.id})")
                except Exception as e:
                    logger.warning(f"Не удалось удалить дубликат TPS {dup.id}: {e}")

        if not stats_category:
            if target_tps and isinstance(target_tps.category, discord.CategoryChannel):
                stats_category = target_tps.category
            elif Config.STATS_VOICE_CATEGORY_ID:
                cat = guild.get_channel(Config.STATS_VOICE_CATEGORY_ID)
                if isinstance(cat, discord.CategoryChannel):
                    stats_category = cat

        # Если канала TPS вообще нет — создаем единственный
        if not target_tps:
            initial_name = tps_name or f"TPS: {self.mc_tps:.2f}"
            target_tps = await self.create_stats_channel(guild, initial_name, category=stats_category)
            if target_tps:
                self.db.set_setting("tps_vc_id", str(target_tps.id))
                if target_tps.category:
                    stats_category = target_tps.category
                updated_any = True
        elif tps_name and target_tps.name != tps_name:
            try:
                await target_tps.edit(name=tps_name)
                updated_any = True
            except discord.HTTPException as e:
                logger.warning(f"Ошибка переименования канала TPS: {e}")

        # --- КАНАЛ IP СЕРВЕРА ---
        target_ip: Optional[discord.VoiceChannel] = None
        if ip_vc_id:
            target_ip = guild.get_channel(ip_vc_id)

        # Если по ID канал не найден, берем первый из найденных на сервере
        if not target_ip and found_ip_vcs:
            target_ip = found_ip_vcs[0]
            self.db.set_setting("ip_vc_id", str(target_ip.id))

        # Удаляем ВСЕ лишние дубликаты каналов IP
        for dup in found_ip_vcs:
            if target_ip and dup.id != target_ip.id:
                try:
                    await dup.delete(reason="Очистка старого дубликата канала IP")
                    logger.info(f"Удален лишний дубликат канала IP: {dup.name} ({dup.id})")
                except Exception as e:
                    logger.warning(f"Не удалось удалить дубликат IP {dup.id}: {e}")

        expected_ip_name = ip_name or f"IP: {Config.SERVER_IP}"
        # Если канала IP вообще нет — создаем единственный в той же категории
        if not target_ip:
            target_ip = await self.create_stats_channel(guild, expected_ip_name, category=stats_category)
            if target_ip:
                self.db.set_setting("ip_vc_id", str(target_ip.id))
                updated_any = True
        elif expected_ip_name and target_ip.name != expected_ip_name:
            try:
                await target_ip.edit(name=expected_ip_name)
                updated_any = True
            except discord.HTTPException as e:
                logger.warning(f"Ошибка переименования канала IP: {e}")

        return updated_any

    async def create_stats_channel(
        self, guild: discord.Guild, name: str, category: Optional[discord.CategoryChannel] = None
    ) -> Optional[discord.VoiceChannel]:
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=False, speak=False)
            }
            if not category and Config.STATS_CATEGORY_ID:
                cat = guild.get_channel(Config.STATS_CATEGORY_ID)
                if isinstance(cat, discord.CategoryChannel):
                    category = cat

            return await guild.create_voice_channel(
                name=name,
                category=category,
                overwrites=overwrites,
                reason="Авто-создание канала статистики сервера",
            )
        except Exception as e:
            logger.error(f"Не удалось создать канал статистики '{name}': {e}")
            return None

    @update_vc_loop.before_loop
    async def before_update_vc_loop(self):
        await self.bot.wait_until_ready()
        # Сразу при старте бота сканируем сервер и очищаем все накопившиеся дубликаты каналов
        for g in self.bot.guilds:
            try:
                await self.cleanup_and_sync_stats_channels(g)
            except Exception as e:
                logger.warning(f"Ошибка при первичной очистке каналов статистики в {g.name}: {e}")

    # --- КОМАНДА /online ДЛЯ ИГРОКОВ (ГИБРИДНАЯ: СЛЭШ + ПРЕФИКС) ---
    @commands.hybrid_command(
        name="online",
        aliases=["онлайн", "players", "игроки"],
        description="Показать текущий онлайн и список игроков на сервере Minecraft",
    )
    async def online_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        embed = self._create_online_embed()
        await ctx.send(embed=embed)

    def _create_online_embed(self) -> discord.Embed:
        connected = len(self.active_sockets) > 0
        if not connected:
            embed = discord.Embed(
                title="Сервер Minecraft оффлайн",
                description="Сервер сейчас недоступен или перезагружается. Попробуйте чуть позже.",
                color=Colors.RED,
            )
            embed.set_footer(text=f"Vanilla Land • {Config.SERVER_IP}")
            return embed

        if connected and not self._socket_stats and getattr(self, "mc_online", 0) == 0:
            embed = discord.Embed(
                title="Синхронизация с сервером Minecraft...",
                description="Сервер подключился к мосту, идёт загрузка данных игроков. Попробуйте через пару секунд.",
                color=Colors.BLUE,
            )
            embed.add_field(name="IP", value=f"`{Config.SERVER_IP}`", inline=True)
            embed.set_footer(text="Vanilla Land")
            return embed

        if self.mc_online == 0:
            embed = discord.Embed(
                title=f"👥 Игроки онлайн: 0 / {self.mc_max}",
                description="Сейчас на сервере никого нет. Будьте первыми!",
                color=Colors.BLUE,
            )
            embed.add_field(name="TPS", value=f"{self.mc_tps:.2f}", inline=True)
            embed.add_field(name="IP", value=f"`{Config.SERVER_IP}`", inline=True)
            embed.set_footer(text="Vanilla Land")
            return embed

        players_formatted = [f"• `{p}`" for p in self.mc_players]
        players_text = "\n".join(players_formatted) if players_formatted else "Игроки загружаются..."

        embed = discord.Embed(
            title=f"👥 Игроки онлайн: {self.mc_online} / {self.mc_max}",
            description=f"**Список игроков на сервере:**\n{players_text}",
            color=Colors.GREEN,
        )
        embed.add_field(name="TPS", value=f"`{self.mc_tps:.2f}`", inline=True)
        embed.add_field(name="IP", value=f"`{Config.SERVER_IP}`", inline=True)
        if self.mc_players:
            first_player = self.mc_players[0]
            embed.set_thumbnail(url=get_skin_avatar_url(first_player, None, self.db))
        embed.set_footer(text="Vanilla Land")
        return embed


    # --- КОМАНДА /deaths (ПРЕМИЯ ДАРВИНА) ---
    @commands.hybrid_command(
        name="deaths",
        aliases=["смерти", "дарвин", "премия_дарвина"],
        description="Топ самых частых смертей на сервере (Премия Дарвина)",
    )
    async def deaths_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()

        top_list = self.db.get_top_deaths(10)
        if not top_list:
            embed = discord.Embed(
                title="🏆 Премия Дарвина • Vanilla Land",
                description="После вайпа от 22 ноября на сервере пока никто не умирал! Все аккуратны и бдительны.",
                color=Colors.BLUE,
            )
            embed.set_footer(text="Vanilla Land • Вайп от 22 ноября 2026")
            return await ctx.send(embed=embed)

        medals = ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8", "#9", "#10"]
        lines = []
        for i, (name, count, last_reason) in enumerate(top_list):
            m = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"{m} **{name}** — `{count}` смертей *(посл: {last_reason})*")

        embed = discord.Embed(
            title="🏆 Премия Дарвина • Топ смертей Vanilla Land",
            description=f"**Сезон:** Вайп от 22 ноября\n\n" + "\n".join(lines),
            color=0xFEE75C,
            timestamp=datetime.now(timezone.utc),
        )
        if top_list:
            top_player = top_list[0][0]
            embed.set_thumbnail(url=get_skin_avatar_url(top_player, None, self.db))
        embed.set_footer(text="Vanilla Land • Вайп от 22 ноября 2026")
        await ctx.send(embed=embed)



    # --- КОМАНДА /msg_mc (ЛИЧНЫЕ СООБЩЕНИЯ В ИГРУ С УДАЛЕНИЕМ ИЗ ЧАТА И ЛС В БОТЕ) ---
    @commands.hybrid_command(
        name="msg_mc",
        aliases=["лс_мк", "msgmc", "tell_mc", "дм_мк"],
        description="Отправить приватное сообщение игроку на сервер Minecraft",
    )
    @app_commands.describe(player="Никнейм игрока на сервере", text="Текст личного сообщения")
    async def msg_mc_cmd(self, ctx: commands.Context, player: str, *, text: str):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        # 1. Скрываем текст в общем чате — сразу удаляем команду
        if ctx.message:
            try:
                await ctx.message.delete()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        clean_player = player.strip()
        is_online = any(p.lower() == clean_player.lower() for p in self.mc_players)
        if not is_online:
            err_msg = f"Игрок **{clean_player}** сейчас не на сервере."
            if ctx.interaction:
                return await ctx.send(err_msg, ephemeral=True)
            try:
                return await ctx.author.send(err_msg)
            except discord.Forbidden:
                return await ctx.send(f"{ctx.author.mention}, {err_msg}", delete_after=5)

        # 2. Отправка пакета на сервер Minecraft
        payload = {
            "type": "dm",
            "target": clean_player,
            "author": ctx.author.display_name,
            "author_id": str(ctx.author.id),
            "content": text.strip(),
        }
        await self.broadcast_packet(payload)

        # 3. Отправка подтверждения пользователю в ЛС с кнопкой диалога
        embed = discord.Embed(
            title=f"✉️ Личное сообщение доставлено игроку {clean_player}",
            description=f"Текст: *{text.strip()}*",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • Ответ придет вам прямо сюда")
        view = DmReplyView(self, clean_player)

        if ctx.interaction:
            await ctx.send(f"✉️ Личное сообщение отправлено игроку **{clean_player}** в Minecraft! Проверьте ЛС от бота.", ephemeral=True)

        try:
            dm_msg = await ctx.author.send(embed=embed, view=view)
            self.db.save_dm_reply_target(dm_msg.id, clean_player)
        except discord.Forbidden:
            if not ctx.interaction and ctx.channel:
                await ctx.channel.send(
                    f"{ctx.author.mention}, у вас закрыты личные сообщения, бот не может присылать ответы в ЛС!",
                    delete_after=7,
                )


    # --- КОМАНДА /time ИЛИ !time (ИГРОВОЕ ВРЕМЯ И ПОГОДА) ---
    @commands.hybrid_command(
        name="time",
        aliases=["время", "daytime", "mc_time"],
        description="Показать текущее игровое время и погоду на сервере Minecraft",
    )
    async def time_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()

        if not self.active_sockets:
            embed = discord.Embed(
                title="Сервер оффлайн",
                description="Сервер Minecraft сейчас не подключен к мосту.",
                color=Colors.RED,
            )
            return await ctx.send(embed=embed)

        data = await self.query_minecraft({"type": "query_world"}, timeout=3.5)
        if not data:
            embed = discord.Embed(
                title="Ошибка запроса",
                description="Сервер не ответил вовремя. Попробуйте ещё раз через несколько секунд.",
                color=Colors.YELLOW,
            )
            return await ctx.send(embed=embed)

        ticks = int(data.get("time", 0))
        day = int(data.get("day", 0))
        weather = data.get("weather", "clear")

        hours = ((ticks + 6000) % 24000) // 1000
        minutes = int(((ticks + 6000) % 1000) * 60 / 1000)
        time_str = f"{hours:02d}:{minutes:02d}"

        if 0 <= ticks < 1000:
            phase = "🌅 Рассвет"
            color = 0xF39C12
        elif 1000 <= ticks < 6000:
            phase = "☀️ Утро"
            color = 0xF1C40F
        elif 6000 <= ticks < 12000:
            phase = "☀️ День (Полдень)"
            color = 0xFEE75C
        elif 12000 <= ticks < 13800:
            phase = "🌇 Закат"
            color = 0xE67E22
        elif 13800 <= ticks < 18000:
            phase = "🌙 Ночь (Монстры активны)"
            color = 0x5865F2
        elif 18000 <= ticks < 22000:
            phase = "🌑 Глубокая полночь"
            color = 0x2C3E50
        else:
            phase = "🌌 Предрассветные сумерки"
            color = 0x34495E

        weather_map = {
            "clear": "☀️ Ясно",
            "rain": "🌧️ Дождь",
            "thunder": "⛈️ Гроза",
        }
        weather_str = weather_map.get(weather, "☀️ Ясно")

        embed = discord.Embed(
            title="Игровое время • Vanilla Land",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Время в игре", value=f"`{time_str}` ({phase})", inline=True)
        embed.add_field(name="📅 День мира", value=f"`День #{day}`", inline=True)
        embed.add_field(name="🌤️ Погода", value=weather_str, inline=True)
        embed.add_field(name="TPS", value=f"`{self.mc_tps:.2f}`", inline=True)
        embed.add_field(name="👥 Онлайн", value=f"`{self.mc_online} / {self.mc_max}`", inline=True)
        embed.set_footer(text="Vanilla Land • Мир")
        await ctx.send(embed=embed)

    # --- КОМАНДА /world ИЛИ !world (КРАСИВОЕ СОСТОЯНИЕ МИРА И ФАЗА ЛУНЫ) ---
    @commands.hybrid_command(
        name="world",
        aliases=["мир", "мир_инфо", "worldinfo", "mc_world"],
        description="Подробное состояние мира: день, время, погода, фаза луны и TPS",
    )
    async def world_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()

        if not self.active_sockets:
            embed = discord.Embed(
                title="Сервер оффлайн",
                description="Сервер Minecraft сейчас не подключен к мосту.",
                color=Colors.RED,
            )
            return await ctx.send(embed=embed)

        data = await self.query_minecraft({"type": "query_world"}, timeout=5.0)
        if not data and hasattr(self, "last_world_data") and self.last_world_data:
            data = self.last_world_data
        elif data:
            self.last_world_data = data

        if not data:
            embed = discord.Embed(
                title="Данные мира недоступны",
                description="Сервер сейчас не предоставил информацию о мире. Попробуйте через пару секунд.",
                color=Colors.YELLOW,
            )
            return await ctx.send(embed=embed)

        ticks = int(data.get("time", 0)) % 24000
        day = int(data.get("day", 0))
        weather = data.get("weather", "clear")
        moon_phase = int(data.get("moon_phase", 0)) % 8

        hours = ((ticks + 6000) % 24000) // 1000
        minutes = int(((ticks + 6000) % 1000) * 60 / 1000)
        time_24h = f"{hours:02d}:{minutes:02d}"

        # Прогресс текущих суток (24000 тиков)
        day_pct = int((ticks / 24000.0) * 100)
        blocks = 10
        filled = min(blocks, int((day_pct / 100) * blocks))
        time_bar = "█" * filled + "░" * (blocks - filled)

        # Фазы суток
        if 0 <= ticks < 1000:
            phase_title = "🌅 Рассвет"
            phase_desc = "Восход солнца, монстры начинают гореть"
            phase_color = 0xF39C12
            can_sleep = False
            mobs_danger = "Безопасно (Монстры сгорают на солнце)"
        elif 1000 <= ticks < 6000:
            phase_title = "☀️ Утро"
            phase_desc = "Яркое утреннее солнце"
            phase_color = 0xF1C40F
            can_sleep = False
            mobs_danger = "Безопасно (Светлое время суток)"
        elif 6000 <= ticks < 12000:
            phase_title = "☀️ Полдень"
            phase_desc = "Солнце в зените, максимальная освещённость"
            phase_color = 0xFEE75C
            can_sleep = False
            mobs_danger = "Безопасно (Светлое время суток)"
        elif 12000 <= ticks < 13000:
            phase_title = "🌇 Закат"
            phase_desc = "Солнце садится, вечерние сумерки"
            phase_color = 0xE67E22
            can_sleep = False
            mobs_danger = "Внимание (Скоро начнётся спавн мобов)"
        elif 13000 <= ticks < 18000:
            phase_title = "🌙 Ночь"
            phase_desc = "Враждебные мобы активны, можно ложиться спать"
            phase_color = 0x5865F2
            can_sleep = True
            mobs_danger = "Опасно (Монстры бродят по поверхности)"
        elif 18000 <= ticks < 22000:
            phase_title = "🌑 Глубокая полночь"
            phase_desc = "Пик темноты, максимальная активность монстров"
            phase_color = 0x2C3E50
            can_sleep = True
            mobs_danger = "Опасно (Монстры бродят по поверхности)"
        else:
            phase_title = "🌌 Предрассветные сумерки"
            phase_desc = "Скоро рассвет, ночь подходит к концу"
            phase_color = 0x34495E
            can_sleep = True
            mobs_danger = "Опасно (Монстры ещё активны)"

        moon_info = {
            0: ("🌕 Полнолуние", "Максимальный спавн слизней в болотах (100%)"),
            1: ("🌖 Убывающая луна", "Высокий спавн слизней в болотах (66%)"),
            2: ("🌗 Последняя четверть", "Умеренный спавн слизней в болотах (33%)"),
            3: ("🌘 Старая луна", "Минимальный спавн слизней в болотах (10%)"),
            4: ("🌑 Новолуние", "Слизни в болотах не спавнятся (0%)"),
            5: ("🌒 Молодая луна", "Минимальный спавн слизней в болотах (10%)"),
            6: ("🌓 Первая четверть", "Умеренный спавн слизней в болотах (33%)"),
            7: ("🌔 Прибывающая луна", "Высокий спавн слизней в болотах (66%)"),
        }
        moon_title, moon_desc = moon_info.get(moon_phase, ("🌕 Луна", ""))

        weather_info = {
            "clear": ("☀️ Ясно", "Отличная солнечная видимость", 0),
            "rain": ("🌧️ Дождь", "Небо затянуто тучами, ускорена рыбалка", 1),
            "thunder": ("⛈️ Грозовая буря", "Опасно! Молнии, монстры спавнятся днём", 2),
        }
        w_title, w_desc, w_level = weather_info.get(weather, ("☀️ Ясно", "Солнечно", 0))
        if w_level == 2:
            phase_color = 0x9B59B6
            mobs_danger = "⛈️ Гроза! Монстры бродят даже днём!"
            can_sleep = True

        sleep_status = "🛌 Можно спать в кровати" if can_sleep else "⏳ Спать пока нельзя (день)"

        embed = discord.Embed(
            title=f"🌍 Мир Vanilla Land • День #{day:,}",
            color=phase_color,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Игровое время",
            value=f"`[{time_bar}]` **{time_24h}** *(тик {ticks:,} / 24,000)*\n**{phase_title}** — {phase_desc}",
            inline=False,
        )

        embed.add_field(
            name="🌤️ Погода",
            value=f"**{w_title}**\n*{w_desc}*",
            inline=True,
        )

        embed.add_field(
            name="🌙 Фаза луны",
            value=f"**{moon_title}**\n*{moon_desc}*",
            inline=True,
        )

        embed.add_field(
            name="Окружающая среда",
            value=f"• Поверхность: {mobs_danger}\n• Сон: {sleep_status}\n• TPS: `{self.mc_tps:.2f}` | Игроков: `{self.mc_online} / {self.mc_max}`",
            inline=False,
        )

        embed.set_footer(text=f"Vanilla Land • IP: {Config.SERVER_IP}")
        await ctx.send(embed=embed)

    # --- КОМАНДА /tps ИЛИ !tps (МОНИТОРИНГ НАГРУЗКИ) ---
    @commands.hybrid_command(
        name="tps",
        aliases=["тпс", "нагрузка", "мспт", "производительность", "mspt", "performance", "сервер_нагрузка"],
        description="Подробные показатели нагрузки сервера: TPS, MSPT, ОЗУ",
    )
    async def tps_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()

        connected = len(self.active_sockets) > 0
        if not connected:
            embed = discord.Embed(
                title="Сервер оффлайн",
                description="Сервер Minecraft сейчас недоступен или мост отключен.",
                color=Colors.RED,
            )
            return await ctx.send(embed=embed)

        tps = self.mc_tps
        mspt = self.mc_mspt
        used_mb = self.mc_mem_used
        max_mb = max(1, self.mc_mem_max)
        free_mb = max(0, max_mb - used_mb)
        ram_pct = min(100, int((used_mb / max_mb) * 100)) if max_mb > 0 else 0

        # Полоса для TPS (20 = 100%)
        tps_pct = min(100, int((tps / 20.0) * 100))
        tps_blocks = 10
        tps_filled = min(tps_blocks, int((tps_pct / 100) * tps_blocks))
        tps_bar = "█" * tps_filled + "░" * (tps_blocks - tps_filled)

        # Полоса для MSPT (бюджет 50 ms)
        mspt_pct = min(100, int((mspt / 50.0) * 100))
        mspt_blocks = 10
        mspt_filled = min(mspt_blocks, int((mspt_pct / 100) * mspt_blocks))
        mspt_bar = "█" * mspt_filled + "░" * (mspt_blocks - mspt_filled)

        # Полоса для RAM
        ram_blocks = 10
        ram_filled = min(ram_blocks, int((ram_pct / 100) * ram_blocks))
        ram_bar = "█" * ram_filled + "░" * (ram_blocks - ram_filled)

        if tps >= 19.8:
            tps_status = "Идеально (Стабильные 20 TPS, 100% тикрейт)"
            embed_color = Colors.GREEN
            health_badge = "Отличное (100% стабильность)"
        elif tps >= 18.0:
            tps_status = "Хорошо (Минимальные колебания)"
            embed_color = Colors.GREEN
            health_badge = "Стабильное (Без задержек)"
        elif tps >= 15.0:
            tps_status = "🟡 Умеренная нагрузка (Возможны микрофризы)"
            embed_color = Colors.YELLOW
            health_badge = "🟡 Повышенная нагрузка"
        else:
            tps_status = "Просадка тиков (Ощутимые лаги)"
            embed_color = Colors.RED
            health_badge = "Критическая перегрузка"

        embed = discord.Embed(
            title="Производительность сервера • Vanilla Land",
            color=embed_color,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Тикрейт (TPS)",
            value=f"`[{tps_bar}]` **{tps:.2f} / 20.00**\n{tps_status}",
            inline=False,
        )

        embed.add_field(
            name="Время тика (MSPT)",
            value=f"`[{mspt_bar}]` **{mspt:.1f} ms** / 50.0 ms\n*Нагрузка на такт: {mspt_pct}% от лимита*",
            inline=True,
        )

        embed.add_field(
            name="👥 Игроки онлайн",
            value=f"**{self.mc_online}** из **{self.mc_max}** игроков\n*Свободных слотов: {max(0, self.mc_max - self.mc_online)}*",
            inline=True,
        )

        if max_mb > 1:
            used_gb = used_mb / 1024.0
            max_gb = max_mb / 1024.0
            free_mb / 1024.0
            embed.add_field(
                name="💾 Память JVM (RAM)",
                value=(
                    f"`[{ram_bar}]` **{ram_pct}%**\n"
                    f"Использовано: `{used_mb:,} МБ` ({used_gb:.1f} ГБ)\n"
                    f"Выделено всего: `{max_mb:,} МБ` ({max_gb:.1f} ГБ) | Свободно: `{free_mb:,} МБ`"
                ),
                inline=False,
            )

        embed.add_field(
            name="Состояние сервера",
            value=f"• Статус: {health_badge}\n• Ядро: `Paper 26.3 (Java 21)`\n• Подключение: `{Config.SERVER_IP}`",
            inline=False,
        )

        embed.set_footer(text="Vanilla Land • Диагностика производительности")
        await ctx.send(embed=embed)

    # --- КОМАНДА /skin ИЛИ !skin <ник> ---
    @commands.hybrid_command(
        name="skin",
        aliases=["скин", "кожа", "модель", "mc_skin", "playerskin"],
        description="Посмотреть 3D модель и скачать скин любого игрока",
    )
    @app_commands.describe(player_name="Никнейм игрока в Minecraft")
    async def skin_cmd(self, ctx: commands.Context, player_name: str):
        if ctx.interaction:
            await ctx.defer()

        clean_name = player_name.strip()
        skin_hash = self.db.get_player_skin(clean_name)
        avatar_url = get_skin_avatar_url(clean_name, skin_hash, self.db)
        body_url = get_skin_body_url(clean_name, skin_hash, self.db)
        download_url = f"https://mc-heads.net/skin/{skin_hash}" if skin_hash else f"https://mc-heads.net/skin/{clean_name}"

        embed = discord.Embed(
            title=f"🎭 Скин игрока • {clean_name}",
            description=f"Никнейм: `{clean_name}`\n[Скачать файл скина (.png)]({download_url})",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=avatar_url)
        embed.set_image(url=body_url)
        embed.set_footer(text="Vanilla Land • 3D Моделирование скинов")

        view = ui.View()
        view.add_item(ui.Button(label="Скачать файл скина (.png)", url=download_url, style=discord.ButtonStyle.link))
        await ctx.send(embed=embed, view=view)

    # --- КОМАНДА /alts ИЛИ !alts (ТВИНКИ И МУЛЬТИАККАУНТЫ) ---
    @commands.hybrid_command(
        name="alts",
        aliases=["альты", "твинки", "мультиаккаунты", "мульты", "alt"],
        description="Поиск мультиаккаунтов и твинков игрока по IP адресам",
    )
    @app_commands.describe(target="Никнейм игрока или IP адрес (например: !alts Steve или !alts 194.x.x.x)")
    async def alts_cmd(self, ctx: commands.Context, *, target: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администрации и модерации.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer()

        clean_target = target.strip()

        # Проверка, не введён ли IP адрес
        is_ip_search = False
        parts = clean_target.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            is_ip_search = True
        elif clean_target.lower().startswith("ip "):
            is_ip_search = True
            clean_target = clean_target[3:].strip()

        if is_ip_search:
            alts_on_ip = self.db.get_alts_by_ip(clean_target)
            if not alts_on_ip:
                embed = discord.Embed(
                    title=f"Поиск по IP: {clean_target}",
                    description="С этого IP адреса не зафиксировано входов.",
                    color=Colors.DARK,
                )
                return await ctx.send(embed=embed)

            # Баны отключены
            banned_map = {}

            has_banned_on_ip = len(banned_map) > 0
            lines = []
            for i, a in enumerate(alts_on_ip, 1):
                p_name = a["player_name"]
                is_on = any(p.lower() == p_name.lower() for p in self.mc_players)
                b_info = banned_map.get(p_name.lower())
                if b_info:
                    status_tag = "`[Забанен]`"
                    ban_text = f" — «{b_info.get('reason', 'Бан')}» ({b_info.get('duration', 'Навсегда')})"
                elif is_on:
                    status_tag = "`[Онлайн]`"
                    ban_text = ""
                else:
                    status_tag = "`[Оффлайн]`"
                    ban_text = ""
                lines.append(f"**{i}.** `{p_name}` {status_tag}{ban_text} — *{a['last_seen']}*")

            desc = f"Найдено аккаунтов: **{len(alts_on_ip)}**\n\n"
            if has_banned_on_ip:
                desc += "Найдено совпадение с заблокированным аккаунтом (возможен обход бана).\n\n"
            desc += "\n".join(lines[:25])

            embed = discord.Embed(
                title=f"Аккаунты на IP: `{clean_target}`",
                description=desc,
                color=Colors.RED if has_banned_on_ip else (Colors.YELLOW if len(alts_on_ip) > 1 else Colors.GREEN),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Vanilla Land • Модерация")
            return await ctx.send(embed=embed)

        # Поиск по имени игрока
        data = self.db.get_player_alts(clean_target)
        known_ips = data["ips"]
        alts = data["alts"]

        avatar_url = get_skin_avatar_url(clean_target, None, self.db)

        if not known_ips:
            embed = discord.Embed(
                title=f"Твинки • {clean_target}",
                description=f"Для игрока **{clean_target}** пока нет сохранённых IP-адресов в базе.",
                color=Colors.DARK,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=avatar_url)
            embed.set_footer(text="Vanilla Land • Модерация")
            return await ctx.send(embed=embed)

        # Баны отключены
        banned_map = {}

        target_banned = clean_target.lower() in banned_map
        has_banned_alts = any(k != clean_target.lower() for k in banned_map.keys())

        embed = discord.Embed(
            title=f"Твинки игрока • {clean_target}",
            color=Colors.RED if (target_banned or has_banned_alts) else (Colors.YELLOW if alts else Colors.GREEN),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=avatar_url)

        if target_banned:
            b_info = banned_map[clean_target.lower()]
            embed.description = (
                f"**Основной аккаунт забанен в LiteBans:**\n"
                f"• Причина: «{b_info.get('reason', 'Нарушение правил')}»\n"
                f"• Срок: `{b_info.get('duration', 'Навсегда')}`\n"
            )
        elif has_banned_alts:
            banned_alt_nicks = [banned_map[k].get("player", k) for k in banned_map if k != clean_target.lower()]
            embed.description = f"**Обнаружен забаненный аккаунт на IP:** {', '.join(banned_alt_nicks)}\n"

        # Список известных IP
        masked_ips = []
        for ip_addr in known_ips[:5]:
            masked_ips.append(f"`{ip_addr}`")
        if len(known_ips) > 5:
            masked_ips.append(f"*+ ещё {len(known_ips) - 5}*")
        embed.add_field(
            name=f"Известные IP ({len(known_ips)})",
            value=", ".join(masked_ips) if masked_ips else "нет данных",
            inline=False,
        )

        if not alts:
            embed.add_field(
                name="Результат",
                value="Твинков не обнаружено.",
                inline=False,
            )
        else:
            alt_lines = []
            for i, alt in enumerate(alts[:15], 1):
                alt_name = alt["player_name"]
                is_on = any(p.lower() == alt_name.lower() for p in self.mc_players)
                on_tag = "[В сети]" if is_on else "[Не в сети]"
                shared_str = ", ".join(f"`{ip}`" for ip in alt["shared_ips"][:2])
                if len(alt["shared_ips"]) > 2:
                    shared_str += f" *(+{len(alt['shared_ips']) - 2})*"

                alt_ban = banned_map.get(alt_name.lower())
                ban_badge = f"\n   ↳ LiteBans: «{alt_ban.get('reason', 'Бан')}» ({alt_ban.get('duration', 'Навсегда')})" if alt_ban else ""

                alt_lines.append(
                    f"**{i}.** `{alt_name}` {on_tag}{ban_badge}\n"
                    f"   ↳ Общий IP: {shared_str} • Вход: *{alt['last_seen']}*"
                )

            embed.add_field(
                name=f"Мультиаккаунты ({len(alts)})",
                value="\n".join(alt_lines),
                inline=False,
            )

        embed.set_footer(text="Vanilla Land • Модерация")
        await ctx.send(embed=embed)

    # --- КОМАНДА /top ИЛИ !top (РЕКОРДЫ И ЛИДЕРЫ СЕРВЕРА) ---
    @commands.hybrid_command(
        name="top",
        aliases=["топ", "лидеры", "рекорды", "leaderboard", "статистика_сервера"],
        description="Таблица лидеров сервера: наигранное время, алмазы, незерит, PvP и смерти",
    )
    @app_commands.describe(category="Категория: playtime, diamonds, debris, kills, deaths (или пусто для общего топа)")
    async def top_cmd(self, ctx: commands.Context, category: Optional[str] = None):
        if ctx.interaction:
            await ctx.defer()

        data = None
        if self.active_sockets:
            data = await self.query_minecraft({"type": "query_top"}, timeout=9.0)

        if not data and self.last_top_data:
            data = self.last_top_data

        if not data:
            if not self.active_sockets:
                embed = discord.Embed(
                    title="Сервер оффлайн",
                    description="Сервер Minecraft сейчас не подключен к мосту.",
                    color=Colors.RED,
                )
            else:
                embed = discord.Embed(
                    title="⏳ Обновление статистики",
                    description="Сервер сейчас подготавливает свежие данные лидерборда. Попробуйте через пару секунд.",
                    color=Colors.YELLOW,
                )
            return await ctx.send(embed=embed)

        self.last_top_data = data
        view = TopLeaderboardView(data, category)
        embed = view.build_embed()
        await ctx.send(embed=embed, view=view)

    # --- КОМАНДА /top_reset (СБРОС ТОПА И СМЕРТЕЙ ПОСЛЕ ВАЙПА) ---
    @commands.hybrid_command(
        name="top_reset",
        aliases=["сброс_топа", "вайп_топ"],
        description="[Админ] Сбросить кэш топа и статистику смертей после вайпа",
    )
    @commands.has_permissions(administrator=True)
    async def top_reset_cmd(self, ctx: commands.Context):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администраторам.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        self.last_top_data = None
        self.db.reset_top_deaths()
        await self.broadcast_packet({"type": "reset_top_cache"})
        await ctx.send("✅ Статистика топа и смертей успешно сброшена! Новый отсчёт ведётся с вайпа от 22 ноября.", ephemeral=True)

    # --- КОМАНДА /profile ИЛИ !profile [ник] (КАРТОЧКА ИГРОКА) ---
    @commands.hybrid_command(
        name="profile",
        aliases=["профиль", "стата", "статистика", "игрок", "player"],
        description="Карточка профиля игрока Minecraft: скин, время игры, добыча, PvP и смерти",
    )
    @app_commands.describe(player_name="Ник игрока (если не указан — используется ваш привязанный аккаунт)")
    async def profile_cmd(self, ctx: commands.Context, player_name: Optional[str] = None):
        if ctx.interaction:
            await ctx.defer()

        if player_name:
            clean_name = player_name.strip()
        else:
            # Сначала проверяем, привязан ли аккаунт у автора команды
            linked_author = self.db.get_linked_account_by_discord(ctx.author.id)
            if linked_author and linked_author.get("player_name"):
                clean_name = linked_author["player_name"]
            else:
                clean_name = ctx.author.display_name.strip()

        data = None
        if self.active_sockets:
            data = await self.query_minecraft({"type": "query_player", "player": clean_name}, timeout=5.0)

        # Если плагин вернул found: false (игрока нет в статистике сервера)
        if data and not data.get("found", True) and not data.get("online", False):
            data = None

        # Проверяем кэш статов игрока
        now_ts = time.time()
        cache_key = clean_name.lower()
        if not data and cache_key in self.cached_player_stats:
            cached_time, cached_data = self.cached_player_stats[cache_key]
            if (now_ts - cached_time) < 180.0:
                data = cached_data

        if data:
            self.cached_player_stats[cache_key] = (now_ts, data)

        # Если данных из игры вообще нет или игрок никогда не заходил
        if not data:
            death_count, last_death = self.db.get_player_deaths(clean_name)
            death_coords = self.db.get_death_coords(clean_name)
            avatar_url = get_skin_avatar_url(clean_name, None, self.db)
            linked_acc = self.db.get_linked_account_by_mc(clean_name)

            desc = (
                "*Игрок сейчас оффлайн. Показаны данные из базы сервера.*"
                if self.active_sockets
                else "*Сервер Minecraft сейчас недоступен. Показаны сохранённые данные моста.*"
            )
            embed = discord.Embed(
                title=f"Профиль игрока • {clean_name}",
                description=desc,
                color=Colors.DARK,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=avatar_url)
            if linked_acc:
                embed.add_field(name="🔗 Discord", value=f"<@{linked_acc['discord_user_id']}>", inline=True)
            embed.add_field(name="Статус", value="Не на сервере", inline=True)
            embed.add_field(name="💀 Смертей в базе", value=f"`{death_count}` (Посл: {last_death})", inline=True)
            if death_coords:
                embed.add_field(
                    name="Координаты гибели",
                    value=f"`{death_coords['world']}` [X: `{death_coords['x']}`, Y: `{death_coords['y']}`, Z: `{death_coords['z']}`] в {death_coords['time']}",
                    inline=False,
                )
            embed.set_footer(text="Vanilla Land • Профиль")
            view = ProfileView(self, clean_name, None)
            return await ctx.send(embed=embed, view=view)

        is_online = data.get("online", False)
        actual_name = data.get("player", clean_name)
        uuid_str = data.get("uuid", "Неизвестно")
        skin_hash = data.get("skin", "")
        if skin_hash:
            self.db.record_player_skin(actual_name, skin_hash)

        playtime_ticks = data.get("playtime", 0)
        diamonds = data.get("diamonds", 0)
        debris = data.get("debris", 0)
        emeralds = data.get("emeralds", 0)
        gold = data.get("gold", 0)
        iron = data.get("iron", 0)
        kills = data.get("kills", 0)
        deaths = data.get("deaths", 0)
        mob_kills = data.get("mob_kills", 0)
        first_played = data.get("first_played", 0)
        last_played = data.get("last_played", 0)

        # Форматирование времени игры
        total_seconds = playtime_ticks // 20
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        days = hours // 24
        hours_rem = hours % 24
        if days > 0:
            playtime_str = f"**{days}** д. **{hours_rem}** ч. **{minutes}** мин."
        elif hours > 0:
            playtime_str = f"**{hours}** ч. **{minutes}** мин."
        else:
            playtime_str = f"**{minutes}** мин."

        kd_ratio = f"{kills / max(1, deaths):.2f}"

        # Форматирование дат
        if first_played > 0:
            first_ts = int(first_played / 1000)
            first_dt = f"<t:{first_ts}:f> (<t:{first_ts}:R>)"
        else:
            first_dt = "Не зафиксировано"

        if last_played > 0:
            last_ts = int(last_played / 1000)
            last_dt = f"<t:{last_ts}:f> (<t:{last_ts}:R>)"
        else:
            last_dt = "Не зафиксировано"

        # Данные из базы бота
        bot_deaths, last_death_reason = self.db.get_player_deaths(actual_name)
        death_coords = self.db.get_death_coords(actual_name)
        linked = self.db.get_linked_account_by_mc(actual_name)

        avatar_url = get_skin_avatar_url(actual_name, skin_hash, self.db)
        embed_color = 0x57F287 if is_online else 0x4F545C

        desc_parts = []
        if linked:
            desc_parts.append(f"• **Discord:** <@{linked['discord_user_id']}>")
        desc_parts.append(f"• **UUID:** `{uuid_str}`")
        if first_played > 0:
            desc_parts.append(f"• **Первый вход:** {first_dt}")
        if not is_online and last_played > 0:
            desc_parts.append(f"• **Последний вход:** {last_dt}")

        world_names = {
            "world": "Обычный мир (Overworld)",
            "world_nether": "Нижний мир (Nether)",
            "world_the_end": "Энд (The End)",
        }

        embed = discord.Embed(
            title=f"Профиль игрока • {actual_name}",
            description="\n".join(desc_parts),
            color=embed_color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=avatar_url)

        status_text = "**[В сети]**" if is_online else "**[Не в сети]**"
        embed.add_field(name="Статус", value=status_text, inline=True)
        embed.add_field(name="Время в игре", value=playtime_str, inline=True)
        embed.add_field(
            name="PvP и статистика",
            value=f"• K/D: `{kd_ratio}`\n• Убийств игроков: `{kills}`\n• Убийств мобов: `{mob_kills:,}`\n• Смертей: `{deaths}`",
            inline=True,
        )

        embed.add_field(
            name="Выкопанные ценности",
            value=(
                f"• Алмазы: **{diamonds:,}**\n"
                f"• Древние обломки: **{debris:,}**\n"
                f"• Изумруды: **{emeralds:,}**\n"
                f"• Золото: **{gold:,}** | Железо: **{iron:,}**"
            ),
            inline=True,
        )

        if is_online:
            hp = data.get("hp", 20.0)
            max_hp = data.get("max_hp", 20.0)
            food = data.get("food", 20)
            lvl = data.get("level", 0)
            ping = data.get("ping", 0)
            raw_w = data.get("world", "world")
            w_ru = world_names.get(raw_w, raw_w)
            embed.add_field(
                name="Состояние",
                value=f"• Здоровье: `{hp:.1f}/{max_hp:.1f}` HP\n• Сытость: `{food}/20` | Уровень: `{lvl}`\n• Пинг: `{ping} ms` | `{w_ru}`",
                inline=True,
            )

        if death_coords:
            embed.add_field(
                name="Последняя гибель",
                value=f"• Причина: {death_coords['reason'] or 'Неизвестно'}\n• Время: `{death_coords['time']} (МСК)` *(Координаты: `!coords`)*",
                inline=False,
            )

        embed.set_footer(text="Vanilla Land • Профиль игрока")
        view = ProfileView(self, actual_name, skin_hash)
        await ctx.send(embed=embed, view=view)

    # --- КОМАНДА /bc ИЛИ !bc <текст> (ДЛЯ АДМИНИСТРАЦИИ) ---
    @commands.hybrid_command(
        name="bc",
        aliases=["бц", "announce", "объявление", "broadcast", "оповещение"],
        description="Цветное объявление на весь сервер Minecraft (Персонал)",
    )
    @app_commands.describe(text="Текст объявления (&a, &c, &#FFAA00, MiniMessage теги <gradient:...>)")
    async def announce_cmd(self, ctx: commands.Context, *, text: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("У вас нет прав для отправки объявлений на сервер.", ephemeral=True)

        if not self.active_sockets:
            return await ctx.send("Сервер Minecraft сейчас оффлайн.", ephemeral=True)

        payload = {
            "type": "announce",
            "author": ctx.author.display_name,
            "text": text.strip(),
        }
        await self.broadcast_packet(payload)

        embed = discord.Embed(
            title="📢 Объявление отправлено на сервер Minecraft",
            description=f"**Текст:**\n{text.strip()}",
            color=Colors.GREEN,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Отправитель: {ctx.author.display_name}")
        await ctx.send(embed=embed)

    # --- КОМАНДА /coords ИЛИ !coords (КООРДИНАТЫ ПОСЛЕДНЕЙ СМЕРТИ В ЛС) ---
    @commands.hybrid_command(
        name="coords",
        aliases=["координаты", "death_coords", "смерть_координаты"],
        description="Получить координаты последней смерти в ЛС бота",
    )
    @app_commands.describe(player_name="Ник игрока (опционально)")
    async def coords_cmd(self, ctx: commands.Context, player_name: Optional[str] = None):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        if ctx.message:
            try:
                await ctx.message.delete()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        target = (player_name or ctx.author.display_name).strip()
        data = self.db.get_death_coords(target)
        if not data and player_name is None:
            data = self.db.get_death_coords(ctx.author.name)

        if not data:
            msg = f"Для игрока **{target}** не найдено сохранённых координат последней гибели."
            try:
                return await ctx.author.send(msg)
            except discord.Forbidden:
                return await ctx.send(f"{ctx.author.mention}, {msg}", delete_after=6)

        world_names = {
            "world": "🌲 Обычный мир (Верхний мир)",
            "world_nether": "🔥 Нижний мир (Незер / Ад)",
            "world_the_end": "🌌 Энд (Край)",
        }
        w_title = world_names.get(data["world"], f"🗺️ {data['world']}")

        embed = discord.Embed(
            title=f"📍 Координаты последней смерти • {target}",
            description="Сохраните эти данные, чтобы быстрее добраться до места гибели и спасти свои ресурсы!",
            color=Colors.YELLOW,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=get_skin_avatar_url(target, None, self.db))
        embed.add_field(name="🗺️ Измерение", value=w_title, inline=False)
        embed.add_field(
            name="📌 Точные координаты",
            value=f"**X:** `{data['x']}` | **Y:** `{data['y']}` | **Z:** `{data['z']}`",
            inline=False,
        )
        embed.add_field(name="Причина гибели", value=data["reason"] or "Неизвестно", inline=True)
        embed.add_field(name="Время гибели", value=f"{data['time']} (МСК)", inline=True)
        embed.set_footer(text="Vanilla Land • Ваши личные координаты смерти")

        try:
            await ctx.author.send(embed=embed)
            if ctx.channel and ctx.channel.type != discord.ChannelType.private:
                await ctx.channel.send(
                    f"📍 {ctx.author.mention}, координаты гибели отправлены вам в личные сообщения!",
                    delete_after=6,
                )
        except discord.Forbidden:
            if ctx.channel:
                await ctx.channel.send(
                    f"{ctx.author.mention}, у вас закрыты личные сообщения! Откройте ЛС, чтобы бот мог прислать координаты.",
                    delete_after=7,
                )

    # --- КОМАНДА /check ИЛИ !check <ник> (ДОСЬЕ ИГРОКА ДЛЯ ПЕРСОНАЛА) ---
    @commands.hybrid_command(
        name="check",
        aliases=["чек", "player_check", "mc_check"],
        description="Полное досье на игрока Minecraft: IP, пинг, хп, броня, позиция (Персонал)",
    )
    @app_commands.describe(player_name="Никнейм игрока Minecraft")
    async def check_cmd(self, ctx: commands.Context, player_name: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администрации и модерации.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer()

        clean_name = player_name.strip()
        data = await self.query_minecraft({"type": "query_player", "player": clean_name}, timeout=3.5)
        if not data:
            return await ctx.send("Сервер не ответил или оффлайн.", ephemeral=True)

        is_online = data.get("online", False)
        uuid_str = data.get("uuid", "Неизвестно")
        death_count, last_death = self.db.get_player_deaths(clean_name)
        death_coords = self.db.get_death_coords(clean_name)

        if not is_online:
            embed = discord.Embed(
                title=f"🔍 Досье игрока • {clean_name} [ОФФЛАЙН]",
                color=Colors.DARK,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=get_skin_avatar_url(clean_name, data.get("skin"), self.db))
            embed.add_field(name="Статус", value="⚪ Не в сети", inline=True)
            embed.add_field(name="UUID", value=f"`{uuid_str}`", inline=True)
            embed.add_field(name="Смертей в базе", value=f"`{death_count}` (Посл: {last_death})", inline=False)
            if death_coords:
                embed.add_field(
                    name="Посл. точка смерти",
                    value=f"`{death_coords['world']}` [X: {death_coords['x']}, Y: {death_coords['y']}, Z: {death_coords['z']}] в {death_coords['time']}",
                    inline=False,
                )
            embed.set_footer(text="Vanilla Land Staff Dossier")
            return await ctx.send(embed=embed)

        from cogs.inventory_renderer import (
            format_item_name,
            format_potion_effect,
        )

        world = data.get("world", "world")
        x = data.get("x", 0)
        y = data.get("y", 0)
        z = data.get("z", 0)
        hp = data.get("hp", 20.0)
        max_hp = data.get("max_hp", 20.0)
        food = data.get("food", 20)
        lvl = data.get("level", 0)
        ping = data.get("ping", 0)
        ip = data.get("ip", "N/A")
        gamemode = data.get("gamemode", "SURVIVAL")
        helmet = data.get("helmet", "AIR")
        chestplate = data.get("chestplate", "AIR")
        leggings = data.get("leggings", "AIR")
        boots = data.get("boots", "AIR")
        main_hand = data.get("main_hand", "AIR")
        off_hand = data.get("off_hand", "AIR")
        effects = data.get("effects", [])

        embed = discord.Embed(
            title=f"🔍 Досье игрока • {clean_name} [ОНЛАЙН]",
            color=Colors.GREEN,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=get_skin_avatar_url(clean_name, data.get("skin"), self.db))
        embed.add_field(name="UUID", value=f"`{uuid_str}`", inline=True)
        embed.add_field(name="Пинг & IP", value=f"`{ping} ms` | IP: `{ip}`", inline=True)
        embed.add_field(name="Режим игры", value=f"`{gamemode}`", inline=True)
        embed.add_field(name="Здоровье", value=f"`{hp:.1f} / {max_hp:.1f}` HP", inline=True)
        embed.add_field(name="Сытость & Уровень", value=f"Еда: `{food}/20` | Уровень: `{lvl}`", inline=True)
        embed.add_field(name="Координаты", value=f"`{world}` [X: `{x}`, Y: `{y}`, Z: `{z}`]", inline=True)

        helmet_str = format_item_name(helmet)
        chest_str = format_item_name(chestplate)
        legs_str = format_item_name(leggings)
        boots_str = format_item_name(boots)
        main_str = format_item_name(main_hand)
        off_str = format_item_name(off_hand)

        armor_str = f"Шлем: {helmet_str}\nНагрудник: {chest_str}\nПоножи: {legs_str}\nБотинки: {boots_str}"
        hands_str = f"Основная рука: {main_str}\nВторая рука: {off_str}"
        embed.add_field(name="Броня", value=armor_str, inline=True)
        embed.add_field(name="Снаряжение в руках", value=hands_str, inline=True)

        if effects:
            eff_lines = [f"• {format_potion_effect(eff)}" for eff in effects]
            eff_str = "\n".join(eff_lines)
        else:
            eff_str = "*Нет активных эффектов*"
        embed.add_field(name="Зелья и эффекты", value=eff_str, inline=False)

        native_deaths = data.get("deaths")
        deaths_val = native_deaths if native_deaths is not None and native_deaths > 0 else death_count
        deaths_str = f"`{deaths_val}`"
        if last_death and last_death != "Не зафиксировано":
            deaths_str += f" (Последняя: {last_death})"
        embed.add_field(name="Смертей в игре", value=deaths_str, inline=False)

        embed.set_footer(text="Vanilla Land Staff Dossier")
        await ctx.send(embed=embed)

    # --- КОМАНДА /invsee ИЛИ !invsee <ник> (ВИЗУАЛЬНАЯ ИНСПЕКЦИЯ ИНВЕНТАРЯ) ---
    @commands.hybrid_command(
        name="invsee",
        aliases=["инвентарь", "viewinv", "mc_inv"],
        description="Просмотр инвентаря игрока Minecraft в виде фото с шалкерами (Персонал)",
    )
    @app_commands.describe(player_name="Никнейм игрока Minecraft")
    async def invsee_cmd(self, ctx: commands.Context, player_name: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администрации и модерации.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer()

        clean_name = player_name.strip()
        data = await self.query_minecraft({"type": "query_player", "player": clean_name}, timeout=4.5)
        if not data or not data.get("online"):
            return await ctx.send(f"Игрок **{clean_name}** сейчас оффлайн или сервер не ответил.", ephemeral=True)

        from cogs.inventory_renderer import (
            render_inventory_image,
            format_item_name,
        )

        inv_items = data.get("inventory", [])
        armor = {
            "helmet": data.get("helmet", "AIR"),
            "chestplate": data.get("chestplate", "AIR"),
            "leggings": data.get("leggings", "AIR"),
            "boots": data.get("boots", "AIR"),
        }
        main_hand = data.get("main_hand", "AIR")
        off_hand = data.get("off_hand", "AIR")

        img_buf = render_inventory_image(clean_name, inv_items, armor, main_hand, off_hand)
        file = discord.File(fp=img_buf, filename=f"inventory_{clean_name}.png")

        shulker_boxes = [it for it in inv_items if "SHULKER_BOX" in it.get("item", "").upper()]

        embed = discord.Embed(
            title=f"🎒 Инвентарь • {clean_name}",
            description=f"Предметов в рюкзаке: **{len(inv_items)} / 36**",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=get_skin_avatar_url(clean_name, data.get("skin"), self.db))
        embed.set_image(url=f"attachment://inventory_{clean_name}.png")

        view = None
        if shulker_boxes:
            sh_lines = []
            for sh in shulker_boxes:
                slot_num = sh.get("slot", 0) + 1
                sh_name = format_item_name(sh.get("item", ""))
                inside_items = sh.get("shulker_items", [])
                if inside_items:
                    items_preview = ", ".join(f"{format_item_name(i['item'])} ×{i.get('count', 1)}" for i in inside_items[:4])
                    if len(inside_items) > 4:
                        items_preview += f" *(ещё {len(inside_items) - 4})*"
                    sh_lines.append(f"• **Слот {slot_num}** [{sh_name}]: {items_preview}")
                else:
                    sh_lines.append(f"• **Слот {slot_num}** [{sh_name}]: *Пустой шалкер*")

            embed.add_field(
                name=f"Содержимое шалкеров ({len(shulker_boxes)} шт.)",
                value="\n".join(sh_lines[:10]),
                inline=False,
            )
            view = ShulkerSelectView(clean_name, shulker_boxes)

        embed.set_footer(text="Vanilla Land Staff • Инспекция инвентаря")
        if view:
            await ctx.send(embed=embed, file=file, view=view)
        else:
            await ctx.send(embed=embed, file=file)

    # --- КОМАНДА /endersee ИЛИ !endersee <ник> (ВИЗУАЛЬНЫЙ ЭНДЕР-СУНДУК) ---
    @commands.hybrid_command(
        name="endersee",
        aliases=["эндер", "эндерсундук", "ecsee", "mc_ender"],
        description="Просмотр содержимого эндер-сундука в виде фото с шалкерами (Персонал)",
    )
    @app_commands.describe(player_name="Никнейм игрока Minecraft")
    async def endersee_cmd(self, ctx: commands.Context, player_name: str):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администрации и модерации.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer()

        clean_name = player_name.strip()
        data = await self.query_minecraft({"type": "query_player", "player": clean_name}, timeout=4.5)
        if not data or not data.get("online"):
            return await ctx.send(f"Игрок **{clean_name}** сейчас оффлайн или сервер не ответил.", ephemeral=True)

        from cogs.inventory_renderer import (
            render_slots_grid,
            format_item_name,
        )

        ender_items = data.get("ender", [])
        slots_map = {it.get("slot", 0): it for it in ender_items}
        shulker_boxes = [it for it in ender_items if "SHULKER_BOX" in it.get("item", "").upper()]

        img_buf = render_slots_grid(
            f"🟣 Эндер-сундук • {clean_name}",
            clean_name,
            slots_map,
            rows=3,
            cols=9,
            shulker_count=len(shulker_boxes),
        )
        file = discord.File(fp=img_buf, filename=f"ender_{clean_name}.png")

        embed = discord.Embed(
            title=f"🟣 Эндер-сундук • {clean_name}",
            description=f"Всего предметов в сундуке: **{len(ender_items)} / 27**",
            color=0x9B59B6,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=get_skin_avatar_url(clean_name, data.get("skin"), self.db))
        embed.set_image(url=f"attachment://ender_{clean_name}.png")

        view = None
        if shulker_boxes:
            sh_lines = []
            for sh in shulker_boxes:
                slot_num = sh.get("slot", 0) + 1
                sh_name = format_item_name(sh.get("item", ""))
                inside_items = sh.get("shulker_items", [])
                if inside_items:
                    items_preview = ", ".join(f"{format_item_name(i['item'])} ×{i.get('count', 1)}" for i in inside_items[:4])
                    if len(inside_items) > 4:
                        items_preview += f" *(ещё {len(inside_items) - 4})*"
                    sh_lines.append(f"• **Слот {slot_num}** [{sh_name}]: {items_preview}")
                else:
                    sh_lines.append(f"• **Слот {slot_num}** [{sh_name}]: *Пустой шалкер*")

            embed.add_field(
                name=f"Содержимое шалкеров ({len(shulker_boxes)} шт.)",
                value="\n".join(sh_lines[:10]),
                inline=False,
            )
            view = ShulkerSelectView(clean_name, shulker_boxes)

        embed.set_footer(text="Vanilla Land Staff • Инспекция эндер-сундука")
        if view:
            await ctx.send(embed=embed, file=file, view=view)
        else:
            await ctx.send(embed=embed, file=file)

    # --- КОМАНДА /chunks ИЛИ !chunks (ДИАГНОСТИКА ЧАНКОВ, СУЩНОСТЕЙ И ЛАГ-ЗОН) ---
    @commands.hybrid_command(
        name="chunks",
        aliases=["чанки", "entities", "сущности", "mc_chunks"],
        description="Диагностика загруженных чанков, сущностей и лаг-зон (Персонал)",
    )
    async def chunks_cmd(self, ctx: commands.Context):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только администрации и модерации.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer()

        data = await self.query_minecraft({"type": "query_chunks"}, timeout=6.0)
        if not data:
            return await ctx.send("Сервер Minecraft не ответил или оффлайн.", ephemeral=True)

        total_chunks = data.get("total_chunks", 0)
        total_entities = data.get("total_entities", 0)
        total_monsters = data.get("total_monsters", 0)
        total_animals = data.get("total_animals", 0)
        total_items = data.get("total_items", 0)
        total_misc = data.get("total_misc", 0)
        worlds = data.get("worlds", [])
        hot_chunks = data.get("hot_chunks", [])

        world_names_map = {
            "world": "Обычный мир (Overworld)",
            "world_nether": "Нижний мир (Nether)",
            "world_the_end": "Энд (The End)",
        }

        embed = discord.Embed(
            title="Диагностика миров, чанков и лаг-зон",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Всего чанков", value=f"`{total_chunks:,}`", inline=True)
        embed.add_field(name="Всего сущностей", value=f"`{total_entities:,}`", inline=True)
        embed.add_field(name="Сервер (TPS / MSPT)", value=f"`{self.mc_tps:.2f}` TPS • `{self.mc_mspt:.1f}` ms", inline=True)

        if total_monsters or total_animals or total_items:
            embed.add_field(
                name="Классификация сущностей",
                value=(
                    f"• Враждебные мобы: `{total_monsters:,}`\n"
                    f"• Мирные животные: `{total_animals:,}`\n"
                    f"• Выпавшие предметы: `{total_items:,}`\n"
                    f"• Прочие сущности: `{total_misc:,}`"
                ),
                inline=False,
            )

        for w in worlds:
            w_name = w.get("name", "world")
            w_label = world_names_map.get(w_name, f"Мир {w_name}")
            ch = w.get("chunks", 0)
            ent = w.get("entities", 0)
            m_cnt = w.get("monsters", 0)
            it_cnt = w.get("items", 0)
            dragon_st = w.get("dragon_status")
            val = f"• Чанков: `{ch:,}`\n• Сущностей: `{ent:,}` (Мобы: `{m_cnt}`, Дроп: `{it_cnt}`)"
            if dragon_st:
                val += f"\n• Дракон: **{dragon_st}**"
            embed.add_field(
                name=w_label,
                value=val,
                inline=True,
            )

        if hot_chunks:
            hot_lines = []
            for i, hc in enumerate(hot_chunks[:5], 1):
                bx = hc.get("block_x", 0)
                bz = hc.get("block_z", 0)
                cx = hc.get("chunk_x", 0)
                cz = hc.get("chunk_z", 0)
                cnt = hc.get("count", 0)
                near = hc.get("nearest", "Никого")
                w_tag = hc.get("world", "world")
                hot_lines.append(
                    f"**{i}. [{w_tag}] Координаты:** `X: {bx}, Z: {bz}` *(Чанк {cx}, {cz})*\n"
                    f"   ↳ **Сущностей:** `{cnt}` | Рядом: **`{near}`** | ТП: `/tp @s {bx} ~ {bz}`"
                )
            embed.add_field(
                name="ТОП-5 перегруженных чанков (Очаги лагов)",
                value="\n".join(hot_lines),
                inline=False,
            )


        embed.set_footer(text="Vanilla Land Staff • Диагностика оптимизации")
        await ctx.send(embed=embed)

    # --- КОМАНДА /link ИЛИ !link (ПРИВЯЗКА АККАУНТА MINECRAFT) ---
    @commands.hybrid_command(
        name="link",
        aliases=["привязать", "связать", "привязка", "linkaccount"],
        description="Привязать аккаунт Minecraft к Discord и настроить 2FA",
    )
    @app_commands.describe(target="Ваш никнейм в игре или 6-значный код из Minecraft (/link)")
    async def link_cmd(self, ctx: commands.Context, target: Optional[str] = None):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id

        async def send_response(content=None, embed=None, view=None):
            if ctx.interaction:
                return await ctx.send(content=content, embed=embed, view=view, ephemeral=True)
            elif ctx.guild is None:
                # Уже в личных сообщениях с ботом — отправляем напрямую без лишнего уведомления
                return await ctx.send(content=content, embed=embed, view=view)
            else:
                try:
                    await ctx.message.delete()
                except Exception as suppressed_exc:
                    logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
                try:
                    await ctx.author.send(content=content, embed=embed, view=view)
                    await ctx.send(f"{ctx.author.mention}, информация отправлена вам в личные сообщения.", delete_after=5)
                except discord.Forbidden:
                    await ctx.send(f"{ctx.author.mention}, у вас закрыты ЛС. Используйте слэш-команду `/link` для скрытого ответа.", delete_after=7)

        # 0. Проверяем, не привязан ли уже этот Discord пользователь
        linked = self.db.get_linked_account_by_discord(user_id)
        if linked:
            view = AccountSecurityView(self, user_id, linked["player_name"])
            embed = AG.embed(
                title="Аккаунт уже привязан • Vanilla Land",
                description=(
                    f"К вашему Discord-профилю уже привязан игровой аккаунт **`{linked['player_name']}`**!\n\n"
                    "• Привязать более одного аккаунта **нельзя**.\n"
                    "• Если вы хотите сменить ник или привязать другой аккаунт, сначала отвяжите текущий командой `!unlink`.\n\n"
                    "> Ниже представлены настройки безопасности вашего текущего аккаунта:"
                ),
                color=Colors.YELLOW,
                thumbnail=get_skin_avatar_url(linked["player_name"], None, self.db),
            )
            return await send_response(embed=embed, view=view)

        # 1. Если аргумент не указан
        if not target:
            embed = AG.embed(
                title="🔗 Привязка аккаунта • Vanilla Land",
                description=(
                    "Привяжите ваш игровой аккаунт Minecraft к Discord для активации двухфакторной защиты (2FA)!\n\n"
                    "**Как привязать аккаунт:**\n"
                    "• **Способ 1:** Напишите `!link <ВашНик>` (бот выдаст 6-значный код для ввода на сервере)\n"
                    "• **Способ 2:** Напишите в игре `/link` и введите полученный код сюда: `!link <код>`\n\n"
                    "> Привязка занимает всего 10 секунд и надёжно защищает ваш аккаунт от взлома."
                ),
                color=Colors.INDIGO,
            )
            return await send_response(embed=embed)

        clean_target = target.strip()

        # 2. Если введён 6-значный код (полученный из Minecraft)
        if clean_target.isdigit() and len(clean_target) == 6:
            if not self.link_rate_ok(user_id):
                return await send_response(content="⏳ Слишком много попыток ввода кода. Попробуйте снова через 10 минут.")
            code_info = self.db.get_link_code(clean_target)
            if code_info and code_info.get("discord_user_id") and int(code_info["discord_user_id"]) != int(user_id):
                return await send_response(content="❌ Этот код принадлежит другому Discord-пользователю. Получите код в своём аккаунте.")
            if code_info:
                code_info = self.db.consume_link_code(clean_target)
            if code_info and code_info.get("player_name"):
                player_name = code_info["player_name"]

                # Проверяем, не привязан ли уже этот Minecraft аккаунт
                already_mc = self.db.get_linked_account_by_mc(player_name)
                if already_mc:
                    return await send_response(content=f"Игровой аккаунт **`{player_name}`** уже привязан к Discord! Повторная привязка невозможна.")

                success = self.db.link_account(player_name, "", user_id, two_factor=1)
                if success:
                    # Оповещаем сервер Minecraft и запрашиваем кик для перезахода (Вариант Б)
                    await self.broadcast_packet({
                        "type": "link_result",
                        "player": player_name,
                        "success": True,
                        "discord_tag": str(ctx.author),
                        "kick_relogin": True,
                    })

                    embed = AG.embed(
                        title="✨ Аккаунт успешно привязан • Vanilla Land",
                        description=(
                            f"Ваш аккаунт Minecraft **`{player_name}`** успешно синхронизирован с Discord!\n\n"
                            "• **Двухфакторная защита (2FA):** `[Включена]`\n"
                            "• **Вход:** Сервер запросил перезаход для входа с 2FA.\n"
                            "• **Управление:** Введите `!security` для настройки сессий.\n\n"
                            "> Теперь при входе с новых IP бот будет присылать подтверждение в этот чат."
                        ),
                        color=Colors.GREEN,
                        thumbnail=get_skin_avatar_url(player_name, None, self.db),
                    )
                    view = AccountSecurityView(self, user_id, player_name)
                    return await send_response(embed=embed, view=view)
                else:
                    return await send_response(content="Не удалось привязать: этот аккаунт уже привязан.")
            else:
                return await send_response(content="Код не найден или истёк срок его действия (10 минут). Введите `/link` в игре повторно.")

        # 3. Если введён никнейм игрока
        player_name = clean_target
        already_linked = self.db.get_linked_account_by_mc(player_name)
        if already_linked:
            return await send_response(content=f"Игровой аккаунт **`{player_name}`** уже привязан к Discord! Повторная привязка невозможна.")

        # Генерируем 6-значный код
        code = f"{secrets.randbelow(900000) + 100000}"
        self.db.create_link_code(player_name=player_name, discord_user_id=user_id, code=code, lifetime_sec=600)

        embed = AG.embed(
            title="🔗 Завершение привязки • Vanilla Land",
            description=(
                f"Для завершения связки аккаунта **`{player_name}`** зайдите на сервер Minecraft и введите команду:\n\n"
                f"```fix\n/link {code}\n```\n"
                f"• **Срок действия кода:** `10 минут`\n"
                f"• **Одноразовый код:** `{code}`\n\n"
                "> Во время ввода команды аккаунт будет мгновенно привязан к вашему Discord!"
            ),
            color=Colors.INDIGO,
            thumbnail=get_skin_avatar_url(player_name, None, self.db),
        )
        await send_response(embed=embed)


    # --- КОМАНДА /security ИЛИ !security (УПРАВЛЕНИЕ 2FA И СЕССИЯМИ) ---
    @commands.hybrid_command(
        name="security",
        aliases=["безопасность", "2fa", "защита", "сессии", "ip_security"],
        description="Управление двухфакторной аутентификацией (2FA) и доверенными IP-сессиями",
    )
    async def security_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id
        linked = self.db.get_linked_account_by_discord(user_id)
        if not linked:
            embed = AG.embed(
                title="Безопасность аккаунта • Vanilla Land",
                description=(
                    "У вас пока нет привязанного аккаунта Minecraft!\n\n"
                    "Для привязки введите команду:\n"
                    "• `!link <ВашНик>` в Discord\n"
                    "• Или `/link` на сервере Minecraft."
                ),
                color=Colors.YELLOW,
            )
            if ctx.interaction:
                return await ctx.send(embed=embed, ephemeral=True)
            else:
                try:
                    await ctx.message.delete()
                except Exception as suppressed_exc:
                    logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
                try:
                    await ctx.author.send(embed=embed)
                    await ctx.send(f"{ctx.author.mention}, информация отправлена в ЛС.", delete_after=5)
                except discord.Forbidden:
                    await ctx.send(f"{ctx.author.mention}, у вас закрыты ЛС. Используйте слэш-команду `/security` для приватного просмотра.", delete_after=7)
                return

        view = AccountSecurityView(self, user_id, linked["player_name"])
        embed = view.build_embed()
        if ctx.interaction:
            await ctx.send(embed=embed, view=view, ephemeral=True)
        else:
            try:
                await ctx.message.delete()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
            try:
                await ctx.author.send(embed=embed, view=view)
                await ctx.send(f"{ctx.author.mention}, панель безопасности отправлена вам в ЛС (в целях конфиденциальности IP).", delete_after=6)
            except discord.Forbidden:
                await ctx.send(f"{ctx.author.mention}, у вас закрыты ЛС. Используйте слэш-команду `/security` для приватного просмотра прямо здесь.", delete_after=7)

    # --- КОМАНДА /unlink ИЛИ !unlink (ОТВЯЗКА АККАУНТА) ---
    @commands.hybrid_command(
        name="unlink",
        aliases=["отвязать", "отвязка"],
        description="Отвязать аккаунт Minecraft от Discord",
    )
    async def unlink_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        user_id = ctx.author.id
        linked = self.db.get_linked_account_by_discord(user_id)
        if not linked:
            if ctx.interaction:
                return await ctx.send("У вас нет привязанного аккаунта Minecraft.", ephemeral=True)
            else:
                return await ctx.send(f"{ctx.author.mention}, у вас нет привязанного аккаунта Minecraft.", delete_after=5)

        player_name = self.db.unlink_account_by_discord(user_id)
        if player_name:
            self.pending_2fa.pop(player_name.lower(), None)
            try:
                await self.broadcast_packet({"type": "account_unlinked", "player": player_name})
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)

        embed = AG.embed(
            title="Аккаунт отвязан • Vanilla Land",
            description=f"Аккаунт Minecraft **`{player_name}`** успешно отвязан от вашего Discord. Двухфакторная защита 2FA отключена.",
            color=Colors.DARK,
        )
        if ctx.interaction:
            await ctx.send(embed=embed, ephemeral=True)
        else:
            try:
                await ctx.message.delete()
            except Exception as suppressed_exc:
                logger.debug("Bridge non-fatal operation suppressed: %s", suppressed_exc)
            await ctx.send(f"Аккаунт `{player_name}` успешно отвязан.", delete_after=6)

    # --- КОМАНДА /maintenance ИЛИ !maintenance / !техработы ---
    @commands.hybrid_command(
        name="maintenance",
        aliases=["техработы", "maint"],
        description="Управление режимом технических работ и перезагрузкой сервера Minecraft (Персонал)",
    )
    @app_commands.describe(
        action="on (вкл), off (выкл), timer (таймер), restart (рестарт), status (статус)",
        param="Время (например: 5m, 300s) или причина",
        reason="Причина техработ или рестарта",
    )
    async def maintenance_cmd(
        self,
        ctx: commands.Context,
        action: str = "status",
        param: Optional[str] = None,
        *,
        reason: Optional[str] = None,
    ):
        if not is_mod_or_admin(ctx):
            return await ctx.send("Эта команда доступна только персоналу и администрации.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer()

        clean_act = action.lower().strip()
        if clean_act in ("on", "вкл", "enable", "1"):
            actual_reason = param if not reason else f"{param} {reason}".strip()
            if not actual_reason:
                actual_reason = "Техническое обслуживание сервера"

            self.maintenance_enabled = True
            self.maintenance_reason = actual_reason
            await self.broadcast_packet({
                "type": "maintenance",
                "enabled": True,
                "reason": actual_reason,
            })
            await self.update_bot_presence()
            embed = AG.embed(
                title="Технические работы включены • Vanilla Land",
                description=(
                    f"**Причина:** {actual_reason}\n\n"
                    "• Обычные игроки отключены от сервера.\n"
                    "• Администрация сервера имеет доступ.\n"
                    "• Оповещение разослано в каналы событий."
                ),
                color=Colors.YELLOW,
            )
            return await ctx.send(embed=embed)

        elif clean_act in ("off", "выкл", "disable", "0"):
            self.maintenance_enabled = False
            self.was_restarting = False
            await self.broadcast_packet({
                "type": "maintenance_countdown_cancel",
            })
            await self.broadcast_packet({
                "type": "maintenance",
                "enabled": False,
            })
            await self.update_bot_presence()
            embed = AG.embed(
                title="Технические работы завершены • Vanilla Land",
                description="Сервер снова открыт для всех желающих! Оповещение отправлено в игру.",
                color=Colors.GREEN,
            )
            return await ctx.send(embed=embed)

        elif clean_act in ("cancel", "отмена", "stop", "стоп"):
            self.maintenance_enabled = False
            self.was_restarting = False
            await self.broadcast_packet({
                "type": "maintenance_countdown_cancel",
            })
            await self.broadcast_packet({
                "type": "maintenance",
                "enabled": False,
            })
            await self.update_bot_presence()
            embed = AG.embed(
                title="Обратный отсчёт отменён • Vanilla Land",
                description="Активный таймер перезагрузки/техработ успешно остановлен. Сервер работает в штатном режиме.",
                color=Colors.GREEN,
            )
            return await ctx.send(embed=embed)

        elif clean_act in ("extend", "продлить", "+"):
            duration_str = param or "1m"
            seconds = 60
            if duration_str.endswith("m") or duration_str.endswith("м"):
                try:
                    seconds = int(duration_str[:-1]) * 60
                except ValueError:
                    seconds = 60
            elif duration_str.endswith("s") or duration_str.endswith("с"):
                try:
                    seconds = int(duration_str[:-1])
                except ValueError:
                    seconds = 60
            else:
                try:
                    seconds = int(duration_str)
                except ValueError:
                    seconds = 60

            await self.broadcast_packet({
                "type": "maintenance_countdown_extend",
                "seconds": seconds,
            })
            embed = AG.embed(
                title="Таймер продлён • Vanilla Land",
                description=f"К текущему обратному отсчёту добавлено **+{seconds // 60} мин. {seconds % 60} сек.**.",
                color=Colors.GREEN,
            )
            return await ctx.send(embed=embed)

        elif clean_act in ("timer", "таймер", "countdown"):
            duration_str = param or "5m"
            actual_reason = reason or "Техническое обслуживание сервера"
            seconds = 300
            if duration_str.endswith("m") or duration_str.endswith("м"):
                try:
                    seconds = int(duration_str[:-1]) * 60
                except ValueError:
                    seconds = 300
            elif duration_str.endswith("s") or duration_str.endswith("с"):
                try:
                    seconds = int(duration_str[:-1])
                except ValueError:
                    seconds = 300
            else:
                try:
                    seconds = int(duration_str)
                except ValueError:
                    seconds = 300

            await self.broadcast_packet({
                "type": "maintenance_countdown",
                "seconds": seconds,
                "reason": actual_reason,
                "mode": "lock",
            })
            embed = AG.embed(
                title="Запущен таймер техработ • Vanilla Land",
                description=(
                    f"**До отключения:** `{seconds // 60} мин. {seconds % 60} сек.`\n"
                    f"**Причина:** {actual_reason}\n\n"
                    "В игре запущен обратный отсчёт на экране и в ActionBar. "
                    "По истечении времени сервер закроется на обслуживание."
                ),
                color=Colors.INDIGO,
            )
            return await ctx.send(embed=embed)

        elif clean_act in ("restart", "рестарт", "перезагрузка"):
            duration_str = param or "3m"
            actual_reason = reason or "Плановая перезагрузка сервера"
            seconds = 180
            if duration_str.endswith("m") or duration_str.endswith("м"):
                try:
                    seconds = int(duration_str[:-1]) * 60
                except ValueError:
                    seconds = 180
            elif duration_str.endswith("s") or duration_str.endswith("с"):
                try:
                    seconds = int(duration_str[:-1])
                except ValueError:
                    seconds = 180
            else:
                try:
                    seconds = int(duration_str)
                except ValueError:
                    seconds = 180

            self.was_restarting = True
            await self.broadcast_packet({
                "type": "maintenance_countdown",
                "seconds": seconds,
                "reason": actual_reason,
                "mode": "restart",
            })
            embed = AG.embed(
                title="Запланирован рестарт сервера • Vanilla Land",
                description=(
                    f"**До рестарта:** `{seconds // 60} мин. {seconds % 60} сек.`\n"
                    f"**Причина:** {actual_reason}\n\n"
                    "В игре объявлен таймер до перезагрузки. "
                    "После рестарта сервер **автоматически откроется** для всех игроков в обычном режиме."
                ),
                color=Colors.YELLOW,
            )
            return await ctx.send(embed=embed)

        else:
            status_text = "ВКЛЮЧЕНЫ" if self.maintenance_enabled else "ВЫКЛЮЧЕНЫ"
            color = Colors.YELLOW if self.maintenance_enabled else Colors.GREEN
            embed = AG.embed(
                title="Статус технических работ • Vanilla Land",
                description=(
                    f"• **Текущий статус:** `{status_text}`\n"
                    f"• **Причина:** `{self.maintenance_reason}`\n\n"
                    "**Команды управления:**\n"
                    "• `!техработы вкл [причина]` — Закрыть сервер немедленно\n"
                    "• `!техработы таймер 5м [причина]` — Закрыть через таймер (останется закрытым)\n"
                    "• `!техработы рестарт 3м [причина]` — Перезагрузить с таймером (после рестарта откроется)\n"
                    "• `!техработы выкл` — Открыть сервер для всех"
                ),
                color=color,
            )
            return await ctx.send(embed=embed)


    # --- КОМАНДА /link_panel ИЛИ !link_panel (ПАНЕЛЬ ПРИВЯЗКИ ДЛЯ АДМИНИСТРАЦИИ) ---
    @commands.hybrid_command(
        name="link_panel",
        aliases=["панель_привязки", "linkpanel", "привязка_панель"],
        description="Отправить интерактивную панель привязки аккаунтов (Администрация)",
    )
    @app_commands.describe(channel="Канал для отправки панели (по умолчанию текущий)")
    @commands.has_permissions(administrator=True)
    async def link_panel_cmd(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or ctx.channel
        guild_icon = ctx.guild.icon.url if ctx.guild and ctx.guild.icon else None

        embed = discord.Embed(
            title="Привязка аккаунта Minecraft • Vanilla Land",
            description=(
                "Привяжите ваш игровой никнейм к профилю Discord для защиты персонажа и быстрого подтверждения входа.\n\n"
                "**Возможности привязки:**\n"
                "• **Двухфакторная защита (2FA):** Вход с нового IP подтверждается в 1 клик через Discord\n"
                "• **Push-уведомления:** Оповещения в ЛС при каждой попытке подключения\n"
                "• **Гибкие сессии:** Выбор срока доверия к IP (от строгого до 7 дней)\n\n"
                "> Нажмите кнопку ниже для привязки или проверки настроек:"
            ),
            color=0xFF8C00,
        )
        if guild_icon:
            embed.set_thumbnail(url=guild_icon)
        embed.set_footer(text="Vanilla Land • Безопасность")
        view = PermanentLinkPanelView(self)
        await target_ch.send(embed=embed, view=view)
        await ctx.send(f"Панель привязки аккаунтов успешно отправлена в {target_ch.mention}.", ephemeral=True)


class ShulkerSelectView(ui.View):
    """Интерактивное меню выбора и визуального рендера шалкера"""
    def __init__(self, player_name: str, shulkers: List[dict]):
        super().__init__(timeout=120)
        self.player_name = player_name
        self.shulkers = {sh.get("slot", 0): sh for sh in shulkers}

        from cogs.inventory_renderer import ITEM_TRANSLATIONS

        options = []
        for sh in shulkers[:25]:
            slot_idx = sh.get("slot", 0)
            raw_item = sh.get("item", "")
            inside_items = sh.get("shulker_items", [])
            item_ru, _ = ITEM_TRANSLATIONS.get(raw_item.upper(), (raw_item, ""))
            label = f"Слот {slot_idx + 1}: {item_ru}"
            desc = f"Внутри предметов: {len(inside_items)} / 27" if inside_items else "Пустой шалкер"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(slot_idx),
                    description=desc[:100],
                    
                )
            )

        select = ui.Select(placeholder="Выберите шалкер для просмотра содержимого...", options=options)
        select.callback = self.on_shulker_selected
        self.add_item(select)

    async def on_shulker_selected(self, interaction: discord.Interaction):
        slot_idx = int(interaction.data["values"][0])
        sh = self.shulkers.get(slot_idx)
        if not sh:
            return await interaction.response.send_message("Шалкер не найден.", ephemeral=True)

        from cogs.inventory_renderer import (
            render_slots_grid,
            format_item_name,
            ITEM_TRANSLATIONS,
        )

        raw_item = sh.get("item", "")
        item_ru, _ = ITEM_TRANSLATIONS.get(raw_item.upper(), (raw_item, ""))
        inside_items = sh.get("shulker_items", [])

        slots_map = {it.get("slot", 0): it for it in inside_items}
        buf = render_slots_grid(
            f"{item_ru} (Слот {slot_idx + 1}) • {self.player_name}",
            self.player_name,
            slots_map,
            rows=3,
            cols=9,
            accent_color="#A855F7",
        )
        file = discord.File(fp=buf, filename=f"shulker_slot_{slot_idx + 1}.png")

        items_list = []
        for it in inside_items:
            s = it.get("slot", 0) + 1
            it_name = format_item_name(it.get("item", ""))
            cnt = it.get("count", 1)
            items_list.append(f"• Слот `{s}`: {it_name} ×{cnt}")

        embed = discord.Embed(
            title=f"Содержимое: {item_ru} (Слот {slot_idx + 1})",
            description=f"Владелец: **{self.player_name}** | Предметов внутри: **{len(inside_items)} / 27**",
            color=0xA855F7,
        )
        embed.set_image(url=f"attachment://shulker_slot_{slot_idx + 1}.png")
        if items_list:
            embed.add_field(name="Список предметов внутри", value="\n".join(items_list[:15]), inline=False)
            if len(items_list) > 15:
                embed.add_field(name="Список (продолжение)", value="\n".join(items_list[15:30]), inline=False)
        else:
            embed.add_field(name="Содержимое", value="*Шалкер абсолютно пуст.*", inline=False)

        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)




class TopLeaderboardView(ui.View):
    """Интерактивное меню таблицы рекордов сервера Vanilla Land"""
    def __init__(self, data: dict, initial_category: Optional[str] = None):
        super().__init__(timeout=180)
        self.data = data
        self.current_cat = (initial_category or "all").lower().strip()
        self.update_buttons()

    def update_buttons(self):
        for child in self.children:
            if isinstance(child, ui.Button):
                cat = child.custom_id.replace("top:cat_", "")
                if cat == self.current_cat or (cat == "all" and self.current_cat in ("all", "summary", "общий")):
                    child.style = discord.ButtonStyle.success
                else:
                    child.style = discord.ButtonStyle.secondary

    def build_embed(self) -> discord.Embed:
        cat = self.current_cat
        if cat in ("playtime", "время", "онлайн"):
            return self._build_category_embed("playtime", "Топ по наигранному времени • Vanilla Land", "Время в игре", is_time=True)
        elif cat in ("diamonds", "алмазы", "алмаз"):
            return self._build_category_embed("diamonds", "Топ шахтёров (Добыто алмазов) • Vanilla Land", "Добыто алмазной руды")
        elif cat in ("debris", "обломки", "незерит"):
            return self._build_category_embed("debris", "Топ искателей незерита (Древние обломки) • Vanilla Land", "Добыто древних обломков")
        elif cat in ("kills", "киллы", "убийства", "pvp"):
            return self._build_category_embed("kills", "Топ дуэлянтов (PvP Убийства) • Vanilla Land", "Убийств игроков")
        elif cat in ("deaths", "смерти"):
            return self._build_category_embed("deaths", "Статистика смертей • Vanilla Land", "Всего смертей")
        else:
            return self._build_summary_embed()

    def _format_time(self, ticks: int) -> str:
        total_seconds = ticks // 20
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        days = hours // 24
        hours_rem = hours % 24
        if days > 0:
            return f"{days} д. {hours_rem} ч. {minutes} мин."
        elif hours > 0:
            return f"{hours} ч. {minutes} мин."
        else:
            return f"{minutes} мин."

    def _build_summary_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Доска почёта • Vanilla Land",
            description=(
                "Главные рекорды и лидеры сервера (Сезон: Вайп от 22 ноября).\n"
                "*Нажимайте кнопки ниже, чтобы открыть подробный ТОП-10 в каждой категории.*"
            ),
            color=Colors.GOLD,
            timestamp=datetime.now(timezone.utc),
        )

        medals = ["#1", "#2", "#3"]

        # 1. Время
        pt_list = self.data.get("playtime", [])
        if pt_list:
            lines = []
            for i, it in enumerate(pt_list[:3]):
                m = medals[i] if i < 3 else f"{i+1}."
                lines.append(f"`{m}` **{it['player']}** — {self._format_time(it.get('value', 0))}")
            embed.add_field(name="Время в игре", value="\n".join(lines), inline=True)

        # 2. Алмазы
        dia_list = self.data.get("diamonds", [])
        if dia_list:
            lines = []
            for i, it in enumerate(dia_list[:3]):
                m = medals[i] if i < 3 else f"{i+1}."
                lines.append(f"`{m}` **{it['player']}** — {it.get('value', 0):,} шт.")
            embed.add_field(name="Алмазные руды", value="\n".join(lines), inline=True)

        # 3. Незерит
        deb_list = self.data.get("debris", [])
        if deb_list:
            lines = []
            for i, it in enumerate(deb_list[:3]):
                m = medals[i] if i < 3 else f"{i+1}."
                lines.append(f"`{m}` **{it['player']}** — {it.get('value', 0):,} шт.")
            embed.add_field(name="Древние обломки", value="\n".join(lines), inline=True)

        # 4. PvP Убийства
        kills_list = self.data.get("kills", [])
        if kills_list:
            lines = []
            for i, it in enumerate(kills_list[:3]):
                m = medals[i] if i < 3 else f"{i+1}."
                lines.append(f"`{m}` **{it['player']}** — {it.get('value', 0):,} киллов")
            embed.add_field(name="PvP Убийства", value="\n".join(lines), inline=True)

        # 5. Смерти
        deaths_list = self.data.get("deaths", [])
        if deaths_list:
            lines = []
            for i, it in enumerate(deaths_list[:3]):
                m = medals[i] if i < 3 else f"{i+1}."
                lines.append(f"`{m}` **{it['player']}** — {it.get('value', 0):,} раз")
            embed.add_field(name="Смерти игроков", value="\n".join(lines), inline=True)

        if pt_list and pt_list[0].get("player"):
            top_player = pt_list[0]["player"]
            top_skin = pt_list[0].get("skin")
            embed.set_thumbnail(url=get_skin_avatar_url(top_player, top_skin))

        embed.set_footer(text="Vanilla Land • Вайп от 22 ноября 2026")
        return embed

    def _build_category_embed(self, key: str, title: str, val_label: str, is_time: bool = False) -> discord.Embed:
        items = self.data.get(key, [])
        embed = discord.Embed(
            title=title,
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )

        medals = {1: "#1", 2: "#2", 3: "#3"}

        if not items:
            embed.description = "*В этой категории пока нет записанных данных.*"
        else:
            lines = []
            for i, it in enumerate(items[:10], 1):
                p_name = it.get("player", "Игрок")
                raw_val = it.get("value", 0)
                formatted_val = self._format_time(raw_val) if is_time else f"{raw_val:,} шт."
                if key == "kills":
                    formatted_val = f"{raw_val:,} киллов"
                elif key == "deaths":
                    formatted_val = f"{raw_val:,} смертей"

                badge = medals.get(i, f"#{i}")
                lines.append(f"`{badge}` **{p_name}** — `{formatted_val}`")

            embed.description = f"**Топ игроков сервера по критерию: {val_label}**\n\n" + "\n".join(lines)

            top_player = items[0].get("player", "")
            top_skin = items[0].get("skin", "")
            if top_player:
                embed.set_thumbnail(url=get_skin_avatar_url(top_player, top_skin))

        embed.set_footer(text="Vanilla Land • Вайп от 22 ноября 2026")
        return embed

    @ui.button(label="Общий", style=discord.ButtonStyle.success, custom_id="top:cat_all")
    async def btn_all(self, interaction: discord.Interaction, button: ui.Button):
        self.current_cat = "all"
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="Время", style=discord.ButtonStyle.secondary, custom_id="top:cat_playtime")
    async def btn_playtime(self, interaction: discord.Interaction, button: ui.Button):
        self.current_cat = "playtime"
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="Алмазы", style=discord.ButtonStyle.secondary, custom_id="top:cat_diamonds")
    async def btn_diamonds(self, interaction: discord.Interaction, button: ui.Button):
        self.current_cat = "diamonds"
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="Незерит", style=discord.ButtonStyle.secondary, custom_id="top:cat_debris")
    async def btn_debris(self, interaction: discord.Interaction, button: ui.Button):
        self.current_cat = "debris"
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="PvP", style=discord.ButtonStyle.secondary, custom_id="top:cat_kills")
    async def btn_kills(self, interaction: discord.Interaction, button: ui.Button):
        self.current_cat = "kills"
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class ProfileView(ui.View):
    """Интерактивное меню профиля игрока Minecraft"""
    def __init__(self, bridge_cog: "BridgeCog", player_name: str, skin_hash: Optional[str] = None):
        super().__init__(timeout=180)
        self.bridge_cog = bridge_cog
        self.player_name = player_name
        self.skin_hash = skin_hash

        # Ссылка на NameMC профиль
        self.add_item(
            ui.Button(
                label="Скин на NameMC",
                url=f"https://namemc.com/profile/{player_name}",
            )
        )

    @ui.button(label="Скин в полный рост", style=discord.ButtonStyle.secondary)
    async def view_skin_btn(self, interaction: discord.Interaction, button: ui.Button):
        body_url = get_skin_body_url(self.player_name, self.skin_hash, self.bridge_cog.db)
        embed = discord.Embed(
            title=f"Внешний вид персонажа • {self.player_name}",
            color=Colors.INDIGO,
        )
        embed.set_image(url=body_url)
        embed.set_footer(text="Vanilla Land • 3D рендер скина")
        if interaction.guild is None:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="🖼️ Карточка (PNG)", style=discord.ButtonStyle.primary)
    async def view_card_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        from cogs.inventory_renderer import render_profile_card

        cache_key = self.player_name.lower()
        stats = {}
        if cache_key in self.bridge_cog.cached_player_stats:
            _, stats = self.bridge_cog.cached_player_stats[cache_key]

        is_online = stats.get("online", False)
        ticks = stats.get("playtime", 0)
        h = ticks // 72000
        m = (ticks % 72000) // 1200
        playtime_str = f"{h} ч {m} мин" if ticks > 0 else "0 ч"

        kills = stats.get("kills", 0)
        deaths = stats.get("deaths", 0)
        kd = round(kills / max(1, deaths), 2)
        diamonds = stats.get("diamonds", 0)
        debris = stats.get("netherite_scrap", stats.get("debris", 0))
        lvl = stats.get("level", 0)
        world_raw = stats.get("world", "world")
        world_map = {"world": "Верхний мир", "world_nether": "Незеp", "world_the_end": "Энд"}
        world_name = world_map.get(world_raw, "Верхний мир")

        buf = render_profile_card(
            player_name=self.player_name,
            is_online=is_online,
            playtime_str=playtime_str,
            diamonds=diamonds,
            debris=debris,
            kills=kills,
            deaths=deaths,
            kd_ratio=kd,
            world_name=world_name,
            level=lvl,
        )
        file = discord.File(buf, filename=f"profile_{self.player_name}.png")
        await interaction.followup.send(file=file, ephemeral=True)



async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    cog = BridgeCog(bot, db)
    await bot.add_cog(cog)
    # Persistent-вью: работают после рестарта бота (данные резолвятся по interaction.user.id)
    bot.add_view(PermanentLinkPanelView(cog))
    bot.add_view(AccountSecurityView(cog))
    bot.add_view(LoginAlertView(cog))
    bot.add_view(DmReplyView(cog))

