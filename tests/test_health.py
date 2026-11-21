import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream.health import HealthTracker, WINDOW_SAMPLES
from lightstream.runner import (STATUS_RECONNECTING, parse_progress,
                                run_with_reconnect)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


LINE = "frame=  100 fps=30 q=28.0 size=1024kB time=00:00:03 bitrate=1000.0kbits/s dup=2 drop=5 speed=1.0x"


class ParseTests(unittest.TestCase):
    def test_parses_drop_and_dup(self):
        got = parse_progress(LINE)
        self.assertEqual(got["dropped"], 5.0)
        self.assertEqual(got["dup"], 2.0)
        self.assertEqual(got["fps"], 30.0)

    def test_old_lines_still_parse(self):
        self.assertEqual(parse_progress("fps=30 speed=1.0x"),
                         {"fps": 30.0, "speed": 1.0})


class TrackerTests(unittest.TestCase):
    def feed(self, tracker, n, **health):
        for _ in range(n):
            tracker.update(dict(health))

    def test_summary_values(self):
        t = HealthTracker()
        t.update({"fps": 30.0, "speed": 1.0, "dropped": 0})
        t.update({"fps": 30.0, "speed": 0.5, "dropped": 7})
        s = t.summary()
        self.assertAlmostEqual(s["avg_speed"], 0.75)
        self.assertEqual(s["min_speed"], 0.5)
        self.assertEqual(s["dropped_frames"], 7)

    def test_memory_is_bounded(self):
        t = HealthTracker()
        self.feed(t, WINDOW_SAMPLES * 5, fps=30.0, speed=1.0, bitrate_kbps=900.0)
        self.assertEqual(len(t._speeds), WINDOW_SAMPLES)
        self.assertEqual(len(t._bitrates), WINDOW_SAMPLES)

    def test_longest_lag_uses_clock(self):
        clock = Clock()
        t = HealthTracker(clock=clock)
        t.update({"speed": 1.0})
        clock.now = 10
        t.update({"speed": 0.5})
        clock.now = 25
        t.update({"speed": 0.5})
        clock.now = 30
        t.update({"speed": 1.0})
        self.assertEqual(t.longest_lag_seconds, 20)

    def test_cpu_bound_advice(self):
        t = HealthTracker(target_kbps=1000)
        self.feed(t, 6, fps=20.0, speed=0.7, bitrate_kbps=400.0)
        text = " ".join(t.diagnose())
        self.assertIn("CPU-bound", text)
        self.assertNotIn("network", text)

    def test_network_bound_advice(self):
        t = HealthTracker(target_kbps=1000)
        self.feed(t, 6, fps=30.0, speed=1.0, bitrate_kbps=300.0)
        self.assertIn("lightstream bandwidth", " ".join(t.diagnose()))

    def test_healthy_stream_has_no_advice(self):
        t = HealthTracker(target_kbps=1000)
        self.feed(t, 10, fps=30.0, speed=1.0, bitrate_kbps=950.0)
        self.assertEqual(t.diagnose(), [])

    def test_reconnect_counted_and_advised(self):
        t = HealthTracker()
        t.on_status(STATUS_RECONNECTING, 1)
        t.on_status(STATUS_RECONNECTING, 2)
        self.assertEqual(t.summary()["reconnects"], 2)
        self.assertIn("dropped 2 times", " ".join(t.diagnose()))

    def test_report_lines(self):
        t = HealthTracker()
        t.update({"speed": 1.0})
        self.assertTrue(t.report_lines()[0].startswith("Session health"))


class RunnerIntegrationTests(unittest.TestCase):
    def test_tracker_receives_runner_progress(self):
        class Proc:
            stderr = io.StringIO(LINE + "\n" + LINE + "\n")

            def wait(self):
                return 0

        t = HealthTracker()
        code = run_with_reconnect(["ffmpeg"], "k", "linux",
                                  popen=lambda *a, **kw: Proc(),
                                  on_status=t.on_status, out=io.StringIO())
        self.assertEqual(code, 0)
        self.assertEqual(t.samples, 2)
        self.assertEqual(t.dropped_frames, 5)


if __name__ == "__main__":
    unittest.main()


class NetworkStabilityTests(unittest.TestCase):
    def tracker(self, bitrates, speeds, reconnects=0, target=2500):
        t = HealthTracker(target_kbps=target)
        for b, s in zip(bitrates, speeds):
            t.update({"bitrate_kbps": b, "speed": s})
        t.reconnects = reconnects
        return t

    def test_none_until_enough_samples(self):
        self.assertIsNone(self.tracker([2500] * 3, [1.0] * 3).network_stability())

    def test_steady_stream_scores_100(self):
        result = self.tracker([2500] * 20, [1.0] * 20).network_stability()
        self.assertEqual(100, result.score)
        self.assertIn("not a packet loss", result.basis)

    def test_penalties_lower_the_score(self):
        steady = self.tracker([2500] * 20, [1.0] * 20).network_stability().score
        low = self.tracker([1000] * 20, [1.0] * 20).network_stability().score
        jitter = self.tracker([2500, 1500] * 10, [1.0, 0.7] * 10).network_stability().score
        dropped = self.tracker([2500] * 20, [1.0] * 20, reconnects=3).network_stability().score
        self.assertEqual(60, low)
        self.assertTrue(all(x < steady for x in (low, jitter, dropped)))
        self.assertEqual(80, dropped)

    def test_score_stays_in_range(self):
        worst = self.tracker([0] * 20, [0.1, 1.5] * 10, reconnects=50).network_stability()
        self.assertGreaterEqual(worst.score, 0)
        self.assertLessEqual(worst.score, 100)
