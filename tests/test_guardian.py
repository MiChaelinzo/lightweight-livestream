import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import autoscale as au
from lightstream import guardian as gd
from lightstream.adaptive import AdaptiveAdvisor
from lightstream.config import resolve_settings
from lightstream.telemetry import Sample
from lightstream.timeline import Timeline


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def sample(cpu=None, ram=None, temp=None, gpu=None):
    return Sample(cpu, ram, None, temp, gpu, None, None)


class PressureTests(unittest.TestCase):
    def test_unknown_fields_are_ignored_and_none_known_is_na(self):
        self.assertEqual(au.NEUTRAL, gd.assess_pressure(None).state)
        self.assertEqual("", gd.assess_pressure(sample()).reason)
        self.assertEqual(au.HEALTHY, gd.assess_pressure(sample(cpu=30)).state)

    def test_each_field_can_stress_with_a_plain_reason(self):
        for kwargs, text in ((dict(cpu=95), "System CPU"), (dict(ram=92), "System RAM"),
                             (dict(temp=90), "CPU temperature"), (dict(gpu=99), "GPU load")):
            signal = gd.assess_pressure(sample(**kwargs))
            self.assertEqual(au.STRESSED, signal.state)
            self.assertIn(text, signal.reason)

    def test_only_cpu_is_cpu_bound(self):
        self.assertTrue(gd.assess_pressure(sample(cpu=95)).cpu_bound)
        self.assertFalse(gd.assess_pressure(sample(ram=95)).cpu_bound)

    def test_between_levels_is_neutral_with_reason(self):
        signal = gd.assess_pressure(sample(cpu=80))
        self.assertEqual(au.NEUTRAL, signal.state)
        self.assertIn("System CPU", signal.reason)


class FakeAdvisor:
    def __init__(self, speed=1.0):
        self.speed = speed

    def is_slow(self): return False
    def dropped_pressure(self): return False
    def last_speed(self): return self.speed
    def reconnect_pressure(self): return False
    def retarget(self, *a): pass


class AssessExtraTests(unittest.TestCase):
    def test_extra_stressed_wins_and_neutral_blocks_healthy(self):
        stress = au.ScaleSignal(au.STRESSED, "pressure")
        self.assertEqual("pressure", au.assess(FakeAdvisor(), extra=[stress]).reason)
        self.assertEqual(au.NEUTRAL, au.assess(
            FakeAdvisor(), extra=[au.ScaleSignal(au.NEUTRAL, "warm")]).state)
        self.assertEqual(au.HEALTHY, au.assess(FakeAdvisor()).state)


