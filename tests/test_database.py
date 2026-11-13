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


if __name__ == "__main__":
    unittest.main()
