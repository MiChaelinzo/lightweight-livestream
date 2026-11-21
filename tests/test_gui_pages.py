import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import gui_pages as gp
from lightstream.adaptive import (KIND_BANDWIDTH_PROFILE, KIND_BITRATE_REDUCTION,
                                  KIND_PRESET_DOWNGRADE, Recommendation)


class PageTests(unittest.TestCase):
    def test_sidebar_pages(self):
        self.assertEqual(gp.page_ids(), ["dashboard", "setup", "scenes", "overlays",
                                         "recording", "advanced"])
        self.assertEqual(gp.page_label("scenes"), "Scenes")
        self.assertEqual(gp.resolve_page("nope"), "dashboard")
        with self.assertRaises(ValueError):
            gp.page_label("nope")

    def test_hardware_choices_include_new_profiles(self):
        choices = gp.hardware_choices()
        self.assertEqual(choices[0], gp.AUTO_HARDWARE_LABEL)
        self.assertIn("intel_hd_optimized", choices)
        self.assertIn("mx250_streamer", choices)
        self.assertEqual(gp.hardware_pref(gp.AUTO_HARDWARE_LABEL), "")
        self.assertEqual(gp.hardware_label("mx250_streamer"), "mx250_streamer")
        self.assertEqual(gp.hardware_label(None), gp.AUTO_HARDWARE_LABEL)

    def test_health_cards(self):
        empty = gp.health_cards({})
        self.assertEqual(empty[0].value, "-")
        cards = gp.health_cards({"recent_speed": 0.95, "dropped_frames": 3,
                                 "reconnects": 1, "recent_fps": 30.0,
                                 "recent_bitrate_kbps": 900.0})
        self.assertEqual([c.value for c in cards],
                         ["0.95x", "30", "900 kbps", "3", "1"])


class RecommendationTests(unittest.TestCase):
    def test_apply_preset_changes_copy_only(self):
        prefs = {"preset": "balanced"}
        rec = Recommendation(KIND_PRESET_DOWNGRADE, "light", "m")
        new, message = gp.apply_recommendation(rec, prefs)
        self.assertEqual(new["preset"], "light")
        self.assertEqual(prefs["preset"], "balanced")
        self.assertIn("next time", message)

    def test_apply_bitrate(self):
        new, _ = gp.apply_recommendation(
            Recommendation(KIND_BITRATE_REDUCTION, 800, "m"), {"bitrate": "1000"})
        self.assertEqual(new["bitrate"], "800")

    def test_not_applicable_leaves_prefs(self):
        rec = Recommendation(KIND_BANDWIDTH_PROFILE, None, "use a cable")
        self.assertFalse(gp.can_apply(rec))
        new, message = gp.apply_recommendation(rec, {"preset": "light"})
        self.assertEqual(new, {"preset": "light"})
        self.assertIn("use a cable", message)

    def test_unknown_preset_rejected(self):
        with self.assertRaises(ValueError):
            gp.apply_recommendation(Recommendation(KIND_PRESET_DOWNGRADE, "x", "m"), {})

    def test_dismiss_hides_only_that_suggestion(self):
        a = Recommendation(KIND_PRESET_DOWNGRADE, "light", "a")
        b = Recommendation(KIND_BITRATE_REDUCTION, 800, "b")
        inbox = gp.RecommendationInbox()
        inbox.dismiss(a)
        self.assertEqual(inbox.visible([a, b]), [b])


class OverlayTests(unittest.TestCase):
    def test_text_preview_is_deterministic(self):
        draft = gp.OverlayDraft(kind="text", text="Hello", corner="top-right", size=30)
        first = gp.overlay_preview(draft)
        self.assertEqual(first, gp.overlay_preview(draft))
        self.assertIn("drawtext", first)
        self.assertIn("fontsize=30", first)
        self.assertIn("w-tw-10", first)

    def test_image_preview_and_scale(self):
        draft = gp.OverlayDraft(kind="image", path="logo.png", size=20)
        self.assertIn("scale=256:-2", gp.overlay_preview(draft))
        self.assertEqual(gp.size_range("image"), (gp.MIN_PERCENT, gp.MAX_PERCENT))

    def test_invalid_preview_explains(self):
        self.assertIn("Not valid yet", gp.overlay_preview(
            gp.OverlayDraft(kind="text", text="bad;text")))

    def test_overlay_limit(self):
        overlays = gp.OverlayList()
        for _ in range(gp.MAX_OVERLAYS):
            overlays.add(gp.OverlayDraft(text="x"))
        with self.assertRaises(ValueError):
            overlays.add(gp.OverlayDraft(text="x"))
        overlays.remove(0)
        overlays.add(gp.OverlayDraft(text="x"))


class SceneActionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.file = os.path.join(self.dir.name, "scenes.json")

    def test_save_duplicate_export_import(self):
        ok, _ = gp.save_scene_action(
            self.file, "game", [gp.OverlayDraft(text="Hi", size=24)])
        self.assertTrue(ok)
        with open(self.file, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("\n  ", text)  # indented, human readable
        self.assertEqual(json.loads(text)["scenes"][0]["overlays"][0]["text"], "Hi")
        self.assertTrue(gp.duplicate_scene_action(self.file, "game")[0])
        self.assertEqual(gp.scene_names(self.file), ["game", "game-copy"])
        dest = os.path.join(self.dir.name, "out.json")
        self.assertTrue(gp.export_scene_action(self.file, "game", dest)[0])
        self.assertFalse(gp.export_scene_action(self.file, "game", dest)[0])
        other = os.path.join(self.dir.name, "other.json")
        ok, message = gp.import_scene_action(other, dest)
        self.assertTrue(ok, message)
        self.assertEqual(gp.scene_names(other), ["game"])
        self.assertFalse(gp.import_scene_action(other, dest)[0])

    def test_errors_become_messages(self):
        self.assertFalse(gp.save_scene_action(self.file, "", [])[0])
        ok, message = gp.duplicate_scene_action(self.file, "missing")
        self.assertFalse(ok)
        self.assertIn("missing", message)
        self.assertEqual(gp.scene_names(os.path.join(self.dir.name, "none.json")), [])


class ControllerTests(unittest.TestCase):
    def test_health_summary_feeds_cards(self):
        from lightstream import gui_controller as gc
        controller = gc.StreamController(os_name="linux")
        values = [c.value for c in gp.health_cards(controller.health_summary())]
        self.assertEqual(values[0], "-")
        self.assertEqual(controller.recommendations(), [])


class ImportTests(unittest.TestCase):
    def test_gui_imports_without_display(self):
        from lightstream import gui
        self.assertTrue(hasattr(gui, "StreamWindow"))


class TelemetryCardTests(unittest.TestCase):
    def test_unknown_fields_show_n_a(self):
        from lightstream.telemetry import UNKNOWN_SAMPLE
        self.assertEqual({"n/a"}, {c.value for c in gp.telemetry_cards(UNKNOWN_SAMPLE)})

    def test_known_fields_are_formatted(self):
        from lightstream.telemetry import Sample
        cards = {c.title: c.value for c in gp.telemetry_cards(
            Sample(12.4, 50.0, 4096.0, 61.0, None, None, 200.0))}
        self.assertEqual("12%", cards["CPU"])
        self.assertEqual("61 C", cards["CPU temp"])
        self.assertEqual("n/a", cards["GPU"])
        self.assertEqual("200 MB", cards["ffmpeg memory"])


class ProfileChoiceTests(unittest.TestCase):
    def test_profile_choices_roundtrip(self):
        self.assertEqual(gp.AUTO_PROFILE_LABEL, gp.profile_choices()[0])
        self.assertIn("competitive", gp.profile_choices())
        self.assertEqual("", gp.profile_pref(gp.AUTO_PROFILE_LABEL))
        self.assertEqual("potato", gp.profile_pref(gp.profile_label("potato")))
        self.assertEqual(gp.AUTO_PROFILE_LABEL, gp.profile_label("bogus"))

    def test_audio_profile_choices_roundtrip(self):
        self.assertEqual(gp.NO_AUDIO_PROFILE_LABEL, gp.audio_profile_choices()[0])
        self.assertEqual("", gp.audio_profile_pref(gp.NO_AUDIO_PROFILE_LABEL))
        self.assertEqual("asmr", gp.audio_profile_pref(gp.audio_profile_label("asmr")))

    def test_applying_a_preset_suggestion_clears_the_profile(self):
        rec = Recommendation(KIND_PRESET_DOWNGRADE, "light", "x")
        prefs, _ = gp.apply_recommendation(rec, {"preset": "balanced", "profile": "quality"})
        self.assertEqual(("light", ""), (prefs["preset"], prefs["profile"]))


if __name__ == "__main__":
    unittest.main()