class SurvivalTests(unittest.TestCase):
    def make(self, enabled=True):
        clock = Clock()
        return clock, gd.SurvivalMonitor(clock, enabled=enabled)

    def feed(self, clock, monitor, s, seconds):
        events = []
        for _ in range(int(seconds)):
            clock.now += 1
            event = monitor.update(s)
            if event:
                events.append(event)
        return events

    def test_off_by_default_never_acts(self):
        self.assertFalse(gd.SurvivalMonitor().enabled)
        clock, monitor = self.make(enabled=False)
        self.assertEqual([], self.feed(clock, monitor, sample(cpu=100), 500))

    def test_enters_only_after_the_hold_time(self):
        clock, monitor = self.make()
        self.assertEqual([], self.feed(clock, monitor, sample(cpu=96), 9))
        events = self.feed(clock, monitor, sample(cpu=96), 2)
        self.assertEqual([gd.ENTER], [e.kind for e in events])
        self.assertTrue(monitor.active)

    def test_ram_alone_triggers_and_short_spikes_do_not(self):
        clock, monitor = self.make()
        for _ in range(5):   # 8 s high, 1 s low: the timer restarts every time
            self.assertEqual([], self.feed(clock, monitor, sample(cpu=99), 8))
            self.assertEqual([], self.feed(clock, monitor, sample(cpu=10), 1))
        clock2, monitor2 = self.make()
        self.assertEqual(1, len(self.feed(clock2, monitor2, sample(ram=91), 12)))

    def test_exit_needs_60_calm_seconds_below_80(self):
        clock, monitor = self.make()
        self.feed(clock, monitor, sample(cpu=99), 11)
        self.assertTrue(monitor.active)
        self.assertEqual([], self.feed(clock, monitor, sample(cpu=85), 200))  # not calm
        self.assertEqual([], self.feed(clock, monitor, sample(cpu=50, ram=79), 59))
        self.assertEqual([], self.feed(clock, monitor, sample(cpu=85), 1))    # resets
        events = self.feed(clock, monitor, sample(cpu=50, ram=50), 61)
        self.assertEqual([gd.EXIT], [e.kind for e in events])
        self.assertFalse(monitor.active)

    def test_no_flapping_cooldown_and_hourly_cap(self):
        clock, monitor = self.make()
        entries = 0
        for _ in range(10):
            entries += len([e for e in self.feed(clock, monitor, sample(cpu=99), 15)
                            if e.kind == gd.ENTER])
            self.feed(clock, monitor, sample(cpu=10, ram=10), 61)
        self.assertEqual(gd.SURVIVAL_MAX_ENTRIES_PER_HOUR, entries)

    def test_unknown_readings_never_trigger_or_calm(self):
        clock, monitor = self.make()
        self.assertEqual([], self.feed(clock, monitor, sample(), 500))
        self.feed(clock, monitor, sample(cpu=99), 11)
        self.assertEqual([], self.feed(clock, monitor, sample(), 500))
        self.assertTrue(monitor.active)


class FakeSampler:
    latest = None


def make_session(survival=None, guardian=None, enabled=False, timeline=None):
    clock = Clock()
    settings = resolve_settings({"platform": "twitch", "preset": "720p60",
                                 "display": ":0.0", "noise": "light"}, {}, cpu_count=8)
    sampler = FakeSampler()
    out = io.StringIO()
    restart = threading.Event()
    advisor = AdaptiveAdvisor("balanced", settings.video_kbps, settings.fps)
    session = au.AutoScaleSession(
        settings, advisor, au.AutoScaler(au.build_ladder(au.top_step(settings)), clock,
                                         enabled=enabled),
        restart, out.write, sampler, survival=survival, guardian=guardian,
        timeline=timeline, monitors=(advisor,) + ((guardian,) if guardian else ()))
    return clock, session, sampler, restart, out, settings


