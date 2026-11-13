import logging
import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CWD = Path.cwd()

# 0. Автодобавление новых несекретных ключей (значения не перезаписываются).
# Отключается переменной VANILLA_ENV_SYNC=0 (используется в тестах).
try:
    from config_sync import sync_env_file

    if os.getenv("VANILLA_ENV_SYNC", "1") != "0":
        sync_env_file()
except Exception:
    pass

# 1. Поиск и загрузка .env
env_loaded = False
for directory in [BASE_DIR, CWD]:
    for filename in [".env", ".env.txt", "config.env", "bot.env"]:
        candidate = directory / filename
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate, override=False, encoding="utf-8")
            env_loaded = True
            break
    if env_loaded:
        break

if not env_loaded:
    load_dotenv(override=False)

# 2. Резервный парсер
for directory in [BASE_DIR, CWD]:
    for filename in [".env", ".env.txt"]:
        candidate = directory / filename
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip().upper()
                            v = v.strip().strip('"').strip("'")
                            if k and v and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass


def _resolve_token() -> str:
    raw = (
        os.getenv("DISCORD_TOKEN")
        or os.getenv("BOT_TOKEN")
        or os.getenv("TOKEN")
        or os.getenv("discord_token")
        or os.getenv("bot_token")
        or os.getenv("token")
        or ""
    )
    return raw.strip().strip('"').strip("'")


def _resolve_server_ip() -> str:
    """Игнорирует системный адрес 0.0.0.0 хостинга Pterodactyl/Docker"""
    mc_ip = os.getenv("MC_SERVER_IP", "").strip()
    if mc_ip and mc_ip not in ("0.0.0.0", "127.0.0.1"):
        return mc_ip

    srv_ip = os.getenv("SERVER_IP", "").strip()
    if srv_ip and srv_ip not in ("0.0.0.0", "127.0.0.1"):
        return srv_ip

    return "vanillaland.ru-mc.ru"


def _env_int(name: str, default: int = 0) -> int:
    """int из env без падения на мусорном значении (например BRIDGE_PORT=abc)."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            logging.getLogger("VanillaBot.Config").warning(
                "Некорректное значение %s=%r, использую %s", name, raw, default
            )
            return default


def _env_float(name: str, default: float = 0.0) -> float:
    """float из env с поддержкой запятой (48,5) и без падения на мусоре."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        logging.getLogger("VanillaBot.Config").warning(
            "Некорректное значение %s=%r, использую %s", name, raw, default
        )
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    """bool из env (1, true, yes, on -> True; 0, false, no, off -> False)."""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on", "y"):
        return True
    if raw in ("0", "false", "no", "off", "n"):
        return False
    logging.getLogger("VanillaBot.Config").warning(
        "Некорректное значение %s=%r, использую %s", name, raw, default
    )
    return default


