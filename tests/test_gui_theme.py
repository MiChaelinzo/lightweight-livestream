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

    def test_every_token_pair_meets_aa__in_every_theme(self):
        for theme in gt.THEMES:
            self.assertEqual([], gt.failing_pairs(theme), theme)

    def test_palettes_have_the_same_keys_and_valid_colors(self):
        self.assertEqual(set(gt.THEMES), set(gt.PALETTES))
        for colors in gt.PALETTES.values():
            self.assertEqual(set(gt.PALETTES["light"]), set(colors))
        for colors in gt.PALETTES.values():
            for value in colors.values():
                gt.relative_luminance(value)

    def test_non_text_marks_meet_3_to_1_in_every_theme(self):
        for theme in gt.THEMES:
            colors = gt.palette(theme)
            for fg, bg in gt.NON_TEXT_PAIRS:
                self.assertGreaterEqual(gt.contrast_ratio(colors[fg], colors[bg]),
                                        gt.AA_NON_TEXT_RATIO, (theme, fg, bg))

    def test_themes_have_labels_and_light_dark_stay_first(self):
        self.assertEqual(("light", "dark"), gt.THEMES[:2])
        self.assertEqual(set(gt.THEMES), set(gt.THEME_LABELS))
        self.assertEqual(len(gt.THEMES), len(set(gt.THEMES)))

    def test_cycle_theme_visits_every_theme_then_wraps(self):
        seen, theme = [], gt.THEMES[0]
        for _ in gt.THEMES:
            seen.append(theme)
            theme = gt.cycle_theme(theme)
        self.assertEqual(list(gt.THEMES), seen)
        self.assertEqual(gt.THEMES[0], theme)
        self.assertEqual(gt.THEMES[0], gt.cycle_theme("nope"))

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


class MotionTests(unittest.TestCase):
    def test_animation_enabled_follows_pref_and_potato(self):
        self.assertTrue(gt.animation_enabled({"reduce_motion": False}, False))
        self.assertFalse(gt.animation_enabled({"reduce_motion": True}, False))
        self.assertFalse(gt.animation_enabled({"reduce_motion": False}, True))
        self.assertTrue(gt.animation_enabled({}, False))

    def test_ease_step_is_deterministic_and_converges(self):
        self.assertEqual(gt.ease_step(0.0, 10.0), gt.ease_step(0.0, 10.0))
        value = 0.0
        for _ in range(100):
            nxt = gt.ease_step(value, 10.0)
            self.assertGreaterEqual(nxt, value)
            self.assertLessEqual(nxt, 10.0)
            value = nxt
        self.assertEqual(10.0, value)
        self.assertEqual(5.0, gt.ease_step(10.0, 5.0, rate=1.0))

    def test_ease_step_handles_missing_readings_and_snaps(self):
        self.assertIsNone(gt.ease_step(3.0, None))
        self.assertEqual(7.0, gt.ease_step(None, 7.0))
        self.assertEqual(7.0, gt.ease_step(7.0 - gt.EASE_SNAP, 7.0))


