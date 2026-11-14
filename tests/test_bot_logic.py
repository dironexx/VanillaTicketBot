import os

os.environ.setdefault("VANILLA_ENV_SYNC", "0")

import asyncio
import unittest
from types import SimpleNamespace

from cogs.bridge import BridgeCog
from cogs.bridge_views import TwoFactorVerifyView
from cogs.security import AltActionView, check_ip_intel


class BridgeLogicTests(unittest.TestCase):
    def test_multi_server_stats_aggregate(self):
        fake = SimpleNamespace(
            _socket_stats={},
            mc_online=0,
            mc_max=0,
            mc_tps=20.0,
            mc_mspt=20.0,
            mc_mem_used=0,
            mc_mem_max=0,
            mc_players=[],
        )
        recompute = BridgeCog._recompute_stats.__get__(fake)
        fake._socket_stats[1] = {
            "online": 3, "max": 20, "tps": 19.5, "mspt": 30.0,
            "mem_used": 100, "mem_max": 200, "players": ["A", "B", "C"],
        }
        fake._socket_stats[2] = {
            "online": 2, "max": 10, "tps": 20.0, "mspt": 20.0,
            "mem_used": 50, "mem_max": 100, "players": ["D", "E"],
        }
        recompute()
        self.assertEqual(fake.mc_online, 5)
        self.assertEqual(fake.mc_max, 30)
        self.assertEqual(fake.mc_tps, 19.5)
        self.assertEqual(fake.mc_mspt, 30.0)
        self.assertEqual(fake.mc_players, ["A", "B", "C", "D", "E"])

        fake._socket_stats.pop(1)
        recompute()
        self.assertEqual(fake.mc_online, 2)
        self.assertEqual(fake.mc_players, ["D", "E"])

        fake._socket_stats.clear()
        recompute()
        self.assertEqual(fake.mc_online, 0)
        self.assertEqual(fake.mc_players, [])

    def test_resend_rate_limit(self):
        fake = SimpleNamespace(_resend_attempts={})
        allowed = BridgeCog.resend_rate_ok.__get__(fake)
        self.assertEqual([allowed("Steve") for _ in range(5)], [True, True, True, False, False])

    def test_alt_check_auto_vs_manual(self):
        fake = SimpleNamespace(_alt_check_requests={}, _alt_check_manual={})
        register = BridgeCog.register_alt_check.__get__(fake)
        consume = BridgeCog.consume_alt_check.__get__(fake)

        register("Auto", ttl=5)
        self.assertTrue(consume("Auto"))
        self.assertFalse(consume("Auto"))

        register("Manual", ttl=5, manual=True)
        self.assertFalse(consume("Manual"))

        register("Expired", ttl=1)
        fake._alt_check_requests["expired"] = 0
        self.assertFalse(consume("Expired"))

    def test_two_factor_session_stale(self):
        fake = SimpleNamespace(pending_2fa={})
        self.assertTrue(TwoFactorVerifyView._is_session_stale(fake, "Steve", "s1"))
        fake.pending_2fa["steve"] = {"session_id": "s1"}
        self.assertFalse(TwoFactorVerifyView._is_session_stale(fake, "Steve", "s1"))
        self.assertTrue(TwoFactorVerifyView._is_session_stale(fake, "Steve", "old"))
        self.assertTrue(TwoFactorVerifyView._is_session_stale(fake, "Steve", ""))

    def test_trust_hours_resolution(self):
        fake = SimpleNamespace(
            db=SimpleNamespace(
                get_linked_account_by_mc=lambda player: {"trust_duration_hours": 168}
            )
        )
        self.assertEqual(TwoFactorVerifyView._resolve_trust_hours(fake, "Steve"), 168)

        fake0 = SimpleNamespace(
            db=SimpleNamespace(
                get_linked_account_by_mc=lambda player: {"trust_duration_hours": 0}
            )
        )
        self.assertEqual(TwoFactorVerifyView._resolve_trust_hours(fake0, "Steve"), 0)

    def test_alt_action_state_from_db(self):
        db = SimpleNamespace(
            get_security_alert=lambda message_id: (
                {"player": "P", "banned_nick": "B", "banned_reason": "R", "ip": "1.2.3.4"}
                if message_id == 77 else None
            )
        )
        view = AltActionView("", "", "", db)
        state = view._state(SimpleNamespace(message=SimpleNamespace(id=77)))
        self.assertEqual(state, ("P", "B", "R", "1.2.3.4"))

    def test_local_ip_is_not_external(self):
        result = asyncio.run(check_ip_intel("127.0.0.1"))
        self.assertFalse(result["is_vpn"])
        self.assertEqual(result["country"], "Локальный")

    def test_alert_channel_prefers_bans_name_over_events(self):
        from cogs.security import SecurityCog
        cog = SecurityCog(SimpleNamespace(guilds=[]))
        cog.db = SimpleNamespace(get_setting=lambda k: None)
        cog._resolve_channel = lambda cid: asyncio.sleep(0, result=SimpleNamespace(id=cid, name=f"ch_{cid}"))
        cog._can_send_to = lambda c: True

        ban_ch = SimpleNamespace(id=101, name="баны", send=True)
        events_ch = SimpleNamespace(id=202, name="события", send=True)
        guild = SimpleNamespace(text_channels=[events_ch, ban_ch])
        cog.bot = SimpleNamespace(get_guild=lambda gid: guild, guilds=[guild])

        resolved = asyncio.run(cog._get_alert_channel())
        self.assertEqual(resolved.id, 101)

    def test_env_bool_parser_and_feature_flags(self):
        from config import Config, _env_bool

        self.assertTrue(_env_bool("NON_EXISTENT_VAR", True))
        self.assertFalse(_env_bool("NON_EXISTENT_VAR", False))

        os.environ["TEST_FLAG_ON"] = "true"
        os.environ["TEST_FLAG_OFF"] = "0"
        self.assertTrue(_env_bool("TEST_FLAG_ON", False))
        self.assertFalse(_env_bool("TEST_FLAG_OFF", True))

        self.assertIsInstance(Config.BRIDGE_ENABLE_ALTS_CHECK, bool)
        self.assertIsInstance(Config.BRIDGE_ENABLE_MAINTENANCE_SYNC, bool)
        self.assertIsInstance(Config.BRIDGE_ENABLE_STATS_CHANNELS, bool)

    def test_is_private_or_docker_ip(self):
        from config import _is_private_or_docker_ip

        # Системные и приватные адреса Docker / Pterodactyl / LAN
        self.assertTrue(_is_private_or_docker_ip("172.18.0.1"))
        self.assertTrue(_is_private_or_docker_ip("172.17.0.1"))
        self.assertTrue(_is_private_or_docker_ip("172.31.255.255"))
        self.assertTrue(_is_private_or_docker_ip("10.0.0.1"))
        self.assertTrue(_is_private_or_docker_ip("192.168.1.1"))
        self.assertTrue(_is_private_or_docker_ip("127.0.0.1"))
        self.assertTrue(_is_private_or_docker_ip("0.0.0.0"))
        self.assertTrue(_is_private_or_docker_ip("localhost"))
        self.assertTrue(_is_private_or_docker_ip(""))
        self.assertTrue(_is_private_or_docker_ip("172.18.0.1:25565"))

        # Публичные домены и внешние IP
        self.assertFalse(_is_private_or_docker_ip("vanillaland.ru-mc.ru"))
        self.assertFalse(_is_private_or_docker_ip("vanillaland.ru-mc.ru:25565"))
        self.assertFalse(_is_private_or_docker_ip("play.vanillaland.fun"))
        self.assertFalse(_is_private_or_docker_ip("95.216.123.45"))

    def test_resolve_server_ip_ignores_docker_private_ips(self):
        from config import _resolve_server_ip

        old_srv = os.environ.get("SERVER_IP")
        old_mc = os.environ.get("MC_SERVER_IP")
        try:
            # Если Pterodactyl передал Docker IP 172.18.0.1
            os.environ["SERVER_IP"] = "172.18.0.1"
            os.environ["MC_SERVER_IP"] = "0.0.0.0"
            resolved = _resolve_server_ip()
            self.assertEqual(resolved, "vanillaland.ru-mc.ru")

            # Если задан реальный публичный домен
            os.environ["MC_SERVER_IP"] = "vanillaland.ru-mc.ru"
            resolved2 = _resolve_server_ip()
            self.assertEqual(resolved2, "vanillaland.ru-mc.ru")
        finally:
            if old_srv is not None:
                os.environ["SERVER_IP"] = old_srv
            else:
                os.environ.pop("SERVER_IP", None)
            if old_mc is not None:
                os.environ["MC_SERVER_IP"] = old_mc
            else:
                os.environ.pop("MC_SERVER_IP", None)

    def test_get_next_ticket_number_transaction_safe(self):
        import tempfile
        from database import DatabaseManager
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = os.path.join(tmp_dir, "test_tickets.db")
            db = DatabaseManager(db_file, tmp_dir)
            n1 = db.get_next_ticket_number()
            n2 = db.get_next_ticket_number()
            n3 = db.get_next_ticket_number()
            self.assertEqual(n1, 1)
            self.assertEqual(n2, 2)
            self.assertEqual(n3, 3)

    def test_linked_accounts_case_insensitive(self):
        import tempfile
        from database import DatabaseManager
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = os.path.join(tmp_dir, "test_link.db")
            db = DatabaseManager(db_file, tmp_dir)
            # Привязываем Steve
            self.assertTrue(db.link_account("Steve", "uuid-1", 111111))
            # Попытка привязать тот же ник в нижнем регистре другому пользователю должна быть отклонена
            self.assertFalse(db.link_account("steve", "uuid-2", 222222))
            # Поиск по любому регистру находит правильного владельца
            acc = db.get_linked_account_by_mc("sTeVe")
            self.assertIsNotNone(acc)
            self.assertEqual(acc["discord_user_id"], 111111)

    def test_offline_mail_flow(self):
        import tempfile
        from database import DatabaseManager
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = os.path.join(tmp_dir, "test_mail.db")
            db = DatabaseManager(db_file, tmp_dir)
            
            # Начальное состояние: 0 писем
            self.assertEqual(db.count_unread_mail("Alex"), 0)
            
            # Отправка писем
            id1 = db.send_offline_mail("Steve", "Alex", "Привет! Нужна помощь на спавне.")
            id2 = db.send_offline_mail("Bob", "ALEX", "Забери алмазы из сундука.")
            self.assertGreater(id1, 0)
            self.assertGreater(id2, 0)

            # Проверка количества
            self.assertEqual(db.count_unread_mail("alex"), 2)

            # Чтение
            mails = db.get_unread_mail("alex")
            self.assertEqual(len(mails), 2)
            self.assertEqual(mails[0]["sender"], "Steve")
            self.assertEqual(mails[1]["sender"], "Bob")

            # Отметка о прочтении
            read_cnt = db.mark_mail_read("alex")
            self.assertEqual(read_cnt, 2)
            self.assertEqual(db.count_unread_mail("alex"), 0)

    def test_suspect_summary(self):
        import tempfile
        from database import DatabaseManager
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_file = os.path.join(tmp_dir, "test_suspect.db")
            db = DatabaseManager(db_file, tmp_dir)
            
            # Фиксируем IP для подозреваемого и его твинка
            db.record_player_ip("Griefer", "198.51.100.15")
            db.record_player_ip("AltGriefer", "198.51.100.15")
            db.save_security_alert(1001, "Griefer", "BannedUser", "Griefing", "198.51.100.15")

            summary = db.get_suspect_summary("griefer")
            self.assertEqual(summary["player_name"], "griefer")
            self.assertIn("198.51.100.15", summary["ips"])
            
            # Должен обнаружить твинк AltGriefer
            alt_names = [a["player_name"] for a in summary["alts"]]
            self.assertIn("AltGriefer", alt_names)
            
            # Должен подтянуть алерт
            self.assertEqual(len(summary["alerts"]), 1)
            self.assertEqual(summary["alerts"][0]["banned_nick"], "BannedUser")

    def test_profile_card_renderer(self):
        from cogs.inventory_renderer import render_profile_card
        buf = render_profile_card(
            player_name="Steve",
            is_online=True,
            playtime_str="120 ч",
            diamonds=540,
            debris=18,
            kills=42,
            deaths=12,
            kd_ratio=3.5,
            world_name="Верхний мир",
            level=30,
        )
        self.assertIsNotNone(buf)
        data = buf.getvalue()
        # Проверяем сигнатуру PNG (8 байт: 89 50 4E 47 0D 0A 1A 0A)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(data), 5000)


if __name__ == "__main__":
    unittest.main()
