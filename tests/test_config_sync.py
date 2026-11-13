import os

os.environ.setdefault("VANILLA_ENV_SYNC", "0")

import tempfile
import unittest
from pathlib import Path

from config_sync import DEFAULT_KEYS, sync_env_file


class ConfigSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"

    def tearDown(self):
        self.tmp.cleanup()

    def test_adds_missing_and_preserves_existing(self):
        self.env.write_text(
            "DISCORD_TOKEN=secret-token\nPANEL_CHANNEL_ID=123\n# мой комментарий\n",
            encoding="utf-8",
        )

        self.assertTrue(sync_env_file(self.env))
        text = self.env.read_text(encoding="utf-8")

        self.assertIn("DISCORD_TOKEN=secret-token", text)
        self.assertIn("PANEL_CHANNEL_ID=123", text)
        self.assertIn("# мой комментарий", text)
        keys = [
            line.split("=", 1)[0].strip()
            for line in text.splitlines()
            if "=" in line and not line.strip().startswith("#")
        ]
        for key, _ in DEFAULT_KEYS:
            self.assertEqual(keys.count(key), 1, key)

    def test_existing_value_is_not_overwritten(self):
        self.env.write_text("ADMIN_ROLE_IDS=777\nGUILD_ID=42\n", encoding="utf-8")
        self.assertTrue(sync_env_file(self.env))
        text = self.env.read_text(encoding="utf-8")
        self.assertIn("ADMIN_ROLE_IDS=777", text)
        self.assertIn("GUILD_ID=42", text)
        self.assertEqual(text.count("ADMIN_ROLE_IDS="), 1)
        self.assertEqual(text.count("GUILD_ID="), 1)

    def test_second_run_is_noop(self):
        self.env.write_text("DISCORD_TOKEN=x\n", encoding="utf-8")
        self.assertTrue(sync_env_file(self.env))
        self.assertFalse(sync_env_file(self.env))

    def test_missing_file(self):
        self.assertFalse(sync_env_file(Path(self.tmp.name) / "nope.env"))


if __name__ == "__main__":
    unittest.main()
