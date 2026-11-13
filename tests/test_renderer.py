import os

os.environ.setdefault("VANILLA_ENV_SYNC", "0")

import unittest

from cogs.inventory_renderer import TEXTURE_MGR, format_item_name, render_slots_grid


class RendererTests(unittest.TestCase):
    def test_texture_aliases(self):
        for item in ("OAK_STAIRS", "CHEST", "COMPASS", "SHIELD", "OAK_PLANKS"):
            self.assertIsNotNone(TEXTURE_MGR.get_texture(item, 16), item)
        self.assertIsNone(TEXTURE_MGR.get_texture("AIR", 16))

    def test_names(self):
        self.assertEqual(format_item_name("NETHERITE_SWORD"), "Незеритовый меч")
        self.assertEqual(format_item_name("AIR"), "Пусто")

    def test_render_png(self):
        buffer = render_slots_grid(
            "test",
            "Steve",
            {0: {"item": "OAK_STAIRS", "count": 12}, 1: {"item": "DIAMOND", "count": 3}},
            rows=1,
            cols=9,
        )
        data = buffer.getvalue()
        self.assertGreater(len(data), 1000)
        self.assertTrue(data.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
