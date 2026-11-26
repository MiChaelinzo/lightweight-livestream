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


class GuiCrashReportTests(unittest.TestCase):
    def raise_error(self, text):
        try:
            raise RuntimeError(text)
        except RuntimeError as exc:
            return exc

    def test_report_is_local_and_redacts_key_and_address(self):
        key = "live_GUIKEY_123456"
        exc = self.raise_error("push rtmp://host/app/%s failed, key %s" % (key, key))
        with tempfile.TemporaryDirectory() as d:
            message = gc.report_gui_crash(exc, key, directory=d, os_name="linux")
            files = os.listdir(d)
            self.assertEqual(1, len(files))
            with open(os.path.join(d, files[0]), encoding="utf-8") as fh:
                text = fh.read()
        self.assertNotIn(key, text)
        self.assertNotIn("rtmp://host", text)
        self.assertIn("RuntimeError", message)
        self.assertIn("never sent anywhere", message)
        self.assertNotIn(key, message)

    def test_short_key_does_not_mask_ordinary_text(self):
        exc = self.raise_error("test failed")
        with tempfile.TemporaryDirectory() as d:
            gc.report_gui_crash(exc, "test", directory=d, os_name="linux")
            with open(os.path.join(d, os.listdir(d)[0]), encoding="utf-8") as fh:
                self.assertIn("test failed", fh.read())

    def test_unwritable_directory_returns_message_instead_of_raising(self):
        exc = self.raise_error("boom")
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "file")
            open(blocker, "w").close()
            message = gc.report_gui_crash(exc, "", directory=os.path.join(blocker, "x"),
                                          os_name="linux")
        self.assertIn("could not be saved", message)


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


