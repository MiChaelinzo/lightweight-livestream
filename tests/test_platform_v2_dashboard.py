import io
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import analytics, cli, gui_controller as gc, gui_pages as gp
from lightstream import gui_theme as gt, optimizer
from lightstream.telemetry import Sample

KEY = "live_SEEDED_SECRET_789"


class PanelTests(unittest.TestCase):
    def test_every_panel_maps_to_an_existing_page(self):
        names = [label for _id, label, _page, _where in gp.PANELS]
        self.assertEqual(["Home", "Streams", "Devices", "Performance", "Network",
                          "Recording", "Analytics", "Settings"], names)
        for panel_id, _label, page_id, _where in gp.PANELS:
            self.assertIn(page_id, gp.page_ids())
            self.assertEqual(page_id, gp.panel_page(panel_id))
        with self.assertRaises(ValueError):
            gp.panel_page("nope")


class PerformanceBufferTests(unittest.TestCase):
    def test_records_all_series_and_drop_deltas(self):
        buffers = gt.PerformanceBuffers(capacity=5)
        sample = Sample(40.0, 55.0, 1000, None, 20.0, None, None)
        buffers.record({"recent_fps": 30, "recent_bitrate_kbps": 2500,
                        "recent_speed": 1.0, "dropped_frames": 4}, sample)
        buffers.record({"recent_fps": 29, "dropped_frames": 10}, None)
        self.assertEqual([0.0, 6.0], buffers.values("drops"))
        self.assertEqual([40.0, None], buffers.values("cpu"))
        self.assertEqual([55.0, None], buffers.values("ram"))
        self.assertEqual([20.0, None], buffers.values("gpu"))
        self.assertEqual([2500.0, None], buffers.values("bitrate"))
        self.assertEqual({n for n, _ in gt.SERIES}, set(buffers.buffers))

    def test_memory_is_bounded(self):
        buffers = gt.PerformanceBuffers(capacity=3)
        for i in range(10):
            buffers.record({"recent_fps": i, "dropped_frames": i})
        self.assertEqual([7.0, 8.0, 9.0], buffers.values("fps"))


class CardStyleTests(unittest.TestCase):
    def test_levels_and_contrast(self):
        for theme in gt.THEMES:
            self.assertEqual(0, gt.card_style(theme, 0)["borderwidth"])
            self.assertGreater(gt.card_style(theme, 2)["borderwidth"],
                               gt.card_style(theme, 1)["borderwidth"])
            self.assertEqual([], gt.failing_pairs(theme))
        with self.assertRaises(ValueError):
            gt.card_style("light", 5)


class HealthLineTests(unittest.TestCase):
    def test_session_health_and_line(self):
        Stab = namedtuple("Stab", "score")
        health = optimizer.session_health(
            {"recent_speed": 1.0}, Sample(50.0, 60.0, 1, None, None, None, None), Stab(100))
        self.assertEqual(100, health.score)
        self.assertEqual("Health: 100/100 (Excellent). PC tier: Creator",
                         optimizer.health_line(health, "Creator"))
        empty = optimizer.session_health({})
        self.assertEqual("Health: not enough readings yet", optimizer.health_line(empty))

    def test_bottleneck_rule_names_cpu_when_slow_and_cpu_high(self):
        from lightstream.adaptive import AdaptiveAdvisor
        advisor = AdaptiveAdvisor("720p30", 2500, 30)
        for _ in range(10):
            advisor.on_status("live", {"speed": 0.6})
        found = optimizer.classify_bottleneck(
            advisor, {}, [Sample(95.0, 50.0, 1, None, None, None, None)] * 5, None,
            optimizer.OptimizerContext("720p30", 2500, 30, "libx264", "off"))
        self.assertEqual(optimizer.BOTTLENECK_CPU, found.kind)


class CompareTests(unittest.TestCase):
    def test_verdicts(self):
        before = {"health_score": 60, "avg_speed": 1.0, "dropped_frames": 10,
                  "reconnect_count": 2}
        after = {"health_score": 80, "avg_speed": 1.0, "dropped_frames": 30,
                 "reconnect_count": 0, "avg_bitrate_kbps": 2000}
        by_key = {c.key: c for c in analytics.compare_sessions(before, after)}
        self.assertEqual("better", by_key["health_score"].verdict)
        self.assertEqual("same", by_key["avg_speed"].verdict)
        self.assertEqual("worse", by_key["dropped_frames"].verdict)
        self.assertEqual("better", by_key["reconnect_count"].verdict)
        self.assertEqual("unknown", by_key["avg_bitrate_kbps"].verdict)

    def test_lines_need_two_sessions(self):
        self.assertIn("Not enough", analytics.comparison_lines([{}])[0])
        lines = analytics.comparison_lines([{"avg_speed": 1.0}, {"avg_speed": 0.5}])
        self.assertTrue(any("worse" in line for line in lines))

    def test_controller_compares_saved_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            for dropped in (1, 5):
                analytics.append_history(tmp, analytics.history_entry(
                    {"avg_speed": 1.0, "dropped_frames": dropped}))
            controller = gc.StreamController(report_dir=tmp, os_name="linux")
            self.assertTrue(any("Dropped frames: 1 -> 5 (worse)" in line
                                for line in controller.comparison_lines()))


