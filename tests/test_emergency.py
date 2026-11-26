import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import cli
from lightstream import gui_controller as gc
from lightstream import gui_pages as gp
from lightstream import runner
from lightstream.command import build_command
from lightstream.config import resolve_settings
from lightstream.emergency import (WEAK_BITRATE_FACTOR, WEAK_BUFSIZE_SECONDS,
                                   WEAK_KEYINT_SECONDS, emergency_settings,
                                   failover_settings, weak_connection_settings)
from lightstream.hardware import LEAN_BUFSIZE_SECONDS
from lightstream.perf_profiles import POTATO_THREAD_CAP
from lightstream.platforms import validate_backup_url
from lightstream.runner import (FAILOVER_AFTER_FAILURES, STATUS_FAILOVER,
                                format_command, redact, run_with_reconnect)

KEY = "live_SECRET_key_123"
BACKUP = "rtmp://backup.example.com/live"
FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")


def base(**cli_values):
    values = {"platform": "twitch", "preset": "720p60", "display": ":0.0"}
    values.update(cli_values)
    return resolve_settings(values, {}, cpu_count=8)


def argv_of(settings, record_path=None):
    return build_command(settings, KEY, "linux", "libx264", "ffmpeg", record_path)


class EmergencySettingsTests(unittest.TestCase):
    def test_safest_values_from_potato(self):
        s = emergency_settings(base())
        self.assertEqual((640, 360, 24, 700), (s.width, s.height, s.fps, s.video_kbps))
        self.assertEqual("ultrafast", s.x264_preset)
        self.assertEqual(POTATO_THREAD_CAP, s.threads)
        self.assertEqual(LEAN_BUFSIZE_SECONDS, s.bufsize_seconds)
        self.assertEqual("off", s.noise)
        self.assertIsNone(s.audio_filter)
        self.assertIsNone(s.scene)

    def test_constant_size_keeps_picture_and_audio_chain(self):
        original = base(noise="light")._replace(audio_filter="highpass=f=80")
        s = emergency_settings(original, constant_size=True)
        self.assertEqual((original.width, original.height), (s.width, s.height))
        self.assertEqual(original.audio_kbps, s.audio_kbps)
        self.assertEqual("light", s.noise)
        self.assertEqual("highpass=f=80", s.audio_filter)
        self.assertEqual((24, 700, "ultrafast"), (s.fps, s.video_kbps, s.x264_preset))
        self.assertIsNone(s.scene)
        self.assertEqual(LEAN_BUFSIZE_SECONDS, s.bufsize_seconds)

    def test_default_emergency_is_unchanged_by_the_new_option(self):
        self.assertEqual(emergency_settings(base()),
                         emergency_settings(base(), constant_size=False))

    def test_never_raises_a_lower_value(self):
        s = emergency_settings(base(preset="potato", bitrate=400, fps=15))
        self.assertEqual((400, 15), (s.video_kbps, s.fps))

    def test_deterministic(self):
        self.assertEqual(emergency_settings(base()), emergency_settings(base()))

    def test_argv_uses_small_buffer_and_threads(self):
        argv = argv_of(emergency_settings(base()))
        self.assertEqual("350k", argv[argv.index("-bufsize") + 1])
        self.assertEqual(str(POTATO_THREAD_CAP), argv[argv.index("-threads") + 1])


class WeakConnectionTests(unittest.TestCase):
    def test_lower_bitrate_short_keyint_long_buffer(self):
        before = base()
        s = weak_connection_settings(before)
        self.assertEqual(int(before.video_kbps * WEAK_BITRATE_FACTOR), s.video_kbps)
        self.assertEqual(WEAK_KEYINT_SECONDS, s.keyint_seconds)
        self.assertEqual(WEAK_BUFSIZE_SECONDS, s.bufsize_seconds)
        argv = argv_of(s)
        self.assertEqual(str(s.fps * WEAK_KEYINT_SECONDS), argv[argv.index("-g") + 1])
        self.assertEqual("%dk" % (s.video_kbps * WEAK_BUFSIZE_SECONDS),
                         argv[argv.index("-bufsize") + 1])

    def test_known_upload_lowers_further(self):
        slow = weak_connection_settings(base(), upload_kbps=1000)
        self.assertLess(slow.video_kbps, weak_connection_settings(base()).video_kbps)
        self.assertLessEqual(slow.video_kbps, 700)

    def test_never_raises_bitrate(self):
        self.assertEqual(300, weak_connection_settings(base(bitrate=300)).video_kbps)


class BackupUrlTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(BACKUP, validate_backup_url(BACKUP))
        validate_backup_url("rtmps://b.example.com:443/app")
        self.assertEqual(BACKUP, validate_backup_url(BACKUP + "\n"))
        with self.assertRaises(ValueError):
            validate_backup_url("rtmp://b.example.com/a pp")

    def test_rejects_bad_scheme_key_and_spaces(self):
        for bad in ("http://x/app", "rtmp:///app", "", "rtmp://h/app/KEY123",
                    "rtmp://h/app?key=abc", "rtmp://h/a pp", "rtmp://h/a|b"):
            with self.assertRaises(ValueError, msg=bad):
                validate_backup_url(bad)

    def test_config_validates_and_failover_uses_it(self):
        s = base(backup_url=BACKUP)
        self.assertEqual(BACKUP, s.backup_url)
        argv = argv_of(failover_settings(s))
        self.assertEqual(BACKUP + "/" + KEY, argv[-1])
        with self.assertRaises(ValueError):
            base(backup_url="http://nope")

    def test_failover_needs_backup(self):
        with self.assertRaises(ValueError):
            failover_settings(base())


class FakeProc:
    def __init__(self, code, lines=()):
        self.stderr, self._code = iter(lines), code

    def wait(self):
        return self._code