class Config:
    DISCORD_TOKEN: str = _resolve_token()
    DISCORD_PROXY: Optional[str] = (
        os.getenv("DISCORD_PROXY")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or ""
    ).strip() or None
    GUILD_ID: int = _env_int("GUILD_ID", 0)
    PANEL_CHANNEL_ID: int = _env_int("PANEL_CHANNEL_ID", 0)
    TICKETS_CATEGORY_ID: int = _env_int("TICKETS_CATEGORY_ID", 0)

    # Каналы для логов и оповещений
    LOG_CHANNEL_ID: int = _env_int("LOG_CHANNEL_ID", 0)
    ADMIN_LOG_CHANNEL_ID: int = _env_int("ADMIN_LOG_CHANNEL_ID", 0)
    ALTS_ALERT_CHANNEL_ID: int = _env_int("ALTS_ALERT_CHANNEL_ID", 0)

    # Роли персонала (доступ к модерации и тикетам)
    MOD_ROLE_IDS: list[int] = [
        int(r.strip())
        for r in os.getenv(
            "MOD_ROLE_IDS",
            "1542891413887262811,1472604035528921099,1543299319874981968",
        ).split(",")
        if r.strip().isdigit()
    ]
    # Отдельные роли для security-команд (если пусто — используется MOD_ROLE_IDS)
    ADMIN_ROLE_IDS: list[int] = [
        int(r.strip())
        for r in os.getenv("ADMIN_ROLE_IDS", "").split(",")
        if r.strip().isdigit()
    ]
    SPEC_ROLE_ID: int = _env_int("SPEC_ROLE_ID", 0)

    # Роль для пинга в тикетах (вместо СММ)
    TICKET_PING_ROLE_ID: int = _env_int("TICKET_PING_ROLE_ID", 1563526341742297158)

    # Роли верификации
    UNVERIFIED_ROLE_ID: int = _env_int("UNVERIFIED_ROLE_ID", 1557849914233589913)
    VERIFIED_ROLE_ID: int = _env_int("VERIFIED_ROLE_ID", 1472644628451950703)
    VERIFICATION_CHANNEL_ID: int = _env_int("VERIFICATION_CHANNEL_ID", 1555500688715423835)

    # Роль мута
    MUTE_ROLE_ID: int = _env_int("MUTE_ROLE_ID", 1472669326237761586)

    # Серверная информация и официальные ссылки
    SERVER_IP: str = _resolve_server_ip()
    SITE_URL: str = os.getenv("SITE_URL", "https://vanillaland.fun").strip()
    DISCORD_URL: str = os.getenv("DISCORD_URL", "https://discord.gg/Ba5cMK7F6a").strip()
    TELEGRAM_URL: str = os.getenv("TELEGRAM_URL", "https://t.me/vanilandes").strip()
    VK_URL: str = os.getenv("VK_URL", "https://vk.ru/vanillalandmine").strip()
    DONATE_URL: str = os.getenv(
        "DONATE_URL", "https://vanillaland.store"
    ).strip()
    RULES_URL: str = os.getenv(
        "RULES_URL",
        "https://docs.google.com/document/d/1N3CiINifkUWb3iqBPbsxUzgm8o5Xzxu8G1N8B5s3JLg/edit?tab=t.0",
    ).strip()

    DB_PATH: str = os.getenv("DB_PATH", "tickets.db").strip()
    TRANSCRIPTS_DIR: str = os.getenv("TRANSCRIPTS_DIR", "transcripts").strip()
    AUTO_CLOSE_HOURS: int = _env_int("AUTO_CLOSE_HOURS", 24)
    COMMAND_PREFIXES: list[str] = ["!", "/"]

    # --- МОСТ С СЕРВЕРОМ MINECRAFT ---
    BRIDGE_CHANNEL_ID: int = _env_int("BRIDGE_CHANNEL_ID", 1556015782566297830)
    EVENTS_CHANNEL_ID: int = _env_int("EVENTS_CHANNEL_ID", 1556209087920873542)
    COMMANDS_CHANNEL_ID: int = _env_int("COMMANDS_CHANNEL_ID", 1555483142578770030)
    BRIDGE_PORT: int = _env_int("BRIDGE_PORT", 0) or _env_int("SERVER_PORT", 25549)
    BRIDGE_SECRET: str = os.getenv("BRIDGE_SECRET", "vanillaland_secret_2026").strip()
    ONLINE_VOICE_CHANNEL_ID: int = _env_int("ONLINE_VOICE_CHANNEL_ID", 0)
    TPS_VOICE_CHANNEL_ID: int = _env_int("TPS_VOICE_CHANNEL_ID", 0)
    STATS_CATEGORY_ID: int = _env_int("STATS_CATEGORY_ID", 0)

    # Двухфакторная аутентификация (2FA) и сессии IP
    IP_SESSION_HOURS: float = _env_float("IP_SESSION_HOURS", 48.0)
    LOGIN_2FA_TIMEOUT_SEC: int = _env_int("LOGIN_2FA_TIMEOUT_SEC", 180)
    LINK_PANEL_CHANNEL_ID: int = _env_int("LINK_PANEL_CHANNEL_ID", 0)

    # Модули совместимости моста с серверным ядром (Rahu / Flectone / MineGuard)
    # Если на сервере проверка твинков или техработы ведутся ядром, флаги отключают дублирование
    BRIDGE_ENABLE_ALTS_CHECK: bool = _env_bool("BRIDGE_ENABLE_ALTS_CHECK", False)
    BRIDGE_ENABLE_MAINTENANCE_SYNC: bool = _env_bool("BRIDGE_ENABLE_MAINTENANCE_SYNC", False)
    BRIDGE_ENABLE_STATS_CHANNELS: bool = _env_bool("BRIDGE_ENABLE_STATS_CHANNELS", True)
