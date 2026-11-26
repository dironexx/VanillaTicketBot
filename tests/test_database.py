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

    def test_backup_rotation_keeps_last_seven(self):
        for _ in range(9):
            path = self.db.backup_db(keep_last=7, rotate=True)
            self.assertIsNotNone(path)
            self.assertTrue(os.path.exists(path))
        backups = self.db.list_backups()
        rotated = [b for b in backups if b["name"] != "tickets_auto_backup.db"]
        self.assertLessEqual(len(rotated), 7)
        self.assertTrue(any(b["name"] == "tickets_auto_backup.db" for b in backups))

    def test_season3_archive_excludes_nov21_to_24(self):
        with self.db._get_connection() as conn:
            conn.execute(
                "INSERT INTO player_deaths (player_name, death_count, last_death_reason, last_death_time) VALUES (?, ?, ?, ?)",
                ("Veteran", 5, "упал", "2026-11-18 14:20:00"),
            )
            for idx, d_str in enumerate(("2026-11-21 09:00:00", "2026-11-22 12:00:00", "2026-11-23 18:00:00", "2026-11-24 23:59:59")):
                conn.execute(
                    "INSERT INTO player_deaths (player_name, death_count, last_death_reason, last_death_time) VALUES (?, ?, ?, ?)",
                    (f"WipePlayer{idx}", 3, "лава", d_str),
                )
            conn.commit()

        archived_cnt = self.db.archive_deaths_to_season3()
        self.assertEqual(archived_cnt, 1)
        s3 = self.db.get_season_leaderboard(3)
        self.assertIsNotNone(s3)
        self.assertEqual(s3["name"], "3 сезон")
        deaths = s3["data"].get("deaths", [])
        self.assertEqual([d["player"] for d in deaths], ["Veteran"])

    def test_ticket_auto_replies_fuzzy_matching(self):
        rid = self.db.add_ticket_auto_reply(
            "как привязать аккаунт | не работает привязка",
            "Напишите /link в игре и введите код в Discord.",
            threshold=0.68,
            created_by="Admin",
        )
        self.assertGreater(rid, 0)

        # Точное совпадение
        m1 = self.db.find_matching_auto_reply("Подскажите, как привязать аккаунт на сервере?")
        self.assertIsNotNone(m1)
        self.assertEqual(m1["rule"]["id"], rid)

        # Похожая фраза с опечаткой и перефразировкой
        m2 = self.db.find_matching_auto_reply("привет как превязать акаунт к дс")
        self.assertIsNotNone(m2)
        self.assertEqual(m2["rule"]["id"], rid)

        # Посторонняя фраза не должна срабатывать
        m3 = self.db.find_matching_auto_reply("меня загриферили на спавне вчера")
        self.assertIsNone(m3)

        self.assertTrue(self.db.delete_ticket_auto_reply(rid))
        self.assertEqual(self.db.get_ticket_auto_replies(), [])

    def test_giveaways_and_stats_history(self):
        gid = self.db.create_giveaway(1, 2, "VIP", "Тест", 1, 9999999999.0, False, 10)
        self.assertGreater(gid, 0)
        self.db.set_giveaway_message_id(gid, 555666)
        gw = self.db.get_giveaway_by_message(555666)
        self.assertIsNotNone(gw)
        self.assertEqual(gw["prize"], "VIP")

        joined, cnt = self.db.toggle_giveaway_entry(gid, 42)
        self.assertTrue(joined)
        self.assertEqual(cnt, 1)
        self.db.finish_giveaway(gid, [42])
        gw_end = self.db.get_giveaway(gid)
        self.assertEqual(gw_end["status"], "ended")
        self.assertEqual(gw_end["winners"], [42])

        self.db.record_server_stats_point(25, 100, 19.9, 12.5)
        hist = self.db.get_server_stats_history(24)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["online"], 25)

    def test_get_user_tickets_by_id_and_username(self):
        n1 = self.db.get_next_ticket_number()
        self.db.save_ticket(2001, 777001, "Dironexx", ticket_num=n1)
        self.db.close_ticket(2001, closed_by="Mod", reason="Решено", transcript_file="transcripts/t1.txt")

        n2 = self.db.get_next_ticket_number()
        self.db.save_ticket(2002, 777001, "Dironexx", ticket_num=n2)

        by_id = self.db.get_user_tickets(user_id=777001)
        self.assertEqual(len(by_id), 2)
        self.assertEqual(by_id[0]["ticket_num"], n2)
        self.assertEqual(by_id[0]["status"], "open")
        self.assertEqual(by_id[1]["status"], "closed")

        by_name = self.db.get_user_tickets(username="diron")
        self.assertEqual(len(by_name), 2)

        from cogs.tickets import _paginate_transcript_text
        pages = _paginate_transcript_text("\n".join(f"line {i}" for i in range(120)), page_size=200)
        self.assertGreater(len(pages), 1)


if __name__ == "__main__":
    unittest.main()