class FailoverRunnerTests(unittest.TestCase):
    def run_sequence(self, codes, durations=None, backup=True, out=None):
        """Run with fake processes; return (code, launched argvs, statuses)."""
        launched, statuses = [], []
        procs = iter(FakeProc(c, ["error %s\n" % KEY] if c else []) for c in codes)
        now = [0.0]
        durations = iter(durations or [])

        def popen(argv, **kw):
            launched.append(argv)
            now[0] += next(durations, 1.0)
            return next(procs)
        code = run_with_reconnect(
            ["primary"], KEY, "linux", popen=popen, sleep=lambda s: None,
            clock=lambda: now[0], out=out or io.StringIO(),
            on_status=lambda s, d=None: statuses.append((s, d)),
            argv_for_attempt=lambda n, enc: ["primary", str(n)],
            backup_argv_for_attempt=(lambda n, enc: ["backup", str(n)]) if backup else None)
        return code, launched, statuses

    def test_switches_after_n_quick_failures_in_order(self):
        n = FAILOVER_AFTER_FAILURES
        code, launched, statuses = self.run_sequence([1] * n + [0])
        self.assertEqual(0, code)
        self.assertEqual(["primary"] * n + ["backup"], [a[0] for a in launched])
        self.assertIn((STATUS_FAILOVER, "backup"), statuses)

    def test_healthy_run_resets_the_count(self):
        n = FAILOVER_AFTER_FAILURES
        # n-1 quick failures, one healthy (long) failure, n-1 quick failures, success
        codes = [1] * (n - 1) + [1] + [1] * (n - 1) + [0]
        durations = [1.0] * (n - 1) + [runner.HEALTHY_RUN_SECONDS + 5] + [1.0] * n
        code, launched, statuses = self.run_sequence(codes, durations)
        self.assertEqual(0, code)
        self.assertEqual({"primary"}, {a[0] for a in launched})
        self.assertNotIn(STATUS_FAILOVER, [s for s, _ in statuses])

    def test_returns_to_primary_when_backup_fails_too(self):
        n = FAILOVER_AFTER_FAILURES
        code, launched, statuses = self.run_sequence([1] * (2 * n) + [0])
        self.assertEqual(["primary"] * n + ["backup"] * n + ["primary"],
                         [a[0] for a in launched])
        self.assertEqual([("failover", "backup"), ("failover", "primary")],
                         [(s, d) for s, d in statuses if s == STATUS_FAILOVER])

    def test_failover_still_gives_up_after_max_failures(self):
        launched = []

        def popen(argv, **kw):
            launched.append(argv)
            if len(launched) > 50:
                raise AssertionError("never gave up")
            return FakeProc(1, [])
        now = [0.0]
        code = run_with_reconnect(
            ["primary"], KEY, "linux", popen=popen, sleep=lambda s: None,
            clock=lambda: now[0], out=io.StringIO(), max_failures=5,
            argv_for_attempt=lambda n, enc: ["primary", str(n)],
            backup_argv_for_attempt=lambda n, enc: ["backup", str(n)])
        self.assertEqual(1, code)
        self.assertEqual(5, len(launched))

    def test_no_failover_without_backup(self):
        _, launched, statuses = self.run_sequence([1] * 5 + [0], backup=False)
        self.assertEqual({"primary"}, {a[0] for a in launched})
        self.assertNotIn(STATUS_FAILOVER, [s for s, _ in statuses])

    def test_encoder_problems_do_not_trigger_failover(self):
        procs = iter([FakeProc(1, ["Error while opening encoder\n"]) for _ in range(4)]
                     + [FakeProc(0)])
        launched = []

        def popen(argv, **kw):
            launched.append(argv)
            return next(procs)
        run_with_reconnect(["primary"], KEY, "linux", popen=popen,
                           sleep=lambda s: None, clock=lambda: 0.0, out=io.StringIO(),
                           argv_for_attempt=lambda n, e: ["primary"],
                           backup_argv_for_attempt=lambda n, e: ["backup"])
        self.assertNotIn(["backup"], launched)

    def test_key_never_in_output(self):
        out = io.StringIO()
        self.run_sequence([1] * FAILOVER_AFTER_FAILURES + [0], out=out)
        self.assertNotIn(KEY, out.getvalue())
        self.assertIn("backup", out.getvalue())

    def test_recording_continues_in_a_new_file_on_backup(self):
        from lightstream.command import numbered_recording_path
        s = base(backup_url=BACKUP)
        with tempfile.TemporaryDirectory() as folder:
            s = s._replace(record_to=os.path.join(folder, "a.mkv"))

            def attempt(n):
                return s._replace(record_to=numbered_recording_path(s.record_to, n))
            argv = build_command(failover_settings(attempt(3)), KEY, "linux",
                                 "libx264", "ffmpeg")
        self.assertIn("a-4.mkv", argv[-1])
        self.assertIn(BACKUP + "/" + KEY, argv[-1])
        self.assertNotIn(KEY, format_command(argv, KEY))


