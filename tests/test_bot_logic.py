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


if __name__ == "__main__":
    unittest.main()