class ProfileWiringTests(unittest.TestCase):
    def test_profile_and_audio_profile_reach_settings(self):
        plain = gc.settings_from_prefs(PREFS, cpu_count=8)
        self.assertIsNone(plain.audio_filter)
        self.assertIsNone(plain.threads)
        prefs = dict(PREFS, profile="competitive", audio_profile="podcast")
        s = gc.settings_from_prefs(prefs, cpu_count=8)
        self.assertEqual((1280, 720, 60), (s.width, s.height, s.fps))  # profile preset wins
        self.assertEqual(6, s.threads)
        self.assertEqual(2, s.reserved_cores)
        self.assertTrue(s.audio_filter)

    def test_explicit_boxes_beat_profile(self):
        s = gc.settings_from_prefs(dict(PREFS, profile="competitive", fps="45",
                                        bitrate="1500"), cpu_count=8)
        self.assertEqual((45, 1500), (s.fps, s.video_kbps))

    def test_blank_profile_values_change_nothing(self):
        blank = gc.settings_from_prefs(dict(PREFS, profile="", audio_profile=""))
        self.assertEqual(gc.settings_from_prefs(PREFS), blank)

    def test_prefs_roundtrip_new_fields_without_key(self):
        prefs = dict(PREFS, profile="potato", audio_profile="gaming", auto_scale=True)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gui.json")
            gc.save_prefs(path, prefs, SECRET)
            self.assertEqual("potato", gc.load_prefs(path)["profile"])
            self.assertTrue(gc.load_prefs(path)["auto_scale"])

    def test_controller_passes_affinity_to_runner(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        with mock.patch.object(gc.os, "cpu_count", return_value=8):
            c.start(dict(PREFS, profile="competitive"), SECRET)
            c._thread.join(0.3)
        c.stop()
        self.assertEqual({2, 3, 4, 5, 6, 7}, calls[0][1]["cpu_affinity"])
        self.assertIn("-threads", calls[0][0])

    def test_auto_scale_off_unless_ticked(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        c.start(PREFS, SECRET)
        c._thread.join(0.3)
        c.stop()
        self.assertFalse(c._scale.scaler.enabled)
        calls2 = []
        c = make_controller(fake_runner_factory(calls2))
        c.start(dict(PREFS, auto_scale=True), SECRET)
        c._thread.join(0.3)
        c.stop()
        self.assertTrue(c._scale.scaler.enabled)
        self.assertIsNotNone(calls2[0][1]["argv_for_attempt"])
        # always supplied so Emergency and failover can relaunch with new settings
        self.assertIsNotNone(calls[0][1]["argv_for_attempt"])

    def test_controller_scales_down_and_relaunches_without_key(self):
        clock = [0.0]
        argvs = []

        def runner(argv, key, os_name, **kw):
            argvs.append(argv)
            for _ in range(40):
                clock[0] += 1
                kw["on_status"](STATUS_LIVE, {"speed": 0.5, "fps": 10.0})
            self.assertTrue(kw["restart"].is_set())
            argvs.append(kw["argv_for_attempt"](1, "libx264"))
            return 0
        c = gc.StreamController(
            runner=runner, which=lambda _n: "/bin/ffmpeg", os_name="linux",
            probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264",
            clock=lambda: clock[0])
        c.start(dict(PREFS, preset="balanced", auto_scale=True), SECRET)
        c._thread.join(2)
        first, second = argvs
        self.assertNotEqual(first[first.index("-b:v") + 1], second[second.index("-b:v") + 1])
        self.assertNotIn(SECRET, c.snapshot()[3])
        self.assertIn("Auto-scale down", c.snapshot()[3])
        self.assertTrue(c.insights())

    def test_gaming_first_follows_reserved_cores(self):
        for prefs, expected in ((dict(PREFS, profile="competitive"), True),
                                (PREFS, False)):
            c = make_controller(fake_runner_factory([]))
            c.start(dict(prefs, auto_scale=True), SECRET)
            c._thread.join(0.3)
            c.stop()
            self.assertIs(expected, c._scale.gaming_first)

    def test_step_retargets_health_and_advisor(self):
        clock = [0.0]

        def runner(argv, key, os_name, **kw):
            for _ in range(40):
                clock[0] += 1
                kw["on_status"](STATUS_LIVE, {"speed": 0.5, "fps": 10.0})
            return 0
        c = gc.StreamController(
            runner=runner, which=lambda _n: "/bin/ffmpeg", os_name="linux",
            probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264",
            clock=lambda: clock[0])
        c.start(dict(PREFS, preset="balanced", auto_scale=True), SECRET)
        c._thread.join(2)
        step = c._scale.decisions[0].step
        self.assertEqual(step.kbps, c._health.target_kbps)
        self.assertEqual(step.kbps, c._advisor.video_kbps)
        self.assertEqual(step.fps, c._advisor.target_fps)

    def test_sampler_ticks_without_controller_lock(self):
        held = []

        class Sampler:
            latest = None
            history = ()

            def tick_if_due(self_inner):
                held.append(c._lock.locked())
        c = make_controller(fake_runner_factory([]))
        c._sampler = Sampler()
        c.start(PREFS, SECRET)
        c._thread.join(0.3)
        c.stop()
        self.assertEqual([False], held)


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

    def test_persistent_ingest_conflicts_with_backup_url(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        prefs = dict(PREFS, persistent_ingest=True, backup_url="rtmp://backup/live")
        message = c.start(prefs, SECRET)
        self.assertEqual(gc.PERSISTENT_BACKUP_CONFLICT, message)
        self.assertEqual(message, c.snapshot()[2])
        self.assertEqual([], calls)
        self.assertFalse(c.is_running())
        # the conflict only applies when the box is ticked and a backup is set
        self.assertIsNone(gc.persistent_conflict(dict(PREFS, backup_url="rtmp://b/x")))
        self.assertIsNone(gc.persistent_conflict(dict(PREFS, persistent_ingest=True)))
        self.assertIsNone(gc.persistent_conflict(prefs, test_local=True))

    def test_persistent_ingest_is_off_by_default(self):
        calls = []
        c = make_controller(fake_runner_factory(calls))
        with mock.patch.object(gc, "run_with_publisher") as publisher:
            c.start(PREFS, SECRET)
            c._thread.join(0.3)
            c.stop()
        publisher.assert_not_called()

    def test_persistent_ingest_wraps_the_encoder_in_a_publisher(self):
        seen = {}

        def fake_publisher(publisher_argv, key, os_name, run_encoder, **kw):
            seen["argv"] = publisher_argv
            seen["kw"] = kw
            return run_encoder()

        calls = []
        c = make_controller(fake_runner_factory(calls))
        with mock.patch.object(gc, "run_with_publisher", fake_publisher):
            self.assertIsNone(c.start(dict(PREFS, persistent_ingest=True), SECRET))
            c._thread.join(0.3)
            before = c._scale.current_settings
            self.assertIn("Emergency mode is on", c.emergency())
            after = c._scale.current_settings
            self.assertTrue(c._scale.restart.is_set())
            c.stop()
        # constant size: same picture and audio, lower fps/bitrate
        self.assertEqual((before.width, before.height), (after.width, after.height))
        self.assertEqual(before.audio_kbps, after.audio_kbps)
        self.assertLessEqual(after.video_kbps, before.video_kbps)
        port = str(c._scale.current_settings.local_ingest_port)
        self.assertTrue(any(port in part for part in calls[0][0]))
        self.assertTrue(any(port in part for part in seen["argv"]))
        self.assertIs(calls[0][1]["stop"], seen["kw"]["encoder_stop"])

    def test_guardian_and_survival_are_off_unless_ticked(self):
        for pref in ("guardian", "auto_survival"):
            self.assertIn(pref, gc.PREF_FIELDS)
        c = make_controller(fake_runner_factory([]))
        c.start(PREFS, SECRET)
        c._thread.join(0.3)
        c.stop()
        self.assertIsNone(c._scale.guardian)
        self.assertIsNone(c._scale.survival)
        self.assertIsNone(c._timeline)
        self.assertFalse(c._scale.scaler.enabled)

    def test_guardian_pref_turns_on_autoscale_guardian_and_timeline(self):
        c = make_controller(fake_runner_factory([]))
        c.start(dict(PREFS, guardian=True, auto_survival=True), SECRET)
        c._thread.join(0.3)
        c.stop()
        self.assertTrue(c._scale.scaler.enabled)
        self.assertIsNotNone(c._scale.guardian)
        self.assertTrue(c._scale.survival.enabled)
        self.assertIsNotNone(c._timeline)

    def test_flags_are_ignored_for_test_recordings(self):
        c = make_controller(fake_runner_factory([]))
        c.start(dict(PREFS, guardian=True, auto_survival=True), "", test_local=True)
        c._thread.join(0.3)
        c.stop()
        self.assertIsNone(c._scale.guardian)
        self.assertFalse(c._scale.scaler.enabled)

    def test_persistent_pref_is_remembered_and_never_the_key(self):
        self.assertIn("persistent_ingest", gc.PREF_FIELDS)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gui.json")
            gc.save_prefs(path, dict(PREFS, persistent_ingest=True), SECRET)
            self.assertTrue(gc.load_prefs(path)["persistent_ingest"])
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn(SECRET, fh.read())

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
                                   lambda **_kw: os.path.join(d, "rec", "a.mkv")):
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


class GuiWindowDisplayTests(unittest.TestCase):
    """Need a display (set DISPLAY, e.g. Xvfb); skipped otherwise."""

    def setUp(self):
        if not os.environ.get("DISPLAY"):
            self.skipTest("no DISPLAY")
        import tkinter
        from lightstream import gui
        try:
            self.root = tkinter.Tk()
        except tkinter.TclError:
            self.skipTest("Tk cannot open the display")
        self.addCleanup(self.root.destroy)
        home = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": home})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = gui.StreamWindow(self.root)
        self.root.update_idletasks()

    def test_callback_error_sets_status_without_raising(self):
        with mock.patch.object(gc, "report_gui_crash", return_value="saved report") as rep:
            self.window.on_callback_error(ValueError, ValueError("boom"), None)
        self.assertEqual(self.window.status.get(), "saved report")
        self.assertIsInstance(rep.call_args[0][0], ValueError)

    def test_wheel_from_other_toplevel_is_ignored(self):
        import tkinter
        other = tkinter.Toplevel(self.root)
        self.addCleanup(other.destroy)
        event = mock.Mock(widget=other, num=4, delta=0)
        with mock.patch.object(self.window.page_canvas, "yview_scroll") as scroll:
            self.window._on_wheel(event)
        scroll.assert_not_called()


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
