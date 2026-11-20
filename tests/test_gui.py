import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import config
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


class StudioFeatureTests(unittest.TestCase):
    def test_one_click_setup_intel_hd_low_ram(self):
        fields, message = gc.one_click_setup(
            os_name="linux", platform="twitch", upload_mbps="3", cpu_count=8,
            ram_mb=4096, gpu_text="00:02.0 VGA compatible controller: Intel HD Graphics 620")
        self.assertEqual(fields["hardware"], "intel_hd_optimized")
        self.assertIn(fields["preset"], ("potato", "light"))
        self.assertEqual(fields["noise"], "off")
        self.assertIn("intel hd", message)
        self.assertNotIn("key", " ".join(str(v) for v in fields.values()).lower())

    def test_one_click_setup_without_upload_has_no_bitrate(self):
        fields, _m = gc.one_click_setup(os_name="linux", cpu_count=4, ram_mb=8192,
                                        gpu_text="")
        self.assertEqual(fields["bitrate"], "")
        self.assertEqual(fields["hardware"], "generic")

    def test_scene_choices_missing_file_and_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scenes.json")
            self.assertEqual(gc.scene_choices(path), [gc.NO_SCENE_LABEL])
            with open(path, "w") as fh:
                json.dump({"scenes": [{"name": "cam", "sources": [
                    {"kind": "screen"}]}]}, fh)
            self.assertEqual(gc.scene_choices(path), [gc.NO_SCENE_LABEL, "cam"])
            with open(path, "w") as fh:
                fh.write("{broken")
            self.assertEqual(gc.scene_choices(path), [gc.NO_SCENE_LABEL])

    def test_record_checkbox_reaches_settings(self):
        path = gc.settings_from_prefs(dict(PREFS, record=True)).record_to
        self.assertTrue(os.path.isabs(path))
        self.assertIn(os.path.join(gc.data_dir(), gc.RECORDINGS_DIRNAME), path)
        self.assertRegex(os.path.basename(path), r"^lightstream-\d{8}-\d{6}\.mkv$")
        self.assertIsNone(gc.settings_from_prefs(dict(PREFS, record=False)).record_to)

    def test_record_uses_tee_in_argv(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(gc, "recording_path",
                                   lambda: os.path.join(d, "rec", "a.mkv")):
                c.start(dict(PREFS, record=True), SECRET)
                c._thread.join(0.3)
                c.stop()
            self.assertIn("tee", calls[0][0])
            self.assertIn(os.path.join(d, "rec", "a.mkv").replace("\\", "/"),
                          calls[0][0][-1])
            self.assertTrue(os.path.isdir(os.path.join(d, "rec")))

    def test_unknown_scene_gives_plain_error(self):
        c = make_controller(fake_runner_factory([]))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scenes.json")
            with open(path, "w") as fh:
                json.dump({"scenes": [{"name": "cam", "sources": [
                    {"kind": "screen"}]}]}, fh)
            with mock.patch.object(config, "scenes_path", lambda *a, **k: path):
                error = c.start(dict(PREFS, scene="nope"), SECRET)
        self.assertIn("Unknown scene", error)

    def test_missing_scenes_file_gives_plain_error(self):
        c = make_controller(fake_runner_factory([]))
        with mock.patch.object(config, "scenes_path", lambda *a, **k: "/nonexistent/s.json"):
            error = c.start(dict(PREFS, scene="cam"), SECRET)
        self.assertIn("scenes example", error)

    def test_hardware_and_noise_prefs_saved_without_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gui.json")
            gc.save_prefs(path, dict(PREFS, hardware="intel_hd", noise="light",
                                     record=True, scene="cam"), SECRET)
            saved = gc.load_prefs(path)
        self.assertEqual((saved["hardware"], saved["noise"], saved["record"], saved["scene"]),
                         ("intel_hd", "light", True, "cam"))

    def test_health_advice_when_encoding_too_slow(self):
        def slow_runner(argv, key, os_name, **kw):
            for _ in range(10):
                kw["on_status"](STATUS_LIVE, {"speed": 0.5, "fps": 20})
            kw["stop"].wait(5)
            return 0
        c = make_controller(slow_runner)
        c.start(PREFS, SECRET)
        c._thread.join(0.3)
        advice = c.health_advice()
        c.stop()
        self.assertIn("cannot encode fast enough", advice)

    def test_health_advice_empty_when_healthy(self):
        c = make_controller(fake_runner_factory([]))
        c.start(PREFS, SECRET)
        c._thread.join(0.3)
        self.assertEqual(c.health_advice(), "")
        c.stop()


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
