import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import analytics, cli
from lightstream import gui_controller as gc
from lightstream.health import HealthTracker

SECRET = "live_SECRET_key_123"
DAY = time.struct_time((2025, 3, 7, 12, 0, 0, 4, 66, -1))


def tracker_with_data():
    tracker = HealthTracker(target_kbps=1000)
    for speed, bitrate in ((1.0, 900.0), (0.8, 1100.0)):
        tracker.update({"speed": speed, "bitrate_kbps": bitrate, "fps": 30.0,
                        "dropped": 4})
    tracker.note_reconnect()
    return tracker


class ReportTests(unittest.TestCase):
    def test_report_fields(self):
        report = analytics.build_session_report(
            tracker_with_data().summary(), "h264_qsv", 125.4567, True,
            preset="light", hardware_profile="intel_hd_optimized", now=DAY)
        self.assertEqual("2025-03-07", report["date"])
        self.assertEqual("h264_qsv", report["encoder"])
        self.assertEqual(0.9, report["avg_speed"])
        self.assertEqual(1000.0, report["avg_bitrate_kbps"])
        self.assertEqual(1, report["reconnect_count"])
        self.assertEqual(4, report["dropped_frames"])
        self.assertEqual(125.457, report["recording_seconds"])

    def test_no_recording_means_zero_seconds(self):
        report = analytics.build_session_report({}, "libx264", 60, False, now=DAY)
        self.assertEqual(0, report["recording_seconds"])
        self.assertIsNone(report["avg_speed"])

    def test_report_contains_no_key_or_url(self):
        report = analytics.build_session_report(
            tracker_with_data().summary(), "libx264", 10, True, now=DAY)
        text = json.dumps(report)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("rtmp", text)
        self.assertNotIn("key", " ".join(report).lower())

    def test_write_uses_dated_name_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = os.path.join(tmp, "reports")
            first = analytics.write_session_report(directory, {"a": 1}, DAY)
            second = analytics.write_session_report(directory, {"a": 2}, DAY)
            self.assertEqual("session-20250307.json", os.path.basename(first))
            self.assertEqual("session-20250307-2.json", os.path.basename(second))
            with open(first, encoding="utf-8") as fh:
                self.assertEqual({"a": 1}, json.load(fh))

    def test_opt_in_only(self):
        self.assertFalse(analytics.analytics_enabled(False, {}))
        self.assertFalse(analytics.analytics_enabled(None, {"analytics": "yes"}))
        self.assertTrue(analytics.analytics_enabled(True, {}))
        self.assertTrue(analytics.analytics_enabled(False, {"analytics": True}))

    def test_reports_dir_is_portable_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "portable.flag"), "w").close()
            path = analytics.reports_dir("linux", {}, tmp)
            self.assertEqual(os.path.join(tmp, "data", "reports"), path)
        path = analytics.reports_dir("linux", {"XDG_CONFIG_HOME": "/x"}, "/nonexistent")
        self.assertEqual("/x/lightstream/reports", path)


class WiringTests(unittest.TestCase):
    def run_start(self, argv, home):
        def fake_runner(argv_, key, os_name, **kw):
            kw["on_status"]("live", {"speed": 1.0, "bitrate_kbps": 800.0, "fps": 24.0})
            return 0
        out = io.StringIO()
        env = {"HOME": home, "XDG_CONFIG_HOME": home, "STREAM_KEY": SECRET}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cli, "detect_gpu_names", lambda _o: []), \
                mock.patch.object(cli, "detect_os", lambda: "linux"), \
                mock.patch.object(cli, "find_ffmpeg", lambda: "/bin/ffmpeg"), \
                mock.patch.object(cli, "probe_encoders", lambda _f: set()), \
                mock.patch.object(cli, "choose_working_encoder", lambda *a, **k: "libx264"), \
                mock.patch.object(cli, "run_with_reconnect", fake_runner):
            code = cli.main(argv, out)
        return code, out.getvalue()

    def test_cli_writes_report_only_when_opted_in(self):
        with tempfile.TemporaryDirectory() as home:
            reports = analytics.reports_dir("linux", {"XDG_CONFIG_HOME": home}, "/none")
            code, text = self.run_start(["start"], home)
            self.assertEqual(0, code)
            self.assertFalse(os.path.exists(reports))
            code, text = self.run_start(["start", "--analytics"], home)
            self.assertEqual(0, code)
            names = [n for n in os.listdir(reports) if n.startswith("session-")]
            self.assertEqual(1, len(names))
            self.assertIn(analytics.HISTORY_FILENAME, os.listdir(reports))
            with open(os.path.join(reports, analytics.HISTORY_FILENAME),
                      encoding="utf-8") as fh:
                self.assertNotIn(SECRET, fh.read())
            with open(os.path.join(reports, names[0]), encoding="utf-8") as fh:
                raw = fh.read()
            self.assertNotIn(SECRET, raw)
            self.assertEqual("libx264", json.loads(raw)["encoder"])
            self.assertNotIn(SECRET, text)

    def test_controller_writes_report_only_when_opted_in(self):
        def runner(argv, key, os_name, **kw):
            kw["on_status"]("live", {"speed": 0.95, "bitrate_kbps": 700.0})
            return 0

        for opted_in in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                controller = gc.StreamController(
                    runner=runner, which=lambda _n: "/bin/ffmpeg", os_name="linux",
                    probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264",
                    report_dir=tmp)
                prefs = {"platform": "twitch", "preset": "light", "analytics": opted_in}
                self.assertIsNone(controller.start(prefs, SECRET))
                controller._thread.join(5)
                files = os.listdir(tmp)
                reports = [n for n in files if n.startswith("session-")]
                self.assertEqual(1 if opted_in else 0, len(reports))
                # session report, history row and last performance snapshot
                self.assertEqual(3 if opted_in else 0, len(files))
                for name in files:
                    with open(os.path.join(tmp, name), encoding="utf-8") as fh:
                        self.assertNotIn(SECRET, fh.read())

    def test_analytics_is_a_saved_gui_preference_but_key_never_is(self):
        self.assertIn("analytics", gc.PREF_FIELDS)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "gui.json")
            gc.save_prefs(path, {"analytics": True, "url": "rtmp://x/" + SECRET}, SECRET)
            with open(path, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertEqual({"analytics": True}, saved)


if __name__ == "__main__":
    unittest.main()


class HistoryTests(unittest.TestCase):
    def test_bounded_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(analytics.HISTORY_LIMIT + 5):
                analytics.append_history(folder, analytics.history_entry(
                    {"avg_speed": 1.0, "dropped_frames": i, "reconnects": 0},
                    "cpu", "light"))
            rows = analytics.load_history(folder)
            self.assertEqual(analytics.HISTORY_LIMIT, len(rows))
            self.assertEqual(analytics.HISTORY_LIMIT + 4, rows[-1]["dropped_frames"])
            self.assertEqual({"date", "preset", "bottleneck", "avg_speed",
                              "dropped_frames", "reconnect_count", "avg_bitrate_kbps",
                              "health_score"}, set(rows[0]))

    def test_unreadable_history_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual([], analytics.load_history(folder))
            with open(os.path.join(folder, analytics.HISTORY_FILENAME), "w") as fh:
                fh.write("not json")
            self.assertEqual([], analytics.load_history(folder))
