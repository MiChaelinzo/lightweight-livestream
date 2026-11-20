import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import adaptive
from lightstream.adaptive import AdaptiveAdvisor
from lightstream.runner import STATUS_LIVE, STATUS_RECONNECTING


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def feed(advisor, clock, seconds, **health):
    for _ in range(int(seconds)):
        clock.now += 1
        advisor.observe(dict(health))


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.advisor = AdaptiveAdvisor("balanced", 2500, target_fps=30, clock=self.clock)

    def test_healthy_stream_gives_no_advice(self):
        feed(self.advisor, self.clock, 120, speed=1.0, fps=30.0, dropped=0)
        self.assertEqual([], self.advisor.recommendations())

    def test_slow_not_yet_sustained(self):
        feed(self.advisor, self.clock, 20, speed=0.8, fps=24.0)
        self.assertEqual([], self.advisor.recommendations())

    def test_sustained_slow_suggests_lighter_preset(self):
        feed(self.advisor, self.clock, 40, speed=0.85, fps=24.0)
        rec, = self.advisor.recommendations()
        self.assertEqual(adaptive.KIND_PRESET_DOWNGRADE, rec.kind)
        self.assertEqual("light", rec.value)
        self.assertTrue(self.advisor.cpu_pressure())

    def test_recovery_resets_the_slow_clock(self):
        feed(self.advisor, self.clock, 25, speed=0.8, fps=24.0)
        feed(self.advisor, self.clock, 1, speed=1.0, fps=30.0)
        feed(self.advisor, self.clock, 25, speed=0.8, fps=24.0)
        self.assertEqual([], self.advisor.recommendations())

    def test_lightest_preset_suggests_hardware_encoder(self):
        advisor = AdaptiveAdvisor("potato", 700, clock=self.clock)
        feed(advisor, self.clock, 40, speed=0.5)
        rec, = advisor.recommendations()
        self.assertIsNone(rec.value)
        self.assertIn("hardware encoder", rec.message)

    def test_speed_exactly_at_threshold_is_fine(self):
        feed(self.advisor, self.clock, 60, speed=0.90)
        self.assertEqual([], self.advisor.recommendations())

    def test_dropped_frames_suggest_lower_bitrate(self):
        for total in range(0, 100, 10):
            feed(self.advisor, self.clock, 1, speed=1.0, dropped=total)
        rec, = self.advisor.recommendations()
        self.assertEqual(adaptive.KIND_BITRATE_REDUCTION, rec.kind)
        self.assertEqual(2000, rec.value)

    def test_few_dropped_frames_are_ignored(self):
        for total in (0, 5, 10):
            feed(self.advisor, self.clock, 1, dropped=total)
        self.assertEqual([], self.advisor.recommendations())

    def test_old_drops_leave_the_window(self):
        feed(self.advisor, self.clock, 1, dropped=0)
        feed(self.advisor, self.clock, 1, dropped=100)
        self.clock.now += adaptive.DROPPED_WINDOW_SECONDS + 5
        feed(self.advisor, self.clock, 1, dropped=100)
        self.assertEqual([], self.advisor.recommendations())

    def test_bitrate_suggestion_has_floor(self):
        advisor = AdaptiveAdvisor("potato", 320, clock=self.clock)
        feed(advisor, self.clock, 1, dropped=0)
        feed(advisor, self.clock, 1, dropped=500)
        rec, = advisor.recommendations()
        self.assertEqual(adaptive.MIN_SUGGESTED_KBPS, rec.value)

    def test_reconnects_suggest_bandwidth_profile(self):
        self.advisor.on_status(STATUS_RECONNECTING)
        self.assertEqual([], self.advisor.recommendations())
        self.clock.now += 10
        self.advisor.on_status(STATUS_RECONNECTING)
        rec, = self.advisor.recommendations()
        self.assertEqual(adaptive.KIND_BANDWIDTH_PROFILE, rec.kind)
        self.assertIn("lightstream bandwidth", rec.message)
        self.assertEqual(2, self.advisor.reconnects_total)

    def test_old_reconnects_expire(self):
        self.advisor.note_reconnect()
        self.advisor.note_reconnect()
        self.clock.now += adaptive.RECONNECT_WINDOW_SECONDS + 1
        feed(self.advisor, self.clock, 1, speed=1.0)
        self.assertEqual([], self.advisor.recommendations())

    def test_on_status_live_feeds_observe(self):
        for _ in range(40):
            self.clock.now += 1
            self.advisor.on_status(STATUS_LIVE, {"speed": 0.7, "fps": 20.0})
        self.assertTrue(self.advisor.recommendations())

    def test_cpu_pressure_needs_low_fps_when_target_known(self):
        feed(self.advisor, self.clock, 1, speed=0.8, fps=30.0)
        self.assertFalse(self.advisor.cpu_pressure())

    def test_advisor_never_changes_its_inputs(self):
        feed(self.advisor, self.clock, 40, speed=0.5, fps=10.0)
        self.advisor.recommendations()
        self.assertEqual(("balanced", 2500), (self.advisor.preset_name,
                                              self.advisor.video_kbps))

    def test_empty_observation_ignored(self):
        self.advisor.observe(None)
        self.advisor.observe({})
        self.assertEqual([], self.advisor.recommendations())


class ControllerHookTests(unittest.TestCase):
    def test_controller_exposes_recommendations_and_keeps_prefs(self):
        from lightstream import gui_controller as gc
        from lightstream.runner import STATUS_RECONNECTING as RECON

        def runner(argv, key, os_name, **kw):
            kw["on_status"](RECON, None)
            kw["on_status"](RECON, None)
            return 0

        controller = gc.StreamController(
            runner=runner, which=lambda _n: "/bin/ffmpeg", os_name="linux",
            probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264")
        prefs = {"platform": "twitch", "preset": "light"}
        self.assertIsNone(controller.start(prefs, "key123"))
        controller._thread.join(5)
        kinds = [r.kind for r in controller.recommendations()]
        self.assertEqual([adaptive.KIND_BANDWIDTH_PROFILE], kinds)
        self.assertEqual({"platform": "twitch", "preset": "light"}, prefs)


if __name__ == "__main__":
    unittest.main()
