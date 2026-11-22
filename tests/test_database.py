import os

os.environ.setdefault("VANILLA_ENV_SYNC", "0")

import tempfile
import unittest
from pathlib import Path

from database import DatabaseManager


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.db = DatabaseManager(str(base / "test.db"), str(base / "transcripts"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_login_statuses(self):
        self.db.record_login("Steve", "1.2.3.4", True)
        self.db.record_login("Steve", "1.2.3.4", status="FAILED")
        self.db.record_login("Steve", "1.2.3.4", status="success")
        statuses = [row["status"] for row in self.db.get_recent_logins("Steve", 5)]
        self.assertEqual(statuses, ["SUCCESS", "FAILED", "SUCCESS"])

    def test_migration_keeps_alerts_disabled(self):
        self.assertTrue(self.db.link_account("Steve", "uuid-1", 123456, two_factor=1))
        self.db.set_login_alerts_enabled(123456, False)
        self.db.init_db()
        linked = self.db.get_linked_account_by_discord(123456)
        self.assertIsNotNone(linked)
        self.assertFalse(linked["login_alerts_enabled"])

    def test_security_alert_and_dm_target(self):
        self.db.save_security_alert(100, "Player", "Alt", "Ban reason", "1.2.3.4")
        alert = self.db.get_security_alert(100)
        self.assertEqual(alert["player"], "Player")
        self.assertEqual(alert["banned_nick"], "Alt")
        self.assertEqual(alert["banned_reason"], "Ban reason")

        self.db.save_dm_reply_target(200, "Steve")
        self.assertEqual(self.db.get_dm_reply_target(200), "Steve")
        self.assertIsNone(self.db.get_dm_reply_target(201))

    def test_ticket_ping_setting(self):
        self.db.set_setting("ticket_ping_role_ids", "111,222")
        saved = self.db.get_setting("ticket_ping_role_ids")
        self.assertEqual(saved, "111,222")

    def test_ticket_history_and_counter_persistence(self):
        # 1. Генерация номеров
        t1 = self.db.get_next_ticket_number()
        self.assertEqual(t1, 1)

        # 2. Сохранение тикета
        self.db.save_ticket(1001, 555, "UserA", ticket_num=t1)
        self.assertTrue(self.db.is_ticket_channel(1001))

        # 3. Закрытие тикета
        self.db.close_ticket(1001, closed_by="Mod1", reason="Помогли", transcript_file="transcripts/ticket-001.html")
        self.assertFalse(self.db.is_ticket_channel(1001))

        # 4. Проверка истории
        hist = self.db.get_ticket_history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["ticket_num"], 1)
        self.assertEqual(hist[0]["status"], "closed")
        self.assertEqual(hist[0]["closed_by"], "Mod1")
        self.assertEqual(hist[0]["close_reason"], "Помогли")

        # 5. Авто-синхронизация счетчика (не должен сбрасываться меньше max(ticket_num))
        self.db.ensure_ticket_counter_at_least(42)
        next_t = self.db.get_next_ticket_number()
        self.assertEqual(next_t, 43)

    def test_claim_member_event_deduplication(self):
        # Первое событие должно быть захвачено
        self.assertTrue(self.db.claim_member_event(12345, "join", window_sec=10.0))
        # Повторное событие в пределах окна должно быть отклонено (защита от двойных сообщений)
        self.assertFalse(self.db.claim_member_event(12345, "join", window_sec=10.0))
        # Другой тип события или другой пользователь принимаются
        self.assertTrue(self.db.claim_member_event(12345, "remove", window_sec=10.0))
        self.assertTrue(self.db.claim_member_event(99999, "join", window_sec=10.0))

    def test_backup_and_salvage(self):
        # Создаем данные
        self.db.get_next_ticket_number()
        self.db.save_ticket(2002, 777, "UserB", ticket_num=2)

        # Создаем бэкап
        backup_file = self.db.backup_db()
        self.assertIsNotNone(backup_file)
        self.assertTrue(os.path.exists(backup_file))

        # Проверяем сальважирование
        recovered = self.db.salvage_corrupted_file(backup_file)
        self.assertGreaterEqual(recovered, 1)


if __name__ == "__main__":
    unittest.main()
