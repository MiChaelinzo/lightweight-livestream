import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import autoscale as au
from lightstream import runner
from lightstream.adaptive import AdaptiveAdvisor
from lightstream.command import build_command, numbered_recording_path
from lightstream.config import resolve_settings

SECRET = "live_SECRET_key_123"
STRESS = au.ScaleSignal(au.STRESSED, "slow")
GOOD = au.ScaleSignal(au.HEALTHY, "")
NEUTRAL = au.ScaleSignal(au.NEUTRAL, "")


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def make(enabled=True, top=au.LadderStep(1280, 720, 60, 4000)):
    clock = Clock()
    scaler = au.AutoScaler(au.build_ladder(top), clock, enabled=enabled)
    return clock, scaler


def hold(clock, scaler, signal, seconds):
    """Feed one signal per second; return the decisions taken."""
    taken = []
    for _ in range(int(seconds)):
        clock.now += 1
        decision = scaler.update(signal)
        if decision:
            taken.append(decision)
    return taken


class LadderTests(unittest.TestCase):
    def test_order_bitrate_then_fps_then_resolution(self):
        steps = au.build_ladder(au.LadderStep(1280, 720, 60, 4000))
        self.assertEqual(au.LadderStep(1280, 720, 60, 4000), steps[0])
        self.assertEqual((1280, 720, 60), steps[1][:3])
        self.assertLess(steps[1].kbps, 4000)
        self.assertEqual((1280, 720, 60), steps[2][:3])
        self.assertEqual((1280, 720, 45), steps[3][:3])
        self.assertEqual((1280, 720, 30), steps[4][:3])
        for before, after in zip(steps, steps[1:]):
            self.assertTrue(after.kbps <= before.kbps and after.fps <= before.fps
                            and after.height <= before.height)
            self.assertNotEqual(before, after)
        self.assertEqual(360, steps[-1].height)
        self.assertIn(480, [s.height for s in steps])

    def test_1080p_steps_to_900p_and_60_fps_to_45(self):
        steps = au.build_ladder(au.LadderStep(1920, 1080, 60, 6000))
        heights = [s.height for s in steps]
        self.assertIn(900, heights)
        self.assertLess(heights.index(900), heights.index(720))
        self.assertIn((1600, 900), [(s.width, s.height) for s in steps])
        fps = [s.fps for s in steps]
        self.assertLess(fps.index(45), fps.index(30))

    def test_user_bitrate_kept_and_floor_respected(self):
        steps = au.build_ladder(au.LadderStep(854, 480, 30, 900), "light")
        self.assertEqual(480, steps[-1].height)
        self.assertTrue(all(s.kbps <= 900 for s in steps))
        self.assertTrue(all(s.kbps >= au.MIN_LADDER_KBPS for s in steps))


