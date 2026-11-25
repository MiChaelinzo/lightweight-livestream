import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import gui_theme as gt


class ContrastTests(unittest.TestCase):
    def test_known_ratios(self):
        self.assertAlmostEqual(gt.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(gt.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=2)
        self.assertEqual(gt.contrast_ratio("#123456", "#ABCDEF"),
                         gt.contrast_ratio("#ABCDEF", "#123456"))

    def test_bad_color_rejected(self):
        for bad in ("red", "#FFF", "", None):
            with self.assertRaises(ValueError):
                gt.relative_luminance(bad)

    def test_every_token_pair_meets_aa_in_both_themes(self):
        for theme in gt.THEMES:
            self.assertEqual([], gt.failing_pairs(theme), theme)

    def test_palettes_have_the_same_keys_and_valid_colors(self):
        self.assertEqual(set(gt.PALETTES["light"]), set(gt.PALETTES["dark"]))
        for colors in gt.PALETTES.values():
            for value in colors.values():
                gt.relative_luminance(value)

    def test_failing_pairs_detects_low_contrast(self):
        original = gt.PALETTES["light"]["foreground"]
        try:
            gt.PALETTES["light"]["foreground"] = "#F0F0F0"
            self.assertTrue(gt.failing_pairs("light"))
        finally:
            gt.PALETTES["light"]["foreground"] = original

    def test_theme_helpers(self):
        self.assertEqual("dark", gt.toggle_theme("light"))
        self.assertEqual("light", gt.toggle_theme("dark"))
        self.assertEqual(gt.PALETTES["light"], gt.palette("nope"))
        self.assertLess(gt.font_sizes(True)["text"], gt.font_sizes(False)["text"])
        self.assertLess(gt.spacing(True)["large"], gt.spacing(False)["large"])


class ShortcutTests(unittest.TestCase):
    def test_table_has_no_duplicates(self):
        sequences = [s for s, _a, _t in gt.SHORTCUTS]
        self.assertEqual(len(sequences), len(set(sequences)))
        actions = [a for _s, a, _t in gt.SHORTCUTS]
        self.assertEqual(len(actions), len(set(actions)))

    def test_required_actions_present(self):
        actions = {a for _s, a, _t in gt.SHORTCUTS}
        for needed in ("start", "stop", "emergency", "theme", "compact", "page:dashboard"):
            self.assertIn(needed, actions)

    def test_every_page_has_a_shortcut(self):
        from lightstream import gui_pages as gp
        for page in gp.page_ids():
            self.assertTrue(gt.shortcut_for("page:" + page), page)

    def test_accelerator_text(self):
        self.assertEqual("START (Ctrl+Enter)", gt.with_accelerator("START", "start"))
        self.assertEqual("Label", gt.with_accelerator("Label", "unknown"))


class RingBufferTests(unittest.TestCase):
    def test_memory_is_bounded(self):
        ring = gt.RingBuffer(5)
        for i in range(10000):
            ring.append(i)
        self.assertEqual([9995.0, 9996.0, 9997.0, 9998.0, 9999.0], ring.values())
        self.assertEqual(5, len(ring))

    def test_none_is_kept_and_capacity_validated(self):
        ring = gt.RingBuffer(3)
        ring.append(None)
        self.assertEqual([None], ring.values())
        with self.assertRaises(ValueError):
            gt.RingBuffer(1)

    def test_downsample(self):
        self.assertEqual([1, 2], gt.downsample([1, 2], 10))
        self.assertEqual([1.5, 3.5], gt.downsample([1, 2, 3, 4], 2))
        self.assertEqual([None, 4.0], gt.downsample([None, None, 4, 4], 2))
        self.assertLessEqual(len(gt.downsample(list(range(1000)), 75)), 75)
        with self.assertRaises(ValueError):
            gt.downsample([1], 0)

    def test_sparkline_points(self):
        self.assertEqual([], gt.sparkline_points([1], 100, 20))
        self.assertEqual([], gt.sparkline_points([None, 3, None], 100, 20))
        coords = gt.sparkline_points([0, 10], 102, 24, pad=2)
        self.assertEqual([2.0, 22.0, 100.0, 2.0], coords)
        flat = gt.sparkline_points([5, 5, 5], 100, 20, pad=0)
        self.assertEqual({10.0}, set(flat[1::2]))

    def test_redraw_gate_limits_to_one_hertz(self):
        gate = gt.RedrawGate(1.0)
        self.assertTrue(gate.ready(100.0))
        self.assertFalse(gate.ready(100.5))
        self.assertFalse(gate.ready(100.99))
        self.assertTrue(gate.ready(101.0))


class UiPrefsTests(unittest.TestCase):
    def test_defaults_when_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ui.json")
            self.assertEqual({"theme": "light", "compact": False}, gt.load_ui_prefs(path))
            with open(path, "w") as fh:
                fh.write("{not json")
            self.assertEqual({"theme": "light", "compact": False}, gt.load_ui_prefs(path))
            with open(path, "w") as fh:
                json.dump({"theme": "neon", "compact": "yes"}, fh)
            self.assertEqual({"theme": "light", "compact": False}, gt.load_ui_prefs(path))

    def test_roundtrip_private_and_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = gt.ui_prefs_path(os.path.join(tmp, "gui.json"))
            gt.save_ui_prefs(path, "dark", True)
            self.assertEqual({"theme": "dark", "compact": True}, gt.load_ui_prefs(path))
            with open(path) as fh:
                self.assertEqual({"theme", "compact"}, set(json.load(fh)))
            if os.name == "posix":
                self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))
            with self.assertRaises(ValueError):
                gt.save_ui_prefs(path, "neon", False)


class GuiModuleTests(unittest.TestCase):
    def test_gui_imports_and_graph_names_have_titles(self):
        from lightstream import gui
        self.assertEqual(set(gui.GRAPH_NAMES), set(gui.GRAPH_TITLES))
        self.assertLessEqual(gui.GRAPH_SAMPLES, 120)


if __name__ == "__main__":
    unittest.main()
