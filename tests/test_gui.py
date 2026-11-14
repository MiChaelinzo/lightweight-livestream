import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import gui_controller as gc
from lightstream.runner import STATUS_FAILED, STATUS_LIVE

SECRET = "live_SECRET_key_123"
PREFS = {"platform": "twitch", "preset": "light"}


def fake_runner_factory(calls, lines=()):
    def runner(argv, key, os_name, **kw):
        calls.append((argv, kw))
        for line in lines:
            kw["out"].write(line)
        kw["on_status"](STATUS_LIVE, {"speed": 1.0})
        kw["stop"].wait(5)
        return 0
    return runner


def make_controller(runner, ffmpeg="/bin/ffmpeg"):
    return gc.StreamController(
        runner=runner, which=lambda _n: ffmpeg, os_name="linux",
        probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264")


class ValidationTests(unittest.TestCase):
    def test_empty_key(self):
        self.assertEqual(gc.validate(PREFS, "  ", "/ffmpeg"), gc.HELP_TEXT["no_key"])

    def test_missing_url(self):
        prefs = dict(PREFS, platform="custom", url=" ")
        self.assertEqual(gc.validate(prefs, "k", "/ffmpeg"), gc.HELP_TEXT["no_url"])

    def test_missing_ffmpeg(self):
        self.assertEqual(gc.validate(PREFS, "k", None), gc.HELP_TEXT["no_ffmpeg"])

    def test_ok(self):
        self.assertIsNone(gc.validate(PREFS, "k", "/ffmpeg"))

    def test_bad_number_is_friendly(self):
        with self.assertRaises(ValueError) as ctx:
            gc.settings_from_prefs(dict(PREFS, fps="abc"))
        self.assertIn("Advanced", str(ctx.exception))

    def test_blank_advanced_uses_preset(self):
        s = gc.settings_from_prefs(dict(PREFS, fps="", bitrate=""))
        self.assertEqual((s.width, s.fps), (854, 30))


class MappingTests(unittest.TestCase):
    def test_strength_labels_map_to_presets(self):
        self.assertEqual(gc.value_for(gc.STRENGTH_CHOICES, "Very old PC (potato)"), "potato")
        self.assertEqual(gc.label_for(gc.STRENGTH_CHOICES, "720p60"), "Strong PC (720p60)")

    def test_suggest_strength(self):
        self.assertEqual([gc.suggest_strength(n) for n in (None, 2, 4, 8, 16)],
                         ["potato", "potato", "light", "balanced", "720p60"])

    def test_banner(self):
        self.assertEqual(gc.banner_for(STATUS_LIVE, {"speed": 1.0}), gc.BANNER_LIVE)
        self.assertEqual(gc.banner_for(STATUS_LIVE, {"speed": 0.5}), gc.BANNER_LAGGING)
        self.assertEqual(gc.banner_for(STATUS_FAILED, 1), gc.BANNER_PROBLEM)
        self.assertEqual(gc.banner_for("stopped"), gc.BANNER_OFFLINE)


class PrefsTests(unittest.TestCase):
    def test_key_never_saved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x", "gui.json")
            gc.save_prefs(path, dict(PREFS, key=SECRET, stream_key=SECRET))
            with open(path) as fh:
                text = fh.read()
            self.assertNotIn(SECRET, text)
            self.assertEqual(json.loads(text), PREFS)
            self.assertEqual(gc.load_prefs(path), PREFS)

    def test_short_key_keeps_unrelated_prefs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gui.json")
            prefs = dict(PREFS, fps="30", bitrate="1000")
            gc.save_prefs(path, prefs, key="3")
            self.assertEqual(gc.load_prefs(path), prefs)
            gc.save_prefs(path, prefs, key="30")  # whole-value match is dropped
            self.assertNotIn("fps", gc.load_prefs(path))

    def test_load_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gui.json")
            with open(path, "w") as fh:
                fh.write("{oops")
            self.assertEqual(gc.load_prefs(path), {})
            self.assertEqual(gc.load_prefs(os.path.join(d, "none.json")), {})


class ControllerTests(unittest.TestCase):
    def test_start_stop_and_log_redaction(self):
        calls = []
        c = make_controller(fake_runner_factory(
            calls, ["url rtmp://x/%s\n" % SECRET]))
        self.assertIsNone(c.start(PREFS, SECRET))
        c._thread.join(0.3)
        text, color, _help, log, running = c.snapshot()
        self.assertTrue(running)
        self.assertEqual(text, gc.BANNER_LIVE[0])
        self.assertNotIn(SECRET, log)
        self.assertIn("****", log)
        self.assertEqual(c.start(PREFS, SECRET), "You are already streaming.")
        c.stop()
        snap = c.snapshot()
        self.assertFalse(snap[4])
        self.assertEqual(snap[0], gc.BANNER_OFFLINE[0])
        self.assertEqual(calls[0][1]["max_failures"], gc.MAX_QUICK_FAILURES)

    def test_stop_without_waiting_returns_at_once_and_ends_stream(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        c.start(PREFS, SECRET)
        c._thread.join(0.3)
        c.stop(wait=False)
        c._thread.join(2)
        self.assertFalse(c.snapshot()[4])

    def test_test_local_needs_no_key_and_records_once(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        self.assertIsNone(c.start(PREFS, "", test_local=True))
        c._thread.join(0.3)
        argv, kw = calls[0]
        self.assertEqual(argv[-1], gc.TEST_FILENAME)
        self.assertEqual(kw["max_failures"], 1)
        c.stop()

    def test_mute_pref_reaches_settings(self):
        self.assertTrue(gc.settings_from_prefs(dict(PREFS, mute=True)).mute)
        self.assertFalse(gc.settings_from_prefs(PREFS).mute)

    def test_keep_trying_is_unlimited(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        c.start(dict(PREFS, keep_trying=True), SECRET)
        c._thread.join(0.3)
        c.stop()
        self.assertIsNone(calls[0][1]["max_failures"])

    def test_validation_blocks_start(self):
        calls = []
        c = make_controller(fake_runner_factory(calls), ffmpeg=None)
        self.assertEqual(c.start(PREFS, SECRET), gc.HELP_TEXT["no_ffmpeg"])
        self.assertEqual(c.snapshot()[2], gc.HELP_TEXT["no_ffmpeg"])
        self.assertEqual(calls, [])

    def test_runner_oserror_shows_problem(self):
        def boom(*a, **k):
            raise OSError("no ffmpeg")
        c = make_controller(boom)
        c.start(PREFS, SECRET)
        c._thread.join(2)
        text, _color, help_text, log, _r = c.snapshot()
        self.assertEqual(text, gc.BANNER_PROBLEM[0])
        self.assertEqual(help_text, gc.HELP_TEXT["failed"])
        self.assertNotIn(SECRET, log)


class GuiModuleTests(unittest.TestCase):
    def test_import_without_display(self):
        import lightstream.gui as gui  # must not open a window
        self.assertTrue(callable(gui.main))

    def test_cli_gui_is_friendly_without_display(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(
            os.path.dirname(__file__), "..", "src"))
        env.pop("DISPLAY", None)
        r = subprocess.run([sys.executable, "-m", "lightstream", "gui"],
                           env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("could not open", r.stdout)


if __name__ == "__main__":
    unittest.main()


def test_save_prefs_drops_value_containing_key(tmp_path):
    path = str(tmp_path / "gui.json")
    gc.save_prefs(path, {"platform": "custom",
                         "url": "rtmp://host/app/SECRETKEY", "fps": "30"},
                  "SECRETKEY")
    saved = gc.load_prefs(path)
    assert "url" not in saved and saved["fps"] == "30"
    assert "SECRETKEY" not in open(path).read()