class RecordingPrefsTests(unittest.TestCase):
    def test_mp4_and_cbr_reach_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(gc, "data_dir", return_value=tmp):
                s = gc.settings_from_prefs({"platform": "twitch", "preset": "light",
                                            "record": True, "record_format": "mp4",
                                            "rate_mode": "cbr"})
        self.assertTrue(s.record_to.endswith(".mp4"))
        self.assertEqual("cbr", s.rate_mode)

    def test_default_is_mkv_and_vbr(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(gc, "data_dir", return_value=tmp):
                s = gc.settings_from_prefs({"platform": "twitch", "preset": "light",
                                            "record": True})
        self.assertTrue(s.record_to.endswith(".mkv"))
        self.assertEqual("vbr", s.rate_mode)

    def test_potato_prefs(self):
        s = gc.settings_from_prefs({"platform": "twitch", "preset": "light",
                                    "potato": "2000", "potato_grayscale": True})
        self.assertEqual(2000, s.video_kbps)
        self.assertTrue(s.grayscale)
        self.assertFalse(s.skip_static)
        with self.assertRaises(ValueError):
            gc.settings_from_prefs({"platform": "twitch", "preset": "light",
                                    "potato": "999"})

    def test_new_prefs_are_saved(self):
        for field in ("record_format", "rate_mode", "potato"):
            self.assertIn(field, gc.PREF_FIELDS)


class ControllerInsightTests(unittest.TestCase):
    def test_congestion_feeds_gui_insights_and_health_line(self):
        controller = gc.StreamController(os_name="linux")
        controller._health.update({"speed": 0.5, "bitrate_kbps": 300.0, "fps": 30.0})
        controller._context = optimizer.OptimizerContext("720p30", 2500, 30, "libx264", "off")
        lines = controller.insight_lines()
        self.assertIsInstance(lines, list)
        self.assertTrue(controller.health_line().startswith("Health:"))
        snap = controller.performance_snapshot()
        self.assertIn("health_score", snap)


class SupportBundleSnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_and_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = analytics.performance_snapshot(
                {"avg_speed": 1.23456, "dropped_frames": 2},
                Sample(10.0, 20.0, 1, None, None, None, None),
                optimizer.performance_health(cpu=50), "Creator")
            analytics.save_performance_snapshot(tmp, snap)
            loaded = analytics.load_performance_snapshot(tmp)
            self.assertEqual("Creator", loaded["tier"])
            bundle = analytics.build_support_bundle(
                "0", "linux", set(), {}, [], known_secrets=(KEY,), performance=loaded)
            self.assertEqual(loaded, bundle["performance"])
            self.assertEqual(None, analytics.load_performance_snapshot(tmp + "/missing"))


class OptInTests(unittest.TestCase):
    def test_analytics_is_off_by_default(self):
        self.assertFalse(analytics.analytics_enabled(False, {}))
        self.assertFalse(analytics.analytics_enabled(False, {"analytics": "yes"}))
        self.assertTrue(analytics.analytics_enabled(True, {}))

    def test_gui_pref_default_is_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = gc.StreamController(
                runner=lambda *a, **k: 0, which=lambda _n: "/bin/ffmpeg", os_name="linux",
                probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264",
                report_dir=tmp)
            controller.start({"platform": "twitch", "preset": "light"}, KEY)
            controller._thread.join(5)
            self.assertEqual([], os.listdir(tmp))


class CrashReportTests(unittest.TestCase):
    def test_report_hides_addresses_and_keys(self):
        try:
            raise RuntimeError("failed pushing to rtmp://host/app/%s with %s" % (KEY, KEY))
        except RuntimeError as exc:
            report = analytics.build_crash_report(exc, "0", "linux", known_secrets=(KEY,))
        text = json.dumps(report)
        self.assertNotIn(KEY, text)
        self.assertNotIn("rtmp://host", text)
        self.assertEqual("RuntimeError", report["error_type"])

    def test_cli_writes_local_file_for_unexpected_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with mock.patch.object(cli, "cmd_doctor", side_effect=KeyError("boom")), \
                    mock.patch.object(cli, "config_path",
                                      return_value=os.path.join(tmp, "config.json")):
                code = cli.main(["doctor"], buf)
            self.assertEqual(70, code)
            folder = os.path.join(tmp, analytics.CRASH_DIRNAME)
            self.assertEqual(1, len(os.listdir(folder)))
            self.assertIn("never sent anywhere", buf.getvalue())

    def test_no_network_imports_in_analytics(self):
        with open(analytics.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for word in ("urllib", "socket", "http.client", "requests"):
            self.assertNotIn("import " + word, source)


if __name__ == "__main__":
    unittest.main()