class SessionTests(unittest.TestCase):
    def test_nothing_runs_with_everything_off(self):
        clock, session, sampler, restart, out, settings = make_session()
        sampler.latest = sample(cpu=100, ram=100)
        for _ in range(300):
            clock.now += 1
            session.on_status("live", {"speed": 0.3})
        self.assertFalse(restart.is_set())
        self.assertEqual("", out.getvalue())
        self.assertEqual(settings, session.current_settings)

    def test_survival_enters_keeps_size_and_audio_then_restores(self):
        clock = Clock()
        monitor = gd.SurvivalMonitor(clock, enabled=True)
        _, session, sampler, restart, out, settings = make_session(monitor)
        monitor._clock = session.scaler._clock = clock
        sampler.latest = sample(cpu=99)
        for _ in range(12):
            clock.now += 1
            session.on_status("live", {"speed": 1.0})
        self.assertTrue(restart.is_set())
        now = session.current_settings
        self.assertTrue(session.in_survival)
        self.assertEqual((settings.width, settings.height), (now.width, now.height))
        self.assertEqual(settings.audio_kbps, now.audio_kbps)
        self.assertEqual("light", now.noise)
        self.assertLess(now.fps * 1000 + now.video_kbps, settings.fps * 1000 + settings.video_kbps)
        self.assertIn("brief interruption", out.getvalue())
        restart.clear()
        sampler.latest = sample(cpu=20, ram=20)
        for _ in range(125):
            clock.now += 1
            session.on_status("live", {"speed": 1.0})
        self.assertFalse(session.in_survival)
        self.assertEqual(settings, session.current_settings)
        self.assertTrue(restart.is_set())

    def test_manual_hold_pauses_survival(self):
        clock = Clock()
        monitor = gd.SurvivalMonitor(clock, enabled=True)
        _, session, sampler, restart, out, settings = make_session(monitor)
        monitor._clock = clock
        session.manual_hold = True
        sampler.latest = sample(cpu=99)
        for _ in range(30):
            clock.now += 1
            session.on_status("live", {"speed": 1.0})
        self.assertFalse(restart.is_set())

    def test_guardian_pressure_steps_down_and_never_flaps(self):
        clock = Clock()
        guardian = gd.Guardian(4000, clock)
        timeline = Timeline(clock)
        _, session, sampler, restart, out, settings = make_session(
            guardian=guardian, enabled=True, timeline=timeline)
        session.scaler._clock = clock
        sampler.latest = sample(cpu=93)
        steps = 0
        for _ in range(300):   # alternating stress and calm every second
            clock.now += 1
            sampler.latest = sample(cpu=93 if int(clock.now) % 2 else 20)
            session.on_status("live", {"speed": 1.0})
        self.assertEqual([], session.decisions)   # NEUTRAL/HEALTHY mix resets timers? stress too short
        for _ in range(25):
            clock.now += 1
            sampler.latest = sample(cpu=93)
            session.on_status("live", {"speed": 1.0})
        self.assertEqual(1, len(session.decisions))
        self.assertIn("System CPU", session.decisions[0].reason)
        self.assertEqual("guardian step", timeline.events[-1].kind)
        self.assertIn("brief interruption", out.getvalue())

    def test_guardian_trend_reason_is_used(self):
        clock = Clock()
        guardian = gd.Guardian(4000, clock)
        _, session, sampler, restart, out, settings = make_session(
            guardian=guardian, enabled=True)
        session.scaler._clock = clock
        for t in range(120):
            clock.now += 1
            speed = max(0.9, 1.30 - 0.004 * t)
            session.on_status("live", {"speed": speed, "bitrate_kbps": 4000 * min(1, speed)})
        reasons = [d.reason for d in session.decisions]
        self.assertTrue(any("Predicted trend" in r for r in reasons), reasons)

    def test_reconnects_are_recorded_only_with_a_timeline(self):
        clock = Clock()
        timeline = Timeline(clock)
        _, session, *_ = make_session(timeline=timeline)
        session.on_status("reconnecting", None)
        self.assertEqual("reconnect", timeline.events[-1].kind)


if __name__ == "__main__":
    unittest.main()


class CliFlagTests(unittest.TestCase):
    KEY = "live_SECRET_key_123"

    def run_cli(self, argv):
        import tempfile
        from unittest import mock
        from lightstream import cli
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            env = {"HOME": d, "XDG_CONFIG_HOME": d, "STREAM_KEY": self.KEY}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(cli, "detect_gpu_names", lambda _o: []), \
                    mock.patch.object(cli, "detect_os", lambda: "linux"), \
                    mock.patch.object(cli, "find_ffmpeg", lambda: None):
                try:
                    code = cli.main(argv, out)
                except SystemExit as exc:
                    code = exc.code
        return code, out.getvalue()

    def test_dry_run_with_flags_matches_plain_argv_and_hides_the_key(self):
        code, plain = self.run_cli(["start", "--dry-run"])
        code2, flagged = self.run_cli(["start", "--dry-run", "--guardian",
                                       "--auto-survival"])
        self.assertEqual((0, 0), (code, code2))
        self.assertEqual(plain, flagged)
        self.assertNotIn(self.KEY, flagged)

    def test_help_lists_both_flags(self):
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.run_cli(["start", "--help"])
        text = buffer.getvalue()
        self.assertIn("--guardian", text)
        self.assertIn("--auto-survival", text)