class CliTests(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        old = dict(os.environ)
        os.environ["STREAM_KEY"] = KEY
        try:
            code = cli.main(argv, out=out)
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, out.getvalue()

    def test_dry_run_emergency(self):
        code, text = self.run_cli(["start", "--preset", "720p60", "--emergency",
                                   "--dry-run"])
        self.assertEqual(0, code)
        self.assertIn("-b:v 700k", text)
        self.assertIn("640:360", text)
        self.assertNotIn(KEY, text)

    def test_dry_run_weak_connection_and_backup(self):
        code, text = self.run_cli(["start", "--preset", "balanced", "--weak-connection",
                                   "--backup-url", BACKUP, "--dry-run"])
        self.assertEqual(0, code)
        self.assertIn("-b:v 1500k", text)
        self.assertIn("Backup ingest: " + BACKUP, text)
        self.assertNotIn(KEY, text)

    def test_bad_backup_url_is_a_plain_error(self):
        code, text = self.run_cli(["start", "--backup-url", "http://x", "--dry-run"])
        self.assertEqual(2, code)
        self.assertIn("backup address", text)


class ControllerTests(unittest.TestCase):
    def make(self, calls):
        def fake_runner(argv, key, os_name, **kw):
            calls.append((argv, kw))
            kw["on_status"](runner.STATUS_LIVE, {"speed": 1.0})
            kw["stop"].wait(5)
            return 0
        return gc.StreamController(
            runner=fake_runner, which=lambda _n: "/bin/ffmpeg", os_name="linux",
            probe=lambda _f: set(), pick_encoder=lambda *a, **k: "libx264")

    def test_emergency_restarts_with_safe_settings_and_restores(self):
        calls = []
        c = self.make(calls)
        prefs = {"platform": "twitch", "preset": "720p60", "auto_scale": True}
        c.start(prefs, KEY)
        c._thread.join(0.3)
        kw = calls[0][1]
        self.assertTrue(c._scale.scaler.enabled)
        message = c.emergency()
        self.assertIn("Emergency mode is on", message)
        self.assertTrue(kw["restart"].is_set())
        self.assertFalse(c._scale.scaler.enabled)  # cannot undo the step
        safe = kw["argv_for_attempt"](1, "libx264")
        self.assertEqual("700k", safe[safe.index("-b:v") + 1])
        self.assertIn("EMERGENCY", gc.BANNER_EMERGENCY[0])
        self.assertIn("already", c.emergency())
        kw["restart"].clear()
        c.restore_after_emergency()
        self.assertTrue(kw["restart"].is_set())
        self.assertTrue(c._scale.scaler.enabled)
        back = kw["argv_for_attempt"](2, "libx264")
        self.assertEqual("4000k", back[back.index("-b:v") + 1])
        c.stop()
        self.assertNotIn(KEY, "".join(c._log))

    def test_emergency_needs_a_running_stream(self):
        self.assertIn("while you are streaming", self.make([]).emergency())

    def test_failover_wiring_and_banner(self):
        calls = []
        c = self.make(calls)
        c.start({"platform": "twitch", "preset": "light", "backup_url": BACKUP}, KEY)
        c._thread.join(0.3)
        backup_argv = calls[0][1]["backup_argv_for_attempt"](1, "libx264")
        c.stop()
        self.assertEqual(BACKUP + "/" + KEY, backup_argv[-1])
        self.assertEqual(gc.BANNER_FAILOVER, gc.banner_for(STATUS_FAILOVER))

    def test_no_backup_means_no_seam(self):
        calls = []
        c = self.make(calls)
        c.start({"platform": "twitch", "preset": "light"}, KEY)
        c._thread.join(0.3)
        c.stop()
        self.assertIsNone(calls[0][1]["backup_argv_for_attempt"])

    def test_button_label(self):
        self.assertNotEqual(gp.emergency_button_label(True),
                            gp.emergency_button_label(False))


@unittest.skipUnless(FFMPEG and os.path.exists(FFMPEG), "LIGHTSTREAM_TEST_FFMPEG not set")
class RealFfmpegArgvTests(unittest.TestCase):
    """The emergency, weak connection and backup argv are accepted by real ffmpeg.
    Capture needs a display, so the screen input is replaced by a test source;
    all output options are kept and written to a file. Real ingest servers are
    UNVERIFIED."""

    def run_ffmpeg(self, settings):
        argv = build_command(settings, "test", "linux", "libx264", FFMPEG,
                             record_path="PLACEHOLDER")
        out_index = argv.index("-i")
        # swap the x11grab/pulse inputs for lavfi sources, keep every output option
        tail_start = argv.index("-vf")
        head = [FFMPEG, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=%d" % settings.fps,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        self.assertGreater(tail_start, out_index)
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "out.mkv")
            rest = argv[tail_start:-1] + [target]
            rest[rest.index("-t") + 1] = "1"
            result = subprocess.run(
                head + ["-map", "0:v", "-map", "1:a"] + rest,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=60)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(os.path.getsize(target) > 0)

    def test_emergency(self):
        self.run_ffmpeg(emergency_settings(base()))

    def test_weak_connection(self):
        self.run_ffmpeg(weak_connection_settings(base(), upload_kbps=2000))

    def test_both_modes(self):
        self.run_ffmpeg(weak_connection_settings(emergency_settings(base())))

    def test_backup_settings(self):
        self.run_ffmpeg(failover_settings(base(backup_url=BACKUP)))


if __name__ == "__main__":
    unittest.main()