class LookHelperTests(unittest.TestCase):
    def test_disabled_big_buttons_are_readable__in_every_theme(self):
        for theme in gt.THEMES:
            for kind in gt.BIG_BUTTON_KINDS:
                bg, fg = gt.big_button_colors(theme, kind, False)
                self.assertGreaterEqual(gt.contrast_ratio(fg, bg), gt.AA_TEXT_RATIO)
                self.assertNotEqual(bg, gt.big_button_colors(theme, kind, True)[0])
        with self.assertRaises(ValueError):
            gt.big_button_colors("light", "nope", True)

    def test_enabled_emergency_uses_palette_color(self):
        self.assertEqual(("#8F4600", "#FFFFFF"),
                         gt.big_button_colors("light", "emergency", True))

    def test_banner_colors_cover_controller_names(self):
        from lightstream import gui_controller as gc
        for text, name in (gc.BANNER_OFFLINE, gc.BANNER_STARTING, gc.BANNER_LIVE,
                           gc.BANNER_LAGGING, gc.BANNER_RECONNECTING,
                           gc.BANNER_FAILOVER, gc.BANNER_EMERGENCY, gc.BANNER_PROBLEM):
            for theme in gt.THEMES:
                bg, fg = gt.banner_colors(theme, name)
                self.assertGreaterEqual(gt.contrast_ratio(fg, bg), gt.AA_TEXT_RATIO)
        with self.assertRaises(ValueError):
            gt.banner_colors("light", "pink")

    def test_banner_accents_are_visible_on_their_tint(self):
        for theme in gt.THEMES:
            colors = gt.palette(theme)
            for fg, bg in gt.NON_TEXT_PAIRS:
                self.assertGreaterEqual(
                    gt.contrast_ratio(colors[fg], colors[bg]), gt.AA_NON_TEXT_RATIO,
                    (theme, fg, bg))
            for name in gt.BANNER_COLOR_NAMES:
                self.assertEqual(colors["banner_" + name], gt.banner_accent(theme, name))
        with self.assertRaises(ValueError):
            gt.banner_accent("light", "pink")

    def test_center_position(self):
        self.assertEqual((203, 30), gt.center_position(1366, 768, 960, 678))
        self.assertEqual((0, 0), gt.center_position(800, 480, 960, 700))

    def test_pick_font_family(self):
        self.assertEqual("Ubuntu", gt.pick_font_family(["Foo", "ubuntu", "DejaVu Sans"]))
        self.assertEqual("Segoe UI", gt.pick_font_family(["Segoe UI", "Ubuntu"]))
        self.assertEqual(gt.FALLBACK_FONT, gt.pick_font_family(["Foo"]))
        self.assertEqual(gt.FALLBACK_MONO_FONT, gt.pick_font_family(
            [], gt.MONO_PREFERENCE, gt.FALLBACK_MONO_FONT))

    def test_fit_window_stays_on_small_screens(self):
        for screen in ((1366, 768), (1280, 720), (1024, 600), (800, 480)):
            (w, h), (min_w, min_h) = gt.fit_window(*screen)
            self.assertLessEqual(w, screen[0])
            self.assertLessEqual(h + gt.SCREEN_MARGIN[1], screen[1])
            self.assertLessEqual(min_w, w)
            self.assertLessEqual(min_h, h)
        self.assertEqual(gt.PREFERRED_WINDOW, gt.fit_window(3840, 2160)[0])

    def test_scroll_steps(self):
        self.assertEqual(-1, gt.scroll_steps(4))
        self.assertEqual(1, gt.scroll_steps(5))
        self.assertEqual(-1, gt.scroll_steps(None, 120))
        self.assertEqual(2, gt.scroll_steps(None, -240))
        self.assertEqual(-1, gt.scroll_steps(None, 2))
        self.assertEqual(0, gt.scroll_steps(None, 0))

    def test_needs_scrollbar_and_graph_placeholder(self):
        self.assertTrue(gt.needs_scrollbar(900, 600))
        self.assertFalse(gt.needs_scrollbar(600, 600))
        self.assertTrue(gt.graph_is_empty([]))
        self.assertTrue(gt.graph_is_empty([None, 3.0, None]))
        self.assertFalse(gt.graph_is_empty([1.0, None, 2.0]))
        self.assertEqual([10.0, 20.0, 30.0], gt.graph_grid_ys(40))


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
            self.assertEqual({"theme": "light", "compact": False, "reduce_motion": False}, gt.load_ui_prefs(path))
            with open(path, "w") as fh:
                fh.write("{not json")
            self.assertEqual({"theme": "light", "compact": False, "reduce_motion": False}, gt.load_ui_prefs(path))
            with open(path, "w") as fh:
                json.dump({"theme": "neon", "compact": "yes"}, fh)
            self.assertEqual({"theme": "light", "compact": False, "reduce_motion": False}, gt.load_ui_prefs(path))

    def test_roundtrip_private_and_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = gt.ui_prefs_path(os.path.join(tmp, "gui.json"))
            gt.save_ui_prefs(path, "dark", True, True)
            self.assertEqual({"theme": "dark", "compact": True, "reduce_motion": True},
                             gt.load_ui_prefs(path))
            with open(path) as fh:
                self.assertEqual({"theme", "compact", "reduce_motion"},
                                 set(json.load(fh)))
            for theme in gt.THEMES:
                gt.save_ui_prefs(path, theme, False)
                self.assertEqual(theme, gt.load_ui_prefs(path)["theme"])
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