class ScalerTests(unittest.TestCase):
    def test_disabled_by_default_and_never_acts(self):
        self.assertFalse(au.AutoScaler([au.LadderStep(1, 1, 1, 1)]).enabled)
        clock, scaler = make(enabled=False)
        self.assertEqual([], hold(clock, scaler, STRESS, 500))
        self.assertEqual(0, scaler.index)

    def test_downscale_needs_sustained_stress(self):
        clock, scaler = make()
        self.assertEqual([], hold(clock, scaler, STRESS, au.DOWNSCALE_AFTER_SECONDS - 2))
        taken = hold(clock, scaler, STRESS, 3)
        self.assertEqual(1, len(taken))
        self.assertEqual((au.DOWN, 0, 1), taken[0][:3])

    def test_one_step_at_a_time_with_cooldown(self):
        clock, scaler = make()
        taken = hold(clock, scaler, STRESS, 200)
        times = len(taken)
        self.assertGreaterEqual(times, 2)
        self.assertTrue(all(d.to_index - d.from_index == 1 for d in taken))
        self.assertLessEqual(times, 200 // au.COOLDOWN_SECONDS + 1)

    def test_floor_is_never_passed(self):
        clock, scaler = make()
        for _ in range(60):
            hold(clock, scaler, STRESS, 100)
            clock.now += au.HOUR_SECONDS  # rate limit window passes
        self.assertEqual(len(scaler.ladder) - 1, scaler.index)

    def test_gradual_restore_and_ceiling(self):
        clock, scaler = make()
        hold(clock, scaler, STRESS, 100)
        low = scaler.index
        self.assertGreaterEqual(low, 1)
        ups = hold(clock, scaler, GOOD, au.UPSCALE_AFTER_SECONDS - 5)
        self.assertEqual([], ups)
        ups = hold(clock, scaler, GOOD, 10)
        self.assertEqual(1, len(ups))
        self.assertEqual(low - 1, scaler.index)
        hold(clock, scaler, GOOD, 5000)
        self.assertEqual(0, scaler.index)  # never above the top the user chose
        self.assertEqual([], hold(clock, scaler, GOOD, 500))

    def test_no_flapping_with_oscillating_input(self):
        clock, scaler = make()
        taken = []
        for _ in range(500):
            taken += hold(clock, scaler, STRESS, au.DOWNSCALE_AFTER_SECONDS - 5)
            taken += hold(clock, scaler, GOOD, au.UPSCALE_AFTER_SECONDS - 5)
        self.assertEqual([], taken)

    def test_neutral_resets_timers(self):
        clock, scaler = make()
        hold(clock, scaler, STRESS, au.DOWNSCALE_AFTER_SECONDS - 3)
        hold(clock, scaler, NEUTRAL, 1)
        self.assertEqual([], hold(clock, scaler, STRESS, au.DOWNSCALE_AFTER_SECONDS - 3))

    def test_cooldown_blocks_immediate_reversal(self):
        clock, scaler = make()
        hold(clock, scaler, STRESS, 25)
        self.assertEqual(1, scaler.index)
        hold(clock, scaler, GOOD, au.UPSCALE_AFTER_SECONDS - 5)
        self.assertEqual(1, scaler.index)

    def test_max_changes_per_hour(self):
        clock, scaler = make(top=au.LadderStep(1280, 720, 60, 4000))
        scaler.ladder = scaler.ladder * 20  # long ladder so only the rate limit binds
        taken = hold(clock, scaler, STRESS, 1800)
        self.assertEqual(au.MAX_CHANGES_PER_HOUR, len(taken))

    def test_deterministic(self):
        runs = []
        for _ in range(2):
            clock, scaler = make()
            runs.append([d[:3] for d in hold(clock, scaler, STRESS, 300)
                         + hold(clock, scaler, GOOD, 600)])
        self.assertEqual(runs[0], runs[1])


class GamingFirstHoldoffTests(unittest.TestCase):
    CPU = au.ScaleSignal(au.STRESSED, "cpu", cpu_bound=True)

    def test_no_step_up_right_after_cpu_triggered_step_down(self):
        clock, scaler = make()
        self.assertEqual(1, len(hold(clock, scaler, self.CPU, 21)))
        taken = hold(clock, scaler, GOOD, int(au.GAMING_STEP_UP_HOLDOFF_SECONDS) - 60)
        self.assertEqual([], taken)
        self.assertEqual(1, scaler.index)
        taken = hold(clock, scaler, GOOD, 120)
        self.assertEqual([au.UP], [d.direction for d in taken])

    def test_slow_encoder_step_down_can_step_up_after_normal_wait(self):
        clock, scaler = make()
        self.assertEqual(1, len(hold(clock, scaler, STRESS, 21)))
        taken = hold(clock, scaler, GOOD, 200)
        self.assertEqual([au.UP], [d.direction for d in taken])

    def test_alternating_cpu_stress_and_recovery_is_bounded(self):
        clock, scaler = make()
        taken = []
        for _ in range(4):
            taken += hold(clock, scaler, self.CPU, 30)
            taken += hold(clock, scaler, GOOD, 200)
        self.assertEqual([], [d for d in taken if d.direction == au.UP])

    def test_assess_marks_gaming_first_cpu_stress(self):
        clock = Clock()
        adv = AdaptiveAdvisor("balanced", 2500, 30, clock=clock)
        adv.observe({"speed": 1.0, "fps": 30.0, "dropped": 0})
        busy = type("S", (), {"cpu_percent": 95.0})()
        self.assertTrue(au.assess(adv, busy, gaming_first=True).cpu_bound)
        adv.observe({"speed": 0.4, "fps": 30.0, "dropped": 0})
        clock.now += 1
        adv.observe({"speed": 0.4, "fps": 30.0, "dropped": 0})
        self.assertFalse(au.assess(adv, busy, gaming_first=True).cpu_bound)


class AssessTests(unittest.TestCase):
    def advisor(self, speed, dropped=0):
        clock = Clock()
        adv = AdaptiveAdvisor("balanced", 2500, 30, clock=clock)
        adv.observe({"speed": speed, "fps": 30.0, "dropped": 0})
        clock.now += 1
        adv.observe({"speed": speed, "fps": 30.0, "dropped": dropped})
        return adv

    def test_signals(self):
        self.assertEqual(au.STRESSED, au.assess(self.advisor(0.5)).state)
        self.assertEqual(au.STRESSED, au.assess(self.advisor(1.0, dropped=99)).state)
        self.assertEqual(au.HEALTHY, au.assess(self.advisor(1.0)).state)
        self.assertEqual(au.NEUTRAL, au.assess(AdaptiveAdvisor()).state)

    def test_gaming_first_protects_game(self):
        busy = type("S", (), {"cpu_percent": 97.0})()
        adv = self.advisor(1.0)
        self.assertEqual(au.HEALTHY, au.assess(adv, busy, gaming_first=False).state)
        signal = au.assess(adv, busy, gaming_first=True)
        self.assertEqual(au.STRESSED, signal.state)
        self.assertIn("Gaming First", signal.reason)
        self.assertIn("97%", signal.reason)


class SessionAndRunnerTests(unittest.TestCase):
    def settings(self, record):
        return resolve_settings({"platform": "twitch", "preset": "720p60",
                                 "record": record}, {})

    def test_step_relaunches_with_new_settings_and_hides_key(self):
        settings = self.settings("rec.mkv")
        clock = Clock()
        advisor = AdaptiveAdvisor("720p60", settings.video_kbps, settings.fps, clock=clock)
        scaler = au.AutoScaler(au.build_ladder(au.top_step(settings)), clock, enabled=True)
        restart = threading.Event()
        out = io.StringIO()
        session = au.AutoScaleSession(settings, advisor, scaler, restart, out.write)
        argvs = []
        slow = "frame=1 fps=20 bitrate=900.0kbits/s speed=0.5x\n"

        def on_status(state, detail=None):
            if state == runner.STATUS_LIVE:
                clock.now += 1
                advisor.observe(detail)
            session.on_status(state, detail)

        def settings_for(n):
            current = session.current_settings
            return current._replace(record_to=numbered_recording_path(current.record_to, n))

        def popen(argv, **kw):
            argvs.append(list(argv))
            n = len(argvs)

            class Proc:
                stderr = iter([slow] * 25 if n == 1 else [])

                def wait(self):
                    return 0 if n > 1 else 1

                def terminate(self):
                    pass
            return Proc()

        code = runner.run_with_reconnect(
            build_command(settings, SECRET, "linux", "libx264"), SECRET, "linux",
            popen=popen, sleep=lambda _s: None, out=out, restart=restart,
            on_status=on_status, encoder="libx264",
            argv_for_attempt=lambda n, enc: build_command(
                settings_for(n), SECRET, "linux", enc))
        self.assertEqual(0, code)
        self.assertEqual(2, len(argvs))
        first, second = argvs
        self.assertIn("rec.mkv", " ".join(first))
        self.assertIn("rec-2.mkv", " ".join(second))
        self.assertNotEqual(first[first.index("-b:v") + 1], second[second.index("-b:v") + 1])
        self.assertEqual(1, len(session.decisions))
        self.assertIn("Restarting ffmpeg", out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())
        self.assertFalse(restart.is_set())

    def test_step_retargets_monitors(self):
        from lightstream.health import HealthTracker
        settings = self.settings(False)
        clock = Clock()
        advisor = AdaptiveAdvisor("720p60", settings.video_kbps, settings.fps, clock=clock)
        tracker = HealthTracker(target_kbps=settings.video_kbps)
        scaler = au.AutoScaler(au.build_ladder(au.top_step(settings)), clock, enabled=True)
        session = au.AutoScaleSession(settings, advisor, scaler, threading.Event(),
                                      lambda t: None, monitors=(tracker, advisor))
        for _ in range(40):
            clock.now += 1
            advisor.observe({"speed": 0.5, "fps": 20.0, "dropped": 0})
            session.on_status("live", {})
        step = session.decisions[0].step
        self.assertEqual(step.kbps, tracker.target_kbps)
        self.assertEqual(step.kbps, advisor.video_kbps)
        self.assertEqual(step.fps, advisor.target_fps)
        self.assertLess(step.kbps, settings.video_kbps)

    def test_restart_resets_failure_count(self):
        """crash, restart, crash must not reach max_failures=2."""
        restart = threading.Event()
        runs = []

        def popen(argv, **kw):
            runs.append(argv)
            n = len(runs)
            if n == 2:
                restart.set()

            class Proc:
                stderr = iter([])

                def wait(self):
                    return 0 if n == 4 else 1

                def terminate(self):
                    pass
            return Proc()
        code = runner.run_with_reconnect(
            ["ffmpeg"], SECRET, "linux", popen=popen, sleep=lambda _s: None,
            out=io.StringIO(), restart=restart, max_failures=2, encoder="libx264")
        self.assertEqual(0, code)
        self.assertEqual(4, len(runs))

    def run_fake(self, codes, restart, stop=None, on_launch=None, on_sleep=None):
        runs = []

        def popen(argv, **kw):
            runs.append(argv)
            n = len(runs)
            if on_launch:
                on_launch(n)

            class Proc:
                stderr = iter([])

                def wait(self):
                    return codes[n - 1]

                def terminate(self):
                    pass
            return Proc()
        code = runner.run_with_reconnect(
            ["ffmpeg"], SECRET, "linux", popen=popen,
            sleep=on_sleep or (lambda _s: None), out=io.StringIO(), restart=restart,
            stop=stop, encoder="libx264")
        return code, runs

    def test_restart_set_during_backoff_relaunches_once(self):
        """The relaunch after the sleep already applies the request; the old
        loop left the event set and relaunched a second time."""
        restart = threading.Event()
        code, runs = self.run_fake([1, 0, 0], restart,
                                   on_sleep=lambda _s: restart.set())
        self.assertEqual(0, code)
        self.assertEqual(2, len(runs))
        self.assertFalse(restart.is_set())

    def test_restart_set_at_clean_exit_is_honored_once(self):
        restart = threading.Event()
        code, runs = self.run_fake([0, 0, 0], restart,
                                   on_launch=lambda n: restart.set() if n == 1 else None)
        self.assertEqual(0, code)
        self.assertEqual(2, len(runs))
        self.assertFalse(restart.is_set())

    def test_clean_exit_without_restart_returns_zero(self):
        restart = threading.Event()
        code, runs = self.run_fake([0], restart)
        self.assertEqual(0, code)
        self.assertEqual(1, len(runs))

    def test_stop_wins_over_restart_at_exit(self):
        restart, stop = threading.Event(), threading.Event()

        def both(n):
            restart.set()
            stop.set()
        code, runs = self.run_fake([0, 0], restart, stop=stop, on_launch=both)
        self.assertEqual(0, code)
        self.assertEqual(1, len(runs))

    def test_disabled_session_never_restarts(self):
        settings = self.settings(False)
        advisor = AdaptiveAdvisor("720p60", 4000, 60)
        scaler = au.AutoScaler(au.build_ladder(au.top_step(settings)))
        restart = threading.Event()
        session = au.AutoScaleSession(settings, advisor, scaler, restart, lambda t: None)
        for _ in range(100):
            session.on_status("live", {"speed": 0.1})
        self.assertFalse(restart.is_set())
        self.assertIs(settings, session.current_settings)


if __name__ == "__main__":
    unittest.main()
