"""Безопасная синхронизация .env.

Добавляет только отсутствующие ключи, никогда не перезаписывает существующие
значения и не трогает секреты (DISCORD_TOKEN/BRIDGE_SECRET).
"""

from pathlib import Path
from typing import Iterable, Optional

ENV_FILENAMES = (".env", ".env.txt", "config.env", "bot.env")

# Только несекретные ключи, которые появились в новых версиях.
DEFAULT_KEYS: tuple[tuple[str, str], ...] = (
    ("GUILD_ID", "0"),
    ("ADMIN_ROLE_IDS", ""),
    ("TICKETS_CATEGORY_ID", "0"),
    ("LOG_CHANNEL_ID", "0"),
    ("ADMIN_LOG_CHANNEL_ID", "0"),
    ("ALTS_ALERT_CHANNEL_ID", "0"),
    ("BRIDGE_PORT", "25549"),
    ("AUTO_CLOSE_HOURS", "24"),
    ("DB_PATH", "tickets.db"),
    ("TRANSCRIPTS_DIR", "transcripts"),
    ("BRIDGE_ENABLE_ALTS_CHECK", "0"),
    ("BRIDGE_ENABLE_MAINTENANCE_SYNC", "0"),
    ("BRIDGE_ENABLE_STATS_CHANNELS", "1"),
    ("IP_VOICE_CHANNEL_ID", "0"),
)

SYNC_MARKER = "# --- Автодобавлено при обновлении (значения можно менять) ---"


def find_env_file(base_dir: Optional[Path] = None, cwd: Optional[Path] = None) -> Optional[Path]:
    roots = [Path(base_dir or Path(__file__).resolve().parent), Path(cwd or Path.cwd())]
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        for name in ENV_FILENAMES:
            candidate = root / name
            if candidate.is_file():
                return candidate
    return None


def _existing_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def sync_env_file(path: Optional[Path] = None) -> bool:
    """Добавляет недостающие ключи в .env. Возвращает True, если файл изменён."""
    target = Path(path) if path is not None else find_env_file()
    if target is None or not target.is_file():
        return False

    text = target.read_text(encoding="utf-8")
    existing = _existing_keys(text)
    missing = [(key, value) for key, value in DEFAULT_KEYS if key not in existing]
    if not missing:
        return False

    newline = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith(("\n", "\r")):
        text += newline
    if SYNC_MARKER not in text:
        text += newline + SYNC_MARKER + newline
    for key, value in missing:
        text += f"{key}={value}{newline}"

    import os
    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix=".env_", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise
    return True


def ensure_env_keys(keys: Iterable[tuple[str, str]], path: Optional[Path] = None) -> bool:
    """Точечная синхронизация произвольного набора ключей (для тестов/расширений)."""
    target = Path(path) if path is not None else find_env_file()
    if target is None or not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    existing = _existing_keys(text)
    missing = [(k, v) for k, v in keys if k not in existing]
    if not missing:
        return False
    newline = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith(("\n", "\r")):
        text += newline
    if SYNC_MARKER not in text:
        text += newline + SYNC_MARKER + newline
    for key, value in missing:
        text += f"{key}={value}{newline}"
    import os
    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix=".env_", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise
    return True
