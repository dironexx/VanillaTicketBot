import difflib
import json
import os
import re
import shutil
import sqlite3
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional, Union

MSK = timezone(timedelta(hours=3))

logger = logging.getLogger("VanillaBot.DB")


def get_msk_now() -> datetime:
    return datetime.now(MSK)


def get_msk_now_str() -> str:
    return get_msk_now().strftime("%Y-%m-%d %H:%M:%S")


class DatabaseManager:
    def __init__(self, db_path: str = "tickets.db", transcripts_dir: str = "transcripts"):
        self.db_path = db_path
        self.transcripts_dir = transcripts_dir
        self.counter_file = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "ticket_counter.txt")
        self.init_db()

    def _read_external_counter(self) -> int:
        """Читает значение счётчика из независимого текстового файла (защита от потери при пересоздании БД)."""
        try:
            if os.path.exists(self.counter_file):
                with open(self.counter_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content.isdigit():
                        return int(content)
        except Exception as e:
            logger.debug("Counter file read note: %s", e)
        return 0

    def _write_external_counter(self, val: int) -> None:
        """Атомарно сохраняет счётчик в текстовый файл, защищая от обнуления при аварийном завершении контейнера."""
        try:
            val_int = max(0, int(val))
            tmp_path = f"{self.counter_file}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(str(val_int))
            os.replace(tmp_path, self.counter_file)
        except Exception as e:
            logger.debug("Counter file write note: %s", e)

    def _recover_corrupted_db(self, error: Exception) -> None:
        """
        Safely recovers from SQLite database corruption (e.g. malformed disk image).
        Backs up the corrupted files, attempts recovery from automatic backup or salvaging tables,
        and initializes a consistent database preserving ticket counters and history.
        """
        logger.critical(
            "SQLite database at '%s' is corrupted (%s). Initiating emergency self-healing recovery...",
            self.db_path,
            error,
        )
        timestamp = int(time.time())
        corrupt_backup = f"{self.db_path}.corrupted_{timestamp}"
        for ext in ("", "-wal", "-shm"):
            src = f"{self.db_path}{ext}"
            dst = f"{corrupt_backup}{ext}"
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                    logger.warning("Moved corrupted file '%s' -> '%s'", src, dst)
                except Exception as exc:
                    logger.error("Failed to move '%s': %s. Attempting removal...", src, exc)
                    try:
                        os.remove(src)
                    except Exception as rm_err:
                        logger.debug("Failed to remove corrupted file '%s': %s", src, rm_err)

        backup_file = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backups", "tickets_auto_backup.db")
        restored = False
        if os.path.exists(backup_file):
            try:
                import shutil
                shutil.copy2(backup_file, self.db_path)
                logger.info("Успешно восстановлена база данных из автоматического бэкапа: %s", backup_file)
                restored = True
            except Exception as bck_err:
                logger.warning("Не удалось восстановить базу из бэкапа %s: %s", backup_file, bck_err)

        if not restored:
            logger.info("Corrupted database isolated. Clean database will be initialized.")

        try:
            self.salvage_corrupted_file(corrupt_backup)
        except Exception as salv_err:
            logger.debug("Corrupted file salvage note: %s", salv_err)

    def _is_corrupt_error(self, error: Exception) -> bool:
        msg = str(error).lower()
        return any(
            k in msg
            for k in (
                "malformed",
                "not a database",
                "disk image is malformed",
                "file is encrypted or is not a database",
                "database disk image is malformed",
            )
        )

    def _open_connection(self) -> sqlite3.Connection:
        max_retries = 3
        for attempt in range(max_retries):
            conn = None
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA busy_timeout=30000;")
                return conn
            except sqlite3.DatabaseError as err:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception as cl_err:
                        logger.debug("Failed to close sqlite connection on error: %s", cl_err)
                if self._is_corrupt_error(err):
                    self._recover_corrupted_db(err)
                    conn = sqlite3.connect(self.db_path, timeout=30.0)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("PRAGMA synchronous=NORMAL;")
                    conn.execute("PRAGMA busy_timeout=30000;")
                    self._create_tables(conn)
                    return conn
                if attempt < max_retries - 1:
                    continue
                raise err

    @contextmanager
    def _get_connection(self):
        conn = self._open_connection()
        try:
            with conn:
                yield conn
        finally:
            try:
                conn.close()
            except Exception as cl_err:
                logger.debug("Failed to close sqlite context connection: %s", cl_err)

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_tickets (
                dc_channel_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ticket_num INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_history (
                ticket_num INTEGER PRIMARY KEY,
                dc_channel_id INTEGER,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                closed_at TEXT,
                closed_by TEXT,
                close_reason TEXT,
                transcript_file TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_hist_user ON ticket_history(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_hist_channel ON ticket_history(dc_channel_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticket_hist_status ON ticket_history(status);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_member_events (
                event_key TEXT PRIMARY KEY,
                processed_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_counter (
                id INTEGER PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_mutes (
                user_id INTEGER,
                guild_id INTEGER,
                unmute_timestamp REAL,
                reason TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_by TEXT,
                banned_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_vc_bans (
                user_id INTEGER,
                guild_id INTEGER,
                unmute_timestamp REAL,
                reason TEXT,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id INTEGER,
                remind_timestamp REAL,
                text TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locked_channels (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_deaths (
                player_name TEXT PRIMARY KEY,
                death_count INTEGER NOT NULL DEFAULT 1,
                last_death_reason TEXT,
                last_death_time TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_death_coords (
                player_name TEXT PRIMARY KEY,
                world TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                reason TEXT,
                time TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS top_seasons (
                season INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                archived_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_auto_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_phrase TEXT NOT NULL,
                response_text TEXT NOT NULL,
                threshold REAL NOT NULL DEFAULT 0.68,
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_ips (
                player_name TEXT NOT NULL,
                ip TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (player_name, ip)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_skins (
                player_name TEXT PRIMARY KEY,
                skin_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linked_accounts (
                player_name TEXT PRIMARY KEY COLLATE NOCASE,
                player_uuid TEXT,
                discord_user_id INTEGER NOT NULL UNIQUE,
                two_factor_enabled INTEGER NOT NULL DEFAULT 1,
                linked_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_linked_player_nocase ON linked_accounts(player_name COLLATE NOCASE);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trusted_ip_sessions (
                player_name TEXT NOT NULL,
                ip TEXT NOT NULL,
                verified_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY (player_name, ip)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_link_codes (
                code TEXT PRIMARY KEY,
                player_name TEXT,
                discord_user_id INTEGER,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                player TEXT NOT NULL,
                ip TEXT NOT NULL,
                incident_type TEXT NOT NULL,
                details TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_whitelist (
                target TEXT PRIMARY KEY,
                target_type TEXT NOT NULL,
                reason TEXT DEFAULT '',
                added_by TEXT DEFAULT '',
                added_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                ip TEXT NOT NULL,
                login_time REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_alerts (
                message_id INTEGER PRIMARY KEY,
                player TEXT NOT NULL,
                banned_nick TEXT,
                banned_reason TEXT,
                ip TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dm_reply_targets (
                message_id INTEGER PRIMARY KEY,
                target_player TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS offline_mail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL COLLATE NOCASE,
                message TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_recipient ON offline_mail(recipient COLLATE NOCASE, is_read);")
        conn.execute("INSERT OR IGNORE INTO ticket_counter (id, count) VALUES (1, 0)")
        conn.commit()

        # Автоматическая синхронизация и защита счётчика тикетов (файл + БД + история)
        try:
            cursor = conn.cursor()
            file_cnt = self._read_external_counter()
            cursor.execute("SELECT count FROM ticket_counter WHERE id = 1")
            r = cursor.fetchone()
            db_cnt = int(r[0]) if r and r[0] is not None else 0
            cursor.execute("SELECT COALESCE(MAX(ticket_num), 0) FROM ticket_history")
            hist_max = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COALESCE(MAX(ticket_num), 0) FROM active_tickets")
            act_max = int(cursor.fetchone()[0] or 0)
            # Синхронизация максимума из файла, БД и истории обращений
            target_count = max(file_cnt, db_cnt, hist_max, act_max)
            cursor.execute("UPDATE ticket_counter SET count = ? WHERE id = 1", (target_count,))
            conn.commit()
            if target_count > 0:
                self._write_external_counter(target_count)
            logger.info("Счётчик тикетов инициализирован со значением: %d", target_count)
        except Exception as sync_err:
            logger.debug("Ticket counter init note: %s", sync_err)

        # Автоматическая миграция active_vc_bans для существующих баз данных
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(active_vc_bans)")
            vc_cols = {row[1] for row in cursor.fetchall()}
            if vc_cols:
                if "unmute_timestamp" not in vc_cols:
                    conn.execute("ALTER TABLE active_vc_bans ADD COLUMN unmute_timestamp REAL")
                    if "unban_timestamp" in vc_cols:
                        conn.execute("UPDATE active_vc_bans SET unmute_timestamp = unban_timestamp")
                if "unban_timestamp" not in vc_cols:
                    conn.execute("ALTER TABLE active_vc_bans ADD COLUMN unban_timestamp REAL")
                    if "unmute_timestamp" in vc_cols:
                        conn.execute("UPDATE active_vc_bans SET unban_timestamp = unmute_timestamp")
            conn.commit()
        except Exception as mig_err:
            logging.getLogger('VanillaBot.DB').debug('Auto-migration active_vc_bans note: %s', mig_err)

        # Автоматическая миграция linked_accounts (настройки срока доверия IP и пуш-алертов)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(linked_accounts)")
            la_cols = {row[1] for row in cursor.fetchall()}
            if la_cols:
                if "trust_duration_hours" not in la_cols:
                    conn.execute("ALTER TABLE linked_accounts ADD COLUMN trust_duration_hours INTEGER NOT NULL DEFAULT 48")
                if "login_alerts_enabled" not in la_cols:
                    conn.execute("ALTER TABLE linked_accounts ADD COLUMN login_alerts_enabled INTEGER NOT NULL DEFAULT 1")
                # Только NULL (старые строки после ALTER). Явно выключенные алерты (=0) не трогаем.
                conn.execute("UPDATE linked_accounts SET login_alerts_enabled = 1 WHERE login_alerts_enabled IS NULL")
            conn.commit()
        except Exception as mig_err:
            logging.getLogger('VanillaBot.DB').debug('Auto-migration linked_accounts note: %s', mig_err)

        # Автоматическая миграция active_tickets (добавление колонки ticket_num для связки с историей)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(active_tickets)")
            at_cols = {row[1] for row in cursor.fetchall()}
            if at_cols and "ticket_num" not in at_cols:
                conn.execute("ALTER TABLE active_tickets ADD COLUMN ticket_num INTEGER")
            conn.commit()
        except Exception as mig_err:
            logging.getLogger('VanillaBot.DB').debug('Auto-migration active_tickets note: %s', mig_err)

    async def execute_async(self, func, *args, **kwargs):
        """
        Гарантированно выполняет дисковые операции с SQLite в отдельном пуле потоков,
        полностью исключая заморозку Event Loop Discord-бота.
        """
        import asyncio
        return await asyncio.to_thread(func, *args, **kwargs)

    def init_db(self):
        os.makedirs(self.transcripts_dir, exist_ok=True)
        with self._get_connection() as conn:
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
            self._create_tables(conn)

    # --- ДЕДУПЛИКАЦИЯ СОБЫТИЙ УЧАСТНИКОВ (ЗАЩИТА ОТ ДВОЙНЫХ ЛОГОВ) ---
    def claim_member_event(self, member_id: int, event_type: str = "join", window_sec: float = 30.0) -> bool:
        """
        Гарантирует, что событие участника (вход/выход) обрабатывается только ОДИН раз за окно window_sec.
        Предотвращает дублирование сообщений даже при параллельных инстансах бота или повторных событиях шлюза.
        """
        now = time.time()
        event_key = f"{member_id}:{event_type}"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
            except Exception:
                pass
            cursor.execute("SELECT processed_at FROM processed_member_events WHERE event_key = ?", (event_key,))
            row = cursor.fetchone()
            if row:
                last_time = float(row[0])
                if (now - last_time) < window_sec:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    return False  # Дубль, событие уже обработано недавно

            cursor.execute(
                "INSERT INTO processed_member_events (event_key, processed_at) VALUES (?, ?) "
                "ON CONFLICT(event_key) DO UPDATE SET processed_at = excluded.processed_at",
                (event_key, now)
            )
            # Очистка старых событий раз в ~5 минут
            if int(now) % 300 < 5:
                cursor.execute("DELETE FROM processed_member_events WHERE processed_at < ?", (now - 3600.0,))
            conn.commit()
            return True

    # --- ТИКЕТЫ ---
    def get_next_ticket_number(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Авто-синхронизация счётчика: count никогда не должен быть меньше максимального номера в истории или внешнем файле
            try:
                cursor.execute("SELECT COALESCE(MAX(ticket_num), 0) FROM ticket_history")
                max_hist = cursor.fetchone()[0] or 0
                cursor.execute("SELECT COALESCE(MAX(ticket_num), 0) FROM active_tickets")
                max_act = cursor.fetchone()[0] or 0
                file_cnt = self._read_external_counter()

                cursor.execute("SELECT count FROM ticket_counter WHERE id = 1")
                row = cursor.fetchone()
                current_count = int(row[0]) if row else 0

                max_known = max(int(max_hist), int(max_act), file_cnt, current_count)
                if current_count < max_known:
                    cursor.execute("UPDATE ticket_counter SET count = ? WHERE id = 1", (max_known,))
            except Exception as sync_err:
                logger.debug("Counter sync note: %s", sync_err)

            # 2. Инкремент с атомарным получением номера
            try:
                cursor.execute("UPDATE ticket_counter SET count = count + 1 WHERE id = 1 RETURNING count")
                row = cursor.fetchone()
                if row:
                    new_count = int(row[0])
                    conn.commit()
                    self._write_external_counter(new_count)
                    return new_count
            except (sqlite3.OperationalError, Exception) as ret_err:
                logger.debug("RETURNING clause not available, using fallback transaction: %s", ret_err)
                try:
                    conn.rollback()
                except Exception:
                    pass

            try:
                cursor.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                pass
            cursor.execute("UPDATE ticket_counter SET count = count + 1 WHERE id = 1")
            cursor.execute("SELECT count FROM ticket_counter WHERE id = 1")
            row = cursor.fetchone()
            new_count = int(row[0]) if row else 1
            conn.commit()
            self._write_external_counter(new_count)
            return new_count

    def ensure_ticket_counter_at_least(self, min_val: int) -> None:
        """Гарантирует, что счётчик тикетов не меньше min_val (например, полученного из существующих каналов Discord)."""
        if min_val <= 0:
            return
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count FROM ticket_counter WHERE id = 1")
            row = cursor.fetchone()
            current = int(row[0]) if row else 0
            if current < min_val:
                cursor.execute("UPDATE ticket_counter SET count = ? WHERE id = 1", (min_val,))
                conn.commit()
                self._write_external_counter(min_val)
                logger.info("Счётчик тикетов обновлён с %d до %d на основе существующих данных.", current, min_val)

    def set_ticket_counter(self, new_val: int) -> int:
        """Принудительно выставляет счетчик тикетов в заданное число (команда администратора)."""
        val = max(1, int(new_val))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE ticket_counter SET count = ? WHERE id = 1", (val,))
            conn.commit()
        self._write_external_counter(val)
        logger.info("Счётчик тикетов вручную установлен на: %d", val)
        return val
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count FROM ticket_counter WHERE id = 1")
            row = cursor.fetchone()
            current = int(row[0]) if row else 0
            if current < min_val:
                cursor.execute("UPDATE ticket_counter SET count = ? WHERE id = 1", (min_val,))
                conn.commit()
                logger.info("Счётчик тикетов обновлён с %d до %d на основе существующих данных.", current, min_val)

    def save_ticket(self, dc_channel_id: int, user_id: int, user_name: str, ticket_num: Optional[int] = None):
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            cur = conn.cursor()
            if ticket_num is None:
                cur.execute("SELECT ticket_num FROM active_tickets WHERE dc_channel_id = ?", (dc_channel_id,))
                row = cur.fetchone()
                if row and row[0]:
                    ticket_num = int(row[0])
                else:
                    cur.execute("SELECT count FROM ticket_counter WHERE id = 1")
                    row = cur.fetchone()
                    ticket_num = int(row[0]) if row and row[0] else None

            conn.execute(
                "INSERT OR REPLACE INTO active_tickets (dc_channel_id, user_id, user_name, last_activity, created_at, ticket_num) VALUES (?, ?, ?, ?, ?, ?)",
                (dc_channel_id, user_id, user_name, now_str, now_str, ticket_num)
            )
            if ticket_num:
                conn.execute(
                    """
                    INSERT INTO ticket_history (ticket_num, dc_channel_id, user_id, user_name, status, created_at)
                    VALUES (?, ?, ?, ?, 'open', ?)
                    ON CONFLICT(ticket_num) DO UPDATE SET
                        dc_channel_id=excluded.dc_channel_id,
                        user_id=excluded.user_id,
                        user_name=excluded.user_name,
                        status='open'
                    """,
                    (ticket_num, dc_channel_id, user_id, user_name, now_str)
                )
            conn.commit()

    def update_ticket_activity(self, dc_channel_id: int):
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            conn.execute("UPDATE active_tickets SET last_activity = ? WHERE dc_channel_id = ?", (now_str, dc_channel_id))
            conn.commit()

    def get_all_active_tickets(self) -> list[tuple]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT dc_channel_id, user_id, user_name, last_activity, created_at FROM active_tickets")
            return cursor.fetchall()

    def get_ticket_user_id(self, dc_channel_id: int) -> Optional[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM active_tickets WHERE dc_channel_id = ?", (dc_channel_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def is_ticket_channel(self, channel_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM active_tickets WHERE dc_channel_id = ?", (channel_id,))
            return cursor.fetchone() is not None

    def user_has_open_ticket(self, user_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM active_tickets WHERE user_id = ?", (user_id,))
            return cursor.fetchone() is not None

    def close_ticket(
        self,
        channel_id: int,
        closed_by: str = "Персонал",
        reason: str = "Вопрос решен",
        transcript_file: Optional[str] = None,
    ) -> None:
        """Закрывает тикет, навсегда сохраняя полную историю в ticket_history перед удалением из active_tickets."""
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT ticket_num, user_id, user_name, created_at FROM active_tickets WHERE dc_channel_id = ?", (channel_id,))
            row = cur.fetchone()
            if row:
                t_num, u_id, u_name, c_at = row
                if t_num:
                    conn.execute(
                        """
                        INSERT INTO ticket_history (ticket_num, dc_channel_id, user_id, user_name, status, created_at, closed_at, closed_by, close_reason, transcript_file)
                        VALUES (?, ?, ?, ?, 'closed', ?, ?, ?, ?, ?)
                        ON CONFLICT(ticket_num) DO UPDATE SET
                            status='closed',
                            closed_at=excluded.closed_at,
                            closed_by=excluded.closed_by,
                            close_reason=excluded.close_reason,
                            transcript_file=COALESCE(excluded.transcript_file, ticket_history.transcript_file)
                        """,
                        (t_num, channel_id, u_id, u_name, c_at or now_str, now_str, closed_by, reason, transcript_file)
                    )
            else:
                conn.execute(
                    """
                    UPDATE ticket_history
                    SET status='closed', closed_at=?, closed_by=?, close_reason=?, transcript_file=COALESCE(?, transcript_file)
                    WHERE dc_channel_id=? AND status='open'
                    """,
                    (now_str, closed_by, reason, transcript_file, channel_id)
                )
            conn.execute("DELETE FROM active_tickets WHERE dc_channel_id = ?", (channel_id,))
            conn.commit()

    def delete_ticket(self, channel_id: int):
        with self._get_connection() as conn:
            now_str = get_msk_now_str()
            conn.execute(
                "UPDATE ticket_history SET status='closed', closed_at=COALESCE(closed_at, ?) WHERE dc_channel_id = ? AND status='open'",
                (now_str, channel_id)
            )
            conn.execute("DELETE FROM active_tickets WHERE dc_channel_id = ?", (channel_id,))
            conn.commit()

    def get_ticket_history(self, limit: int = 50, user_id: Optional[int] = None) -> list[dict]:
        """Возвращает историю тикетов (номер, пользователь, статус, даты, кто закрыл, причина)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute(
                    "SELECT ticket_num, dc_channel_id, user_id, user_name, status, created_at, closed_at, closed_by, close_reason, transcript_file "
                    "FROM ticket_history WHERE user_id = ? ORDER BY ticket_num DESC LIMIT ?",
                    (user_id, limit)
                )
            else:
                cursor.execute(
                    "SELECT ticket_num, dc_channel_id, user_id, user_name, status, created_at, closed_at, closed_by, close_reason, transcript_file "
                    "FROM ticket_history ORDER BY ticket_num DESC LIMIT ?",
                    (limit,)
                )
            cols = ["ticket_num", "dc_channel_id", "user_id", "user_name", "status", "created_at", "closed_at", "closed_by", "close_reason", "transcript_file"]
            return [dict(zip(cols, r)) for r in cursor.fetchall()]

    # --- ЧЕРНЫЙ СПИСОК ТИКЕТОВ ---
    def add_ticket_blacklist(self, user_id: int, reason: str, banned_by: str):
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO ticket_blacklist VALUES (?, ?, ?, ?)", (user_id, reason, banned_by, now_str))
            conn.commit()

    def remove_ticket_blacklist(self, user_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM ticket_blacklist WHERE user_id = ?", (user_id,))
            conn.commit()

    def is_ticket_blacklisted(self, user_id: int) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT reason FROM ticket_blacklist WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    # --- ТЕКСТОВЫЕ МУТЫ ---
    def save_mute(self, user_id: int, guild_id: int, unmute_timestamp: float, reason: str):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO active_mutes VALUES (?, ?, ?, ?)", (user_id, guild_id, unmute_timestamp, reason))
            conn.commit()

    def delete_mute(self, user_id: int, guild_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM active_mutes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            conn.commit()

    def get_expired_mutes(self, current_timestamp: float) -> list[tuple[int, int, str]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, guild_id, reason FROM active_mutes WHERE unmute_timestamp <= ?", (current_timestamp,))
            return cursor.fetchall()

    def is_user_muted(self, user_id: int, guild_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM active_mutes WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            return cursor.fetchone() is not None

    # --- ГОЛОСОВЫЕ БАНЫ (VC BAN) ---
    def save_vc_ban(self, user_id: int, guild_id: int, unban_timestamp: float, reason: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(active_vc_bans)")
            cols = {row[1] for row in cursor.fetchall()}
            if "unmute_timestamp" in cols and "unban_timestamp" in cols:
                conn.execute(
                    "INSERT OR REPLACE INTO active_vc_bans (user_id, guild_id, unmute_timestamp, unban_timestamp, reason) VALUES (?, ?, ?, ?, ?)",
                    (user_id, guild_id, unban_timestamp, unban_timestamp, reason),
                )
            elif "unmute_timestamp" in cols:
                conn.execute(
                    "INSERT OR REPLACE INTO active_vc_bans (user_id, guild_id, unmute_timestamp, reason) VALUES (?, ?, ?, ?)",
                    (user_id, guild_id, unban_timestamp, reason),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO active_vc_bans (user_id, guild_id, unban_timestamp, reason) VALUES (?, ?, ?, ?)",
                    (user_id, guild_id, unban_timestamp, reason),
                )
            conn.commit()

    def delete_vc_ban(self, user_id: int, guild_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM active_vc_bans WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            conn.commit()

    def get_expired_vc_bans(self, current_timestamp: float) -> list[tuple[int, int, str]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT user_id, guild_id, reason FROM active_vc_bans WHERE COALESCE(unmute_timestamp, unban_timestamp) <= ?",
                    (current_timestamp,),
                )
                return cursor.fetchall()
            except Exception:
                return []

    def is_user_vc_banned(self, user_id: int, guild_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM active_vc_bans WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            return cursor.fetchone() is not None

    # --- НАПОМИНАНИЯ (REMIND) ---
    def save_reminder(self, user_id: int, channel_id: int, remind_timestamp: float, text: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO reminders (user_id, channel_id, remind_timestamp, text) VALUES (?, ?, ?, ?)", (user_id, channel_id, remind_timestamp, text))
            conn.commit()
            return cursor.lastrowid

    def get_expired_reminders(self, current_timestamp: float) -> list[tuple[int, int, int, str]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, channel_id, text FROM reminders WHERE remind_timestamp <= ?", (current_timestamp,))
            return cursor.fetchall()

    def delete_reminder(self, reminder_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()

    # --- ЗАБЛОКИРОВАННЫЕ КАНАЛЫ (ДЛЯ ТОЧНОГО UNLOCKALL) ---
    def save_locked_channel(self, channel_id: int, guild_id: int):
        with self._get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO locked_channels VALUES (?, ?)", (channel_id, guild_id))
            conn.commit()

    def get_locked_channels(self, guild_id: int) -> list[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id FROM locked_channels WHERE guild_id = ?", (guild_id,))
            return [row[0] for row in cursor.fetchall()]

    def clear_locked_channels(self, guild_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM locked_channels WHERE guild_id = ?", (guild_id,))
            conn.commit()

    # --- ДИНАМИЧЕСКИЕ НАСТРОЙКИ (БОТ) ---
    def set_setting(self, key: str, value: str):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    # --- СТАТИСТИКА СМЕРТЕЙ (ПРЕМИЯ ДАРВИНА) ---
    def record_player_death(self, player_name: str, reason: str):
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO player_deaths (player_name, death_count, last_death_reason, last_death_time)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(player_name) DO UPDATE SET
                    death_count = death_count + 1,
                    last_death_reason = excluded.last_death_reason,
                    last_death_time = excluded.last_death_time
            """, (player_name, reason, now_str))
            conn.commit()

    def get_top_deaths(self, limit: int = 10) -> list[tuple[str, int, str]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, death_count, last_death_reason
                FROM player_deaths
                ORDER BY death_count DESC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()

    def get_player_deaths(self, player_name: str) -> tuple[int, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT death_count, last_death_reason
                FROM player_deaths
                WHERE LOWER(player_name) = LOWER(?)
            """, (player_name.strip(),))
            row = cursor.fetchone()
            if row:
                return (row[0], row[1] or "Неизвестно")
            return (0, "Нет смертей")

    def reset_top_deaths(self) -> int:
        """Сбрасывает статистику смертей игроков."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM player_deaths")
            try:
                cursor.execute("DELETE FROM player_death_coords")
            except Exception:
                pass
            conn.commit()
            logger.info("Таблица смертей игроков успешно очищена.")
            return 1

    # --- СЕЗОНЫ И АРХИВ ЛИДЕРБОРДА ---
    def get_active_season(self) -> int:
        raw = self.get_setting("active_top_season", "4")
        try:
            return max(1, int(str(raw).strip()))
        except (TypeError, ValueError):
            return 4

    def set_active_season(self, season: int) -> None:
        self.set_setting("active_top_season", str(max(1, int(season))))

    def save_season_leaderboard(self, season: int, name: str, data: dict) -> None:
        now_str = get_msk_now_str()
        clean_data = {
            "playtime": list(data.get("playtime", [])),
            "diamonds": list(data.get("diamonds", [])),
            "debris": list(data.get("debris", [])),
            "kills": list(data.get("kills", [])),
            "deaths": list(data.get("deaths", [])),
        }
        payload_json = json.dumps(clean_data, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO top_seasons (season, name, data_json, archived_at)
                VALUES (?, ?, ?, ?)
                """,
                (int(season), str(name), payload_json, now_str),
            )
            conn.commit()

    def get_season_leaderboard(self, season: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT season, name, data_json, archived_at FROM top_seasons WHERE season = ?",
                (int(season),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            try:
                parsed = json.loads(row[2]) if row[2] else {}
            except Exception:
                parsed = {}
            return {
                "season": row[0],
                "name": row[1],
                "data": parsed,
                "archived_at": row[3],
            }

    def list_seasons(self) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT season, name, archived_at FROM top_seasons ORDER BY season DESC")
            return [
                {"season": row[0], "name": row[1], "archived_at": row[2]}
                for row in cursor.fetchall()
            ]

    def merge_season_mc_data(self, season: int, name: str, mc_data: dict) -> dict:
        """Объединяет статистику из Minecraft с архивом сезона (не затирая сохранённые категории)."""
        existing = self.get_season_leaderboard(season)
        base = dict(existing["data"]) if existing and isinstance(existing.get("data"), dict) else {}
        for key in ("playtime", "diamonds", "debris", "kills"):
            if mc_data.get(key):
                base[key] = list(mc_data[key])
            else:
                base.setdefault(key, [])
        if mc_data.get("deaths") and not base.get("deaths"):
            base["deaths"] = list(mc_data["deaths"])
        else:
            base.setdefault("deaths", [])
        self.save_season_leaderboard(season, name, base)
        return base

    def archive_deaths_to_season3(self) -> int:
        """
        Переносит накопленные смерти из player_deaths в архив 3 сезона,
        полностью исключая записи за период 2026-11-21 .. 2026-11-24.
        """
        excluded_dates = ("2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT player_name, death_count, last_death_time FROM player_deaths ORDER BY death_count DESC"
            )
            rows = cursor.fetchall()

        filtered_deaths = []
        for p_name, count, last_time in rows:
            date_prefix = str(last_time or "").strip()[:10]
            if date_prefix in excluded_dates:
                continue
            filtered_deaths.append({"player": p_name, "value": int(count or 0), "skin": ""})

        existing = self.get_season_leaderboard(3)
        base = dict(existing["data"]) if existing and isinstance(existing.get("data"), dict) else {}
        if filtered_deaths or "deaths" not in base:
            base["deaths"] = filtered_deaths[:10]
        for key in ("playtime", "diamonds", "debris", "kills"):
            base.setdefault(key, [])
        self.save_season_leaderboard(3, "3 сезон", base)
        return len(filtered_deaths)

    # --- УМНЫЕ АВТООТВЕТЫ В ТИКЕТАХ (FUZZY / ПОХОЖИЕ ФРАЗЫ) ---
    @staticmethod
    def _normalize_reply_text(text: str) -> str:
        low = str(text or "").lower().replace("ё", "е")
        low = re.sub(r"[^\w\s]", " ", low, flags=re.UNICODE)
        return re.sub(r"\s+", " ", low).strip()

    def add_ticket_auto_reply(
        self,
        trigger_phrase: str,
        response_text: str,
        threshold: float = 0.68,
        created_by: str = "",
    ) -> int:
        now_str = get_msk_now_str()
        thr = max(0.45, min(0.98, float(threshold)))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ticket_auto_replies (trigger_phrase, response_text, threshold, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (trigger_phrase.strip(), response_text.strip(), thr, str(created_by or ""), now_str),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_ticket_auto_replies(self) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, trigger_phrase, response_text, threshold, created_by, created_at FROM ticket_auto_replies ORDER BY id ASC"
            )
            return [
                {
                    "id": row[0],
                    "trigger_phrase": row[1],
                    "response_text": row[2],
                    "threshold": float(row[3] if row[3] is not None else 0.68),
                    "created_by": row[4] or "",
                    "created_at": row[5] or "",
                }
                for row in cursor.fetchall()
            ]

    def delete_ticket_auto_reply(self, rule_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ticket_auto_replies WHERE id = ?", (int(rule_id),))
            conn.commit()
            return cursor.rowcount > 0

    def find_matching_auto_reply(self, message_text: str) -> Optional[dict]:
        """Ищет наиболее подходящий шаблон автоответа с учётом точных и похожих фраз."""
        msg_norm = self._normalize_reply_text(message_text)
        if len(msg_norm) < 2:
            return None
        msg_words = msg_norm.split()
        rules = self.get_ticket_auto_replies()
        if not rules:
            return None

        best_match: Optional[dict] = None
        best_score = 0.0

        for rule in rules:
            variants = [v.strip() for v in re.split(r"[|;]", rule["trigger_phrase"]) if v.strip()]
            rule_thr = float(rule.get("threshold", 0.68))
            for variant in variants:
                v_norm = self._normalize_reply_text(variant)
                if not v_norm:
                    continue
                v_words = v_norm.split()

                score = 0.0
                if v_norm in msg_norm:
                    score = 1.0
                else:
                    # Проверка по ключевым словам с нечётким сравнением отдельных слов
                    sig_words = [w for w in v_words if len(w) >= 2] or v_words
                    matched_words = 0
                    for tw in sig_words:
                        if any(tw == mw or difflib.SequenceMatcher(None, tw, mw).ratio() >= 0.78 for mw in msg_words):
                            matched_words += 1
                    token_ratio = matched_words / max(1, len(sig_words))
                    if token_ratio >= 0.8:
                        score = max(score, 0.85 * token_ratio + 0.1)

                    # Полное сравнение и скользящее окно по n-граммам сообщения
                    full_ratio = difflib.SequenceMatcher(None, v_norm, msg_norm).ratio()
                    score = max(score, full_ratio)

                    w_len = len(v_words)
                    if len(msg_words) >= w_len and w_len > 0:
                        min_win = max(1, w_len - 1)
                        max_win = min(len(msg_words), w_len + 1)
                        for win in range(min_win, max_win + 1):
                            for start in range(0, len(msg_words) - win + 1):
                                sub = " ".join(msg_words[start : start + win])
                                sub_ratio = difflib.SequenceMatcher(None, v_norm, sub).ratio()
                                if sub_ratio > score:
                                    score = sub_ratio

                if score >= rule_thr and score > best_score:
                    best_score = score
                    best_match = {
                        "rule": rule,
                        "score": round(score, 3),
                        "matched_variant": variant,
                    }

        return best_match

    def is_automod_enabled(self) -> bool:
        val = self.get_setting("automod_enabled", "true")
        return str(val).lower() in ("true", "1", "yes", "on")

    def set_automod_enabled(self, enabled: bool):
        self.set_setting("automod_enabled", "true" if enabled else "false")

    def record_death_coords(self, player_name: str, world: str, x: int, y: int, z: int, reason: str):
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO player_death_coords (player_name, world, x, y, z, reason, time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (player_name.strip(), world, x, y, z, reason, now_str))
            conn.commit()

    def get_death_coords(self, player_name: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT world, x, y, z, reason, time
                FROM player_death_coords
                WHERE LOWER(player_name) = LOWER(?)
            """, (player_name.strip(),))
            row = cursor.fetchone()
            if row:
                return {
                    "world": row[0],
                    "x": row[1],
                    "y": row[2],
                    "z": row[3],
                    "reason": row[4],
                    "time": row[5]
                }
            return None

    # --- IP ТРЕКИНГ И ПОИСК АЛЬТ-АККАУНТОВ / ТВИНКОВ (!alts) ---
    def _normalize_ip(self, ip: str) -> str:
        if not ip:
            return ""
        clean = str(ip).strip().lstrip("/")
        if ":" in clean and clean.count(":") == 1:
            clean = clean.split(":")[0].strip()
        return clean

    def record_player_ip(self, player_name: str, ip: str):
        if not player_name or not ip:
            return
        clean_ip = self._normalize_ip(ip)
        if clean_ip.lower() in ("127.0.0.1", "0.0.0.0", "n/a", "localhost", "::1", "unknown", "none", ""):
            return
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO player_ips (player_name, ip, last_seen)
                VALUES (?, ?, ?)
            """, (player_name.strip(), clean_ip, now_str))
            conn.commit()

    def get_player_ips(self, player_name: str, limit: int = 25) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ip, last_seen
                FROM player_ips
                WHERE LOWER(player_name) = LOWER(?)
                ORDER BY last_seen DESC
                LIMIT ?
            """, (player_name.strip(), limit))
            return [{"ip": row[0], "last_seen": row[1]} for row in cursor.fetchall()]

    def get_alts_by_ip(self, ip: str) -> list[dict]:
        clean_ip = self._normalize_ip(ip)
        if clean_ip.lower() in ("127.0.0.1", "0.0.0.0", "localhost", "::1", "unknown", "n/a", "none", ""):
            return []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, last_seen
                FROM player_ips
                WHERE ip = ?
                ORDER BY last_seen DESC
            """, (clean_ip,))
            return [{"player_name": row[0], "last_seen": row[1]} for row in cursor.fetchall()]

    def get_alts_by_subnet(self, ip: str, exclude_player: str = "", limit: int = 200) -> list[dict]:
        clean_ip = self._normalize_ip(ip)
        if not clean_ip or clean_ip.lower() in ("127.0.0.1", "0.0.0.0", "localhost", "::1", "unknown", "none", "n/a", ""):
            return []
        parts = clean_ip.split(".")
        if len(parts) != 4 or not all(p.isdigit() for p in parts):
            return []
        subnet_prefix = f"{parts[0]}.{parts[1]}.{parts[2]}.%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT player_name, ip, last_seen
                FROM player_ips
                WHERE ip LIKE ? AND LOWER(player_name) != LOWER(?)
                ORDER BY last_seen DESC
                LIMIT ?
            """, (subnet_prefix, exclude_player.strip(), limit))
            return [
                {"player_name": row[0], "ip": row[1], "last_seen": row[2]}
                for row in cursor.fetchall()
            ]

    def get_player_alts(self, player_name: str, current_ip: str = "") -> dict:
        player_clean = player_name.strip()
        clean_cur_ip = self._normalize_ip(current_ip)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT ip, last_seen
                FROM player_ips
                WHERE LOWER(player_name) = LOWER(?)
                ORDER BY last_seen DESC
            """, (player_clean,))
            ip_rows = cursor.fetchall()
            known_ips = [
                r[0] for r in ip_rows
                if r[0].lower() not in ("127.0.0.1", "0.0.0.0", "localhost", "::1", "unknown", "n/a", "none", "")
            ]

            if clean_cur_ip and clean_cur_ip.lower() not in ("127.0.0.1", "0.0.0.0", "localhost", "::1", "unknown", "n/a", "none", ""):
                if clean_cur_ip not in known_ips:
                    known_ips.append(clean_cur_ip)

            if not known_ips:
                return {
                    "player": player_clean,
                    "ips": [],
                    "current_ip": clean_cur_ip,
                    "alts": [],
                }

            # Ограничение до 200 IP для защиты от превышения лимита переменных SQLite
            safe_ips = known_ips[:200]
            placeholders = ",".join(["?"] * len(safe_ips))
            cursor.execute(f"""
                SELECT player_name, ip, last_seen
                FROM player_ips
                WHERE ip IN ({placeholders})
                ORDER BY last_seen DESC
            """, safe_ips)

            alt_map: dict[str, dict] = {}
            for p_name, ip, last_seen in cursor.fetchall():
                if p_name.lower() == player_clean.lower():
                    continue
                k = p_name.lower()
                if k not in alt_map:
                    alt_map[k] = {
                        "player_name": p_name,
                        "shared_ips": set(),
                        "last_seen": last_seen,
                    }
                alt_map[k]["shared_ips"].add(ip)
                if last_seen > alt_map[k]["last_seen"]:
                    alt_map[k]["last_seen"] = last_seen

            alts = [
                {
                    "player_name": v["player_name"],
                    "shared_ips": sorted(list(v["shared_ips"])),
                    "last_seen": v["last_seen"],
                }
                for v in alt_map.values()
            ]
            alts.sort(key=lambda x: x["last_seen"], reverse=True)

            return {
                "player": player_clean,
                "ips": known_ips,
                "current_ip": clean_cur_ip or (known_ips[0] if known_ips else ""),
                "alts": alts,
            }

    # --- КЭШ ХЕШЕЙ ТЕКСТУР СКИHОВ (ДЛЯ ОТОБРАЖЕНИЯ БЕЗ СТИВА) ---
    def record_player_skin(self, player_name: str, skin_hash: str):
        if not player_name or not skin_hash:
            return
        clean_hash = skin_hash.split("/")[-1].split(".")[0].strip()
        if not clean_hash:
            return
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO player_skins (player_name, skin_hash, updated_at)
                VALUES (?, ?, ?)
            """, (player_name.strip(), clean_hash, now_str))
            conn.commit()

    def get_player_skin(self, player_name: str) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT skin_hash
                FROM player_skins
                WHERE LOWER(player_name) = LOWER(?)
            """, (player_name.strip(),))
            row = cursor.fetchone()
            return row[0] if row else None

    # --- ПРИВЯЗКА АККАУНТОВ MINECRAFT <-> DISCORD ---
    def link_account(
        self,
        player_name: str,
        player_uuid: str,
        discord_user_id: int,
        two_factor: int = 1,
    ) -> bool:
        """Связывает Minecraft аккаунт с пользователем Discord. Повторная привязка запрещена!"""
        clean_name = player_name.strip()
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Проверяем, не привязан ли этот ник Minecraft к кому-либо
            cursor.execute(
                "SELECT discord_user_id FROM linked_accounts WHERE LOWER(player_name) = LOWER(?)",
                (clean_name,),
            )
            row = cursor.fetchone()
            if row:
                if row[0] == int(discord_user_id):
                    return True
                return False

            # 2. Проверяем, не привязан ли уже этот Discord-пользователь к какому-либо нику
            cursor.execute("SELECT player_name FROM linked_accounts WHERE discord_user_id = ?", (int(discord_user_id),))
            old_row = cursor.fetchone()
            if old_row:
                return False

            conn.execute("""
                INSERT INTO linked_accounts (player_name, player_uuid, discord_user_id, two_factor_enabled, linked_at, login_alerts_enabled)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (clean_name, player_uuid.strip(), int(discord_user_id), int(two_factor), now_str))
            conn.commit()
            return True

    def unlink_account_by_discord(self, discord_user_id: int) -> Optional[str]:
        """Отвязывает аккаунт по Discord ID, возвращает имя отвязанного игрока"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT player_name FROM linked_accounts WHERE discord_user_id = ?",
                (int(discord_user_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            player_name = row[0]
            conn.execute("DELETE FROM linked_accounts WHERE discord_user_id = ?", (int(discord_user_id),))
            conn.execute("DELETE FROM trusted_ip_sessions WHERE LOWER(player_name) = LOWER(?)", (player_name,))
            conn.execute("DELETE FROM pending_link_codes WHERE discord_user_id = ? OR LOWER(player_name) = LOWER(?)", (int(discord_user_id), player_name))
            conn.commit()
            return player_name

    def unlink_account_by_mc(self, player_name: str) -> bool:
        """Отвязывает аккаунт по нику Minecraft"""
        clean_name = player_name.strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM linked_accounts WHERE LOWER(player_name) = LOWER(?)", (clean_name,))
            affected = cursor.rowcount > 0
            conn.execute("DELETE FROM trusted_ip_sessions WHERE LOWER(player_name) = LOWER(?)", (clean_name,))
            conn.execute("DELETE FROM pending_link_codes WHERE LOWER(player_name) = LOWER(?)", (clean_name,))
            conn.commit()
            return affected

    def get_linked_account_by_discord(self, discord_user_id: int) -> Optional[dict]:
        """Получает привязанный аккаунт по Discord ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, player_uuid, discord_user_id, two_factor_enabled, linked_at, trust_duration_hours, login_alerts_enabled
                FROM linked_accounts
                WHERE discord_user_id = ?
            """, (int(discord_user_id),))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "player_name": row[0],
                "player_uuid": row[1],
                "discord_user_id": row[2],
                "two_factor_enabled": bool(row[3]),
                "linked_at": row[4],
                "trust_duration_hours": row[5] if len(row) > 5 and row[5] is not None else 48,
                "login_alerts_enabled": bool(row[6]) if len(row) > 6 and row[6] is not None else True,
            }

    def get_linked_account_by_player(self, player_name: str) -> Optional[dict]:
        """Псевдоним для get_linked_account_by_mc"""
        return self.get_linked_account_by_mc(player_name)

    def get_linked_account_by_mc(self, player_name: str) -> Optional[dict]:
        """Получает привязанный аккаунт по нику Minecraft"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT player_name, player_uuid, discord_user_id, two_factor_enabled, linked_at, trust_duration_hours, login_alerts_enabled
                FROM linked_accounts
                WHERE LOWER(player_name) = LOWER(?)
            """, (player_name.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "player_name": row[0],
                "player_uuid": row[1],
                "discord_user_id": row[2],
                "two_factor_enabled": bool(row[3]),
                "linked_at": row[4],
                "trust_duration_hours": row[5] if len(row) > 5 and row[5] is not None else 48,
                "login_alerts_enabled": bool(row[6]) if len(row) > 6 and row[6] is not None else True,
            }

    def set_trust_duration(self, discord_user_id: int, hours: int) -> bool:
        """Устанавливает персональный срок доверия к IP (0 = каждый раз, 24ч, 48ч, 168ч)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE linked_accounts
                SET trust_duration_hours = ?
                WHERE discord_user_id = ?
            """, (int(hours), int(discord_user_id)))
            conn.commit()
            return cursor.rowcount > 0

    def set_login_alerts_enabled(self, discord_user_id: int, enabled: bool) -> bool:
        """Включает или выключает пуш-уведомления о входе в ЛС Discord"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE linked_accounts
                SET login_alerts_enabled = ?
                WHERE discord_user_id = ?
            """, (1 if enabled else 0, int(discord_user_id)))
            conn.commit()
            return cursor.rowcount > 0

    def record_login(self, player_name: str, ip: str, status: Union[str, bool] = "SUCCESS"):
        """Записывает событие входа. Принимает 'SUCCESS'/'FAILED' или bool (обратная совместимость)."""
        if isinstance(status, bool):
            status = "SUCCESS" if status else "FAILED"
        status_str = str(status or "SUCCESS").strip().upper() or "SUCCESS"
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO login_history (player_name, ip, login_time, status)
                VALUES (?, ?, ?, ?)
            """, (player_name.strip(), ip.strip(), now_ts, status_str))
            conn.commit()

    def get_recent_logins(self, player_name: str, limit: int = 5) -> list[dict]:
        """Возвращает историю недавних входов игрока"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ip, login_time, status
                FROM login_history
                WHERE LOWER(player_name) = LOWER(?)
                ORDER BY id DESC
                LIMIT ?
            """, (player_name.strip(), int(limit)))
            rows = cursor.fetchall()
            return [
                {
                    "ip": r[0],
                    "time": r[1],
                    "status": r[2],
                }
                for r in rows
            ]

    # --- СЕССИИ ДОВЕРЕННЫХ IP (2FA ДОВЕРИЕ) ---
    def is_ip_trusted(self, player_name: str, ip: str) -> bool:
        """Проверяет, доверен ли IP с учётом персонального срока доверия"""
        now_ts = datetime.now(timezone.utc).timestamp()
        linked = self.get_linked_account_by_mc(player_name)
        trust_hours = linked.get("trust_duration_hours", 48) if linked else 48

        # Строгий режим: 0 часов — всегда запрашивать подтверждение
        if trust_hours <= 0:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT expires_at
                FROM trusted_ip_sessions
                WHERE LOWER(player_name) = LOWER(?) AND ip = ?
            """, (player_name.strip(), ip.strip()))
            row = cursor.fetchone()
            if not row:
                return False
            expires_at = row[0]
            if now_ts > expires_at:
                conn.execute("""
                    DELETE FROM trusted_ip_sessions
                    WHERE LOWER(player_name) = LOWER(?) AND ip = ?
                """, (player_name.strip(), ip.strip()))
                conn.commit()
                return False

            # Продлеваем сессию на выбранный срок доверия
            new_expires = now_ts + (float(trust_hours) * 3600.0)
            conn.execute("""
                UPDATE trusted_ip_sessions
                SET expires_at = ?
                WHERE LOWER(player_name) = LOWER(?) AND ip = ?
            """, (new_expires, player_name.strip(), ip.strip()))
            conn.commit()
            return True

    def trust_ip_session(self, player_name: str, ip: str, duration_hours: Optional[float] = None):
        """Продлевает или сохраняет доверенную сессию для IP"""
        linked = self.get_linked_account_by_mc(player_name)
        if duration_hours is None:
            duration_hours = float(linked.get("trust_duration_hours", 48)) if linked else 48.0

        if duration_hours <= 0:
            return

        now_ts = datetime.now(timezone.utc).timestamp()
        expires_at = now_ts + (duration_hours * 3600.0)
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trusted_ip_sessions (player_name, ip, verified_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, (player_name.strip(), ip.strip(), now_ts, expires_at))
            conn.commit()

    def revoke_ip_session(self, player_name: str, ip: str):
        """Отзывает сессию для конкретного IP"""
        with self._get_connection() as conn:
            conn.execute("""
                DELETE FROM trusted_ip_sessions
                WHERE LOWER(player_name) = LOWER(?) AND ip = ?
            """, (player_name.strip(), ip.strip()))
            conn.commit()

    def clear_ip_sessions(self, player_name: str):
        """Сбрасывает все доверенные IP игрока (следующий вход с любого IP потребует 2FA)"""
        with self._get_connection() as conn:
            conn.execute("""
                DELETE FROM trusted_ip_sessions
                WHERE LOWER(player_name) = LOWER(?)
            """, (player_name.strip(),))
            conn.commit()

    def get_trusted_ip_sessions(self, player_name: str) -> list[dict]:
        """Возвращает список действующих IP-сессий игрока"""
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ip, verified_at, expires_at
                FROM trusted_ip_sessions
                WHERE LOWER(player_name) = LOWER(?) AND expires_at > ?
                ORDER BY expires_at DESC
            """, (player_name.strip(), now_ts))
            rows = cursor.fetchall()
            return [
                {
                    "ip": r[0],
                    "verified_at": r[1],
                    "expires_at": r[2],
                    "remaining_sec": max(0.0, r[2] - now_ts),
                }
                for r in rows
            ]

    # --- ОДНОРАЗОВЫЕ КОДЫ ПРИВЯЗКИ (6 ЦИФР) ---
    def create_link_code(
        self,
        player_name: Optional[str],
        discord_user_id: Optional[int],
        code: str,
        lifetime_sec: int = 600,
    ):
        """Создает временный 6-значный код привязки (10 минут)"""
        now_ts = datetime.now(timezone.utc).timestamp()
        expires_at = now_ts + lifetime_sec
        clean_code = str(code).strip()
        with self._get_connection() as conn:
            # Очищаем старые коды для этого игрока/пользователя
            if discord_user_id:
                conn.execute("DELETE FROM pending_link_codes WHERE discord_user_id = ?", (int(discord_user_id),))
            if player_name:
                conn.execute("DELETE FROM pending_link_codes WHERE LOWER(player_name) = LOWER(?)", (player_name.strip(),))

            conn.execute("""
                INSERT OR REPLACE INTO pending_link_codes (code, player_name, discord_user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                clean_code,
                player_name.strip() if player_name else None,
                int(discord_user_id) if discord_user_id else None,
                now_ts,
                expires_at,
            ))
            conn.commit()

    def get_link_code(self, code: str) -> Optional[dict]:
        """Получает данные по коду привязки, если он не истек"""
        now_ts = datetime.now(timezone.utc).timestamp()
        clean_code = str(code).strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT code, player_name, discord_user_id, created_at, expires_at
                FROM pending_link_codes
                WHERE code = ? AND expires_at > ?
            """, (clean_code, now_ts))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "code": row[0],
                "player_name": row[1],
                "discord_user_id": row[2],
                "created_at": row[3],
                "expires_at": row[4],
            }

    def consume_link_code(self, code: str) -> Optional[dict]:
        """Использует и удаляет одноразовый код привязки"""
        data = self.get_link_code(code)
        if not data:
            return None
        with self._get_connection() as conn:
            conn.execute("DELETE FROM pending_link_codes WHERE code = ?", (str(code).strip(),))
            conn.commit()
        return data

    def cleanup_expired_codes(self) -> int:
        """Очистка устаревших кодов и сессий с возвратом количества удаленных записей"""
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._get_connection() as conn:
            c1 = conn.execute("DELETE FROM pending_link_codes WHERE expires_at <= ?", (now_ts,)).rowcount
            c2 = conn.execute("DELETE FROM trusted_ip_sessions WHERE expires_at <= ?", (now_ts,)).rowcount
            conn.commit()
            return max(0, c1) + max(0, c2)

    # --- СИСТЕМА ПРОВЕРОК НА ЧИТЫ (CHEAT CHECKS) ---

    # --- ДЕТЕКЦИЯ ТВИНКОВ / МУЛЬТИАККАУНТОВ ПО IP ---

    def find_alts_by_ip(self, player_name: str) -> list[dict]:
        """Находит все другие ники, когда-либо заходившие с совпадающих IP-адресов (поиск твинков)"""
        alts_data = self.get_player_alts(player_name)
        result = []
        for a in alts_data.get("alts", []):
            shared = a.get("shared_ips", [])
            primary_ip = shared[0] if shared else ""
            result.append({
                "player_name": a["player_name"],
                "ip": primary_ip,
                "last_seen": a.get("last_seen", "")
            })
        return result

    # --- СОСТОЯНИЕ PERSISTENT-ВЬЮ ---
    def save_security_alert(self, message_id: int, player: str, banned_nick: str, banned_reason: str, ip: str = ""):
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO security_alerts (message_id, player, banned_nick, banned_reason, ip) VALUES (?, ?, ?, ?, ?)",
                (int(message_id), player, banned_nick, banned_reason, ip),
            )
            conn.commit()

    def get_security_alert(self, message_id: int) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT player, banned_nick, banned_reason, ip FROM security_alerts WHERE message_id = ?",
                (int(message_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {"player": row[0], "banned_nick": row[1], "banned_reason": row[2], "ip": row[3]}

    def save_dm_reply_target(self, message_id: int, target_player: str):
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dm_reply_targets (message_id, target_player) VALUES (?, ?)",
                (int(message_id), target_player),
            )
            conn.commit()

    def get_dm_reply_target(self, message_id: int) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT target_player FROM dm_reply_targets WHERE message_id = ?", (int(message_id),))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_db_stats(self) -> dict:
        """Возвращает сводную статистику записей в базе данных для системной диагностики"""
        now_ts = datetime.now(timezone.utc).timestamp()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM active_tickets")
            active_tickets = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM linked_accounts")
            linked_accounts = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM trusted_ip_sessions WHERE expires_at > ?", (now_ts,))
            active_sessions = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM player_ips")
            tracked_ips = cursor.fetchone()[0]
            try:
                cursor.execute("SELECT COUNT(DISTINCT player_name) FROM player_ips")
                tracked_players = cursor.fetchone()[0]
            except Exception:
                tracked_players = tracked_ips
            return {
                "active_tickets": active_tickets,
                "linked_accounts": linked_accounts,
                "active_sessions": active_sessions,
                "tracked_ips": tracked_ips,
                "tracked_players": tracked_players,
            }

    # --- МЕТОДЫ ЖУРНАЛИРОВАНИЯ И БЕЗОПАСНОСТИ (ALTS & LITEBANS) ---

    def record_security_incident(self, player: str, ip: str, incident_type: str, details: str):
        """Записывает инцидент безопасности (обход бана, мультибокс, VPN) в журнал"""
        now_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO security_audit_log (timestamp, player, ip, incident_type, details) VALUES (?, ?, ?, ?, ?)",
                (now_str, player.strip(), ip.strip(), incident_type.strip(), details.strip())
            )
            conn.commit()

    def get_security_incidents(self, limit: int = 15) -> list[dict]:
        """Возвращает список последних инцидентов безопасности"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, timestamp, player, ip, incident_type, details FROM security_audit_log ORDER BY id DESC LIMIT ?",
                (max(1, limit),)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "player": r[2],
                    "ip": r[3],
                    "type": r[4],
                    "details": r[5]
                }
                for r in rows
            ]

    def add_security_whitelist(self, target: str, target_type: str = "player", reason: str = "", added_by: str = ""):
        """Добавляет игрока или IP в белый список исключений безопасности"""
        now_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        clean_target = target.strip().lower()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO security_whitelist (target, target_type, reason, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                (clean_target, target_type.strip().lower(), reason.strip(), added_by.strip(), now_str)
            )
            conn.commit()

    def remove_security_whitelist(self, target: str) -> bool:
        """Удаляет цель из белого списка безопасности"""
        clean_target = target.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM security_whitelist WHERE lower(target)=?", (clean_target,))
            conn.commit()
            return cursor.rowcount > 0

    def is_security_whitelisted(self, player_name: str, ip: str = "") -> bool:
        """Проверяет, находится ли игрок или его IP в белом списке безопасности"""
        p_clean = player_name.strip().lower() if player_name else ""
        ip_clean = self._normalize_ip(ip).lower() if ip else ""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if p_clean and ip_clean:
                cursor.execute(
                    "SELECT 1 FROM security_whitelist WHERE lower(target) IN (?, ?) LIMIT 1",
                    (p_clean, ip_clean)
                )
            elif p_clean:
                cursor.execute(
                    "SELECT 1 FROM security_whitelist WHERE lower(target)=? LIMIT 1",
                    (p_clean,)
                )
            elif ip_clean:
                cursor.execute(
                    "SELECT 1 FROM security_whitelist WHERE lower(target)=? LIMIT 1",
                    (ip_clean,)
                )
            else:
                return False
            return cursor.fetchone() is not None

    def get_security_whitelist(self) -> list[dict]:
        """Возвращает все записи белого списка безопасности"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT target, target_type, reason, added_by, added_at FROM security_whitelist ORDER BY added_at DESC")
            return [
                {
                    "target": r[0],
                    "type": r[1],
                    "reason": r[2],
                    "added_by": r[3],
                    "added_at": r[4]
                }
                for r in cursor.fetchall()
            ]

    # --- ВНУТРИИГРОВАЯ ПОЧТА (OFFLINE MAIL) ---
    def send_offline_mail(self, sender: str, recipient: str, message: str) -> int:
        now_str = get_msk_now_str()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO offline_mail (sender, recipient, message, sent_at, is_read) VALUES (?, ?, ?, ?, 0)",
                (sender.strip(), recipient.strip(), message.strip(), now_str),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_unread_mail(self, recipient: str) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, sender, message, sent_at FROM offline_mail WHERE recipient = ? COLLATE NOCASE AND is_read = 0 ORDER BY id ASC",
                (recipient.strip(),),
            )
            return [
                {"id": r[0], "sender": r[1], "message": r[2], "sent_at": r[3]}
                for r in cursor.fetchall()
            ]

    def count_unread_mail(self, recipient: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM offline_mail WHERE recipient = ? COLLATE NOCASE AND is_read = 0",
                (recipient.strip(),),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def mark_mail_read(self, recipient: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE offline_mail SET is_read = 1 WHERE recipient = ? COLLATE NOCASE AND is_read = 0",
                (recipient.strip(),),
            )
            conn.commit()
            return cursor.rowcount

    # --- КАРТОЧКА НАРУШИТЕЛЯ (SUSPECT SUMMARY) ---
    def get_suspect_summary(self, suspect_nick: str) -> dict:
        clean_nick = suspect_nick.strip()
        linked = self.get_linked_account_by_mc(clean_nick)
        ips = [x["ip"] for x in self.get_player_ips(clean_nick, limit=10)]
        
        # Поиск твинков по известным IP
        alts_map: dict[str, str] = {}
        for ip in ips:
            for alt in self.get_alts_by_ip(ip):
                alt_name = alt["player_name"]
                if alt_name.lower() != clean_nick.lower() and alt_name not in alts_map:
                    alts_map[alt_name] = alt["last_seen"]

        deaths_count, last_death = self.get_player_deaths(clean_nick)

        # Проверка алертов безопасности
        alerts = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT banned_nick, banned_reason, ip FROM security_alerts WHERE lower(player) = lower(?)",
                (clean_nick,),
            )
            for r in cursor.fetchall():
                alerts.append({"banned_nick": r[0], "reason": r[1], "ip": r[2]})

        return {
            "player_name": clean_nick,
            "linked": linked,
            "ips": ips,
            "alts": [{"player_name": k, "last_seen": v} for k, v in alts_map.items()],
            "death_count": deaths_count,
            "last_death": last_death,
            "alerts": alerts,
        }

    # --- РЕЗЕРВНОЕ КОПИРОВАНИЕ И САЛЬВАЖ ДАННЫХ ПРИ СБОЯХ ---
    def backup_db(self, backup_dir: Optional[str] = None, keep_last: int = 7, rotate: bool = False) -> Optional[str]:
        """Создает онлайн неблокирующий бэкап SQLite через conn.backup с проверкой целостности и ротацией."""
        if not os.path.exists(self.db_path):
            return None
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        auto_file = os.path.join(backup_dir, "tickets_auto_backup.db")
        tmp_file = os.path.join(backup_dir, f"tickets_tmp_{int(time.time() * 1000)}.db")
        try:
            with self._get_connection() as src_conn:
                try:
                    src_conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
                except Exception:
                    pass
                bck_conn = sqlite3.connect(tmp_file)
                with bck_conn:
                    src_conn.backup(bck_conn)
                chk = bck_conn.execute("PRAGMA quick_check;").fetchone()
                bck_conn.close()
            if not chk or str(chk[0]).lower() != "ok":
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
                logger.warning("Бэкап БД не прошёл PRAGMA quick_check: %s", chk)
                return None

            shutil.copy2(tmp_file, auto_file)
            result_path = auto_file

            if rotate:
                stamp = get_msk_now().strftime("%Y%m%d_%H%M%S")
                rotated_file = os.path.join(backup_dir, f"tickets_{stamp}.db")
                idx = 1
                while os.path.exists(rotated_file):
                    rotated_file = os.path.join(backup_dir, f"tickets_{stamp}_{idx}.db")
                    idx += 1
                os.replace(tmp_file, rotated_file)
                result_path = rotated_file

                # Ротация старых копий: сохраняем только последние keep_last
                try:
                    rotated_list = sorted(
                        [
                            os.path.join(backup_dir, f)
                            for f in os.listdir(backup_dir)
                            if f.startswith("tickets_") and f.endswith(".db") and f != "tickets_auto_backup.db"
                        ],
                        key=lambda p: os.path.getmtime(p),
                        reverse=True,
                    )
                    for old_path in rotated_list[max(1, int(keep_last)):]:
                        try:
                            os.remove(old_path)
                        except Exception:
                            pass
                except Exception as rot_err:
                    logger.debug("Backup rotation cleanup note: %s", rot_err)
            else:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)

            logger.debug("Резервная копия базы данных успешно создана: %s", result_path)
            return result_path
        except Exception as e:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            logger.warning("Ошибка создания бэкапа БД: %s", e)
            return None

    def list_backups(self, backup_dir: Optional[str] = None) -> list[dict]:
        """Возвращает список доступных бэкапов (от новых к старым)."""
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backups")
        if not os.path.isdir(backup_dir):
            return []
        items = []
        for fn in os.listdir(backup_dir):
            if fn.endswith(".db"):
                fp = os.path.join(backup_dir, fn)
                try:
                    st = os.stat(fp)
                    items.append({
                        "name": fn,
                        "path": fp,
                        "size_bytes": st.st_size,
                        "mtime": st.st_mtime,
                    })
                except Exception:
                    pass
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items

    def get_db_summary(self) -> dict:
        """Возвращает сводку записей в основных таблицах БД."""
        tables = ("active_tickets", "ticket_history", "linked_accounts", "player_ips", "top_seasons", "active_mutes")
        summary = {"size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0}
        with self._get_connection() as conn:
            cur = conn.cursor()
            for tbl in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                    summary[tbl] = int(cur.fetchone()[0])
                except Exception:
                    summary[tbl] = 0
        return summary

    def salvage_corrupted_file(self, corrupted_path: str) -> int:
        """
        Пытается извлечь максимум уцелевших записей (счётчик тикетов, историю, привязки, муты)
        из повреждённого файла SQLite и вставить их в текущую базу данных.
        """
        if not os.path.exists(corrupted_path):
            return 0
        logger.info("Попытка спасения данных из файла: %s", corrupted_path)
        recovered_rows = 0
        try:
            old_conn = sqlite3.connect(f"file:{corrupted_path}?mode=ro", uri=True, timeout=10.0)
        except Exception:
            try:
                old_conn = sqlite3.connect(corrupted_path, timeout=10.0)
            except Exception as e:
                logger.error("Не удалось открыть файл для спасения данных %s: %s", corrupted_path, e)
                return 0

        target_tables = [
            ("ticket_counter", "INSERT OR REPLACE INTO ticket_counter (id, count) VALUES (?, ?)"),
            ("ticket_history", "INSERT OR IGNORE INTO ticket_history (ticket_num, dc_channel_id, user_id, user_name, status, created_at, closed_at, closed_by, close_reason, transcript_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"),
            ("active_tickets", "INSERT OR IGNORE INTO active_tickets (dc_channel_id, user_id, user_name, last_activity, created_at, ticket_num) VALUES (?, ?, ?, ?, ?, ?)"),
            ("linked_accounts", "INSERT OR IGNORE INTO linked_accounts (player_name, player_uuid, discord_user_id, two_factor_enabled, linked_at, trust_duration_hours, login_alerts_enabled) VALUES (?, ?, ?, ?, ?, ?, ?)"),
            ("active_mutes", "INSERT OR IGNORE INTO active_mutes (user_id, guild_id, unmute_timestamp, reason) VALUES (?, ?, ?, ?)"),
            ("ticket_blacklist", "INSERT OR IGNORE INTO ticket_blacklist (user_id, reason, banned_by, banned_at) VALUES (?, ?, ?, ?)"),
            ("bot_settings", "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)"),
            ("top_seasons", "INSERT OR REPLACE INTO top_seasons (season, name, data_json, archived_at) VALUES (?, ?, ?, ?)"),
            ("ticket_auto_replies", "INSERT OR IGNORE INTO ticket_auto_replies (id, trigger_phrase, response_text, threshold, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)"),
            ("offline_mail", "INSERT OR IGNORE INTO offline_mail (id, sender, recipient, message, sent_at, is_read) VALUES (?, ?, ?, ?, ?, ?)"),
            ("player_ips", "INSERT OR IGNORE INTO player_ips (player_name, ip, last_seen) VALUES (?, ?, ?)"),
            ("security_whitelist", "INSERT OR IGNORE INTO security_whitelist (target, target_type, reason, added_by, added_at) VALUES (?, ?, ?, ?, ?)"),
        ]

        with self._get_connection() as target_conn:
            for table_name, insert_sql in target_tables:
                try:
                    cur = old_conn.cursor()
                    cur.execute(f"SELECT * FROM {table_name}")
                    rows = cur.fetchall()
                    if rows:
                        for row in rows:
                            try:
                                placeholders_count = insert_sql.count("?")
                                if len(row) >= placeholders_count:
                                    target_conn.execute(insert_sql, row[:placeholders_count])
                                    recovered_rows += 1
                            except Exception:
                                pass
                        target_conn.commit()
                        logger.info("Таблица '%s': успешно спасено строк: %d", table_name, len(rows))
                except Exception as tbl_err:
                    logger.debug("Не удалось прочитать таблицу '%s' из %s: %s", table_name, corrupted_path, tbl_err)

        try:
            old_conn.close()
        except Exception:
            pass

        return recovered_rows

    def close(self):
        """Выполняет корректный чекпоинт WAL и бэкап при завершении работы бота."""
        try:
            with self._get_connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self.backup_db()
            logger.info("База данных успешно чекпоинтирована и сохранен бэкап.")
        except Exception as e:
            logger.debug("Ошибка при закрытии БД: %s", e)


