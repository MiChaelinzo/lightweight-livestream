import io
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import cli, encoders
from lightstream.command import build_command
from lightstream.config import (config_path, detect_os, load_file_config,
                                resolve_key,
                                resolve_settings, write_example_config)
from lightstream.encoders import (choose_encoder, choose_working_encoder,
                                  encoder_works, parse_encoders)
from lightstream.platforms import (capture_inputs, ingest_url,
                                   parse_audio_devices)
from lightstream.presets import PRESETS, get_preset, parse_resolution
from lightstream.runner import (backoff_delay, format_command, is_lagging,
                                mentions_encoder_problem,
                                parse_progress, priority_kwargs, redact,
                                run_with_reconnect)

KEY = "live_SECRET123"
FFMPEG_TEXT = """Encoders:
 V..... libx264              libx264 H.264
 V....D h264_nvenc           NVIDIA NVENC H.264
 A....D aac                  AAC
"""


def settings(**cli_args):
    return resolve_settings(cli_args, {})


class PresetTests(unittest.TestCase):
    def test_presets_ordered_by_cost(self):
        self.assertLess(PRESETS["potato"].video_kbps, PRESETS["light"].video_kbps)
        self.assertEqual((640, 360, 24), (PRESETS["potato"].width,
                                          PRESETS["potato"].height,
                                          PRESETS["potato"].fps))

    def test_unknown_preset(self):
        with self.assertRaises(ValueError):
            get_preset("ultra")

    def test_resolution(self):
        self.assertEqual((854, 480), parse_resolution("854x480"))
        for bad in ("abc", "853x480", "0x0"):
            with self.assertRaises(ValueError):
                parse_resolution(bad)


class EncoderTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual({"libx264", "h264_nvenc"}, parse_encoders(FFMPEG_TEXT))

    def test_choice(self):
        avail = parse_encoders(FFMPEG_TEXT)
        self.assertEqual("h264_nvenc", choose_encoder(avail))
        self.assertEqual("libx264", choose_encoder(avail, prefer_hardware=False))
        self.assertEqual("libx264", choose_encoder(set()))
        self.assertEqual("h264_qsv", choose_encoder(avail, forced="h264_qsv"))


class FakeRun:
    """Fake subprocess.run: only the listed encoders pass the test encode."""
    def __init__(self, working):
        self.working = working

    def __call__(self, argv, **kwargs):
        code = 0 if argv[argv.index("-c:v") + 1] in self.working else 1
        return type("R", (), {"returncode": code})()


class WorkingEncoderTests(unittest.TestCase):
    avail = {"h264_nvenc", "h264_qsv", "libx264"}

    def setUp(self):
        encoders._WORKS_CACHE.clear()

    def test_probe_results_are_cached(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return type("R", (), {"returncode": 0})()
        encoder_works("ffmpeg", "h264_qsv", run)
        encoder_works("ffmpeg", "h264_qsv", run)
        self.assertEqual(1, len(calls))

    def test_skips_hardware_that_fails_test_encode(self):
        self.assertFalse(encoder_works("ffmpeg", "h264_nvenc", FakeRun(set())))
        self.assertEqual("h264_qsv", choose_working_encoder(
            "ffmpeg", self.avail, run=FakeRun({"h264_qsv"})))

    def test_falls_back_to_software(self):
        self.assertEqual("libx264", choose_working_encoder(
            "ffmpeg", self.avail, run=FakeRun(set())))

    def test_forced_and_software_skip_probe(self):
        self.assertEqual("h264_amf", choose_working_encoder(
            "ffmpeg", self.avail, forced="h264_amf", run=FakeRun(set())))
        self.assertEqual("libx264", choose_working_encoder(
            "ffmpeg", self.avail, prefer_hardware=False, run=FakeRun(set())))

    def test_missing_binary_means_not_working(self):
        def boom(*a, **k):
            raise OSError("gone")
        self.assertFalse(encoder_works("ffmpeg", "h264_nvenc", boom))


class CommandTests(unittest.TestCase):
    def test_keeps_aspect_ratio(self):
        joined = " ".join(build_command(settings(), KEY, "linux", "libx264"))
        self.assertIn("force_original_aspect_ratio=decrease,pad=854:480", joined)

    def test_deterministic(self):
        s = settings(preset="potato")
        self.assertEqual(build_command(s, KEY, "linux", "libx264"),
                         build_command(s, KEY, "linux", "libx264"))

    def test_low_latency_flags_linux(self):
        argv = build_command(settings(preset="potato"), KEY, "linux", "libx264")
        joined = " ".join(argv)
        for flag in ("-fflags nobuffer", "-bf 0", "-tune zerolatency",
                     "-preset ultrafast", "-g 48", "-flush_packets 1",
                     "-flvflags no_duration_filesize", "-f x11grab", "-f pulse",
                     "-b:v 700k", "scale=640:360"):
            self.assertIn(flag, joined)
        self.assertEqual("rtmp://live.twitch.tv/app/" + KEY, argv[-1])

    def test_windows_window_capture_and_silent_audio(self):
        s = settings(window="BlueStacks")
        argv = build_command(s, KEY, "windows", "libx264")
        self.assertIn("title=BlueStacks", argv)
        self.assertIn("gdigrab", argv)
        self.assertIn("anullsrc=r=44100:cl=stereo", argv)

    def test_windows_audio_device(self):
        argv = build_command(settings(audio_device="Mic"), KEY, "windows", "libx264")
        self.assertIn("audio=Mic", argv)
        self.assertNotIn("anullsrc=r=44100:cl=stereo", argv)

    def test_macos(self):
        argv = build_command(settings(), KEY, "macos", "h264_videotoolbox")
        self.assertIn("avfoundation", argv)
        self.assertIn("h264_videotoolbox", argv)

    def test_window_unsupported_off_windows(self):
        with self.assertRaises(ValueError):
            capture_inputs("linux", 30, window="x")

    def test_hardware_encoders(self):
        for enc in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi"):
            self.assertIn(enc, build_command(settings(), KEY, "linux", enc))
        vaapi = " ".join(build_command(settings(), KEY, "linux", "h264_vaapi"))
        self.assertIn("hwupload", vaapi)
        with self.assertRaises(ValueError):
            build_command(settings(), KEY, "linux", "nope")

    def test_youtube_and_custom_urls(self):
        self.assertEqual("rtmp://a.rtmp.youtube.com/live2/k", ingest_url("youtube", "k"))
        self.assertEqual("rtmp://h/app/k", ingest_url("custom", "k", "rtmp://h/app/"))
        with self.assertRaises(ValueError):
            ingest_url("custom", "k")
        with self.assertRaises(ValueError):
            ingest_url("other", "k")


DSHOW_TEXT = """[dshow @ 0x1] DirectShow video devices (some may be both video and audio devices)
[dshow @ 0x1]  "Integrated Camera"
[dshow @ 0x1]     Alternative name "@device_pnp_x"
[dshow @ 0x1] DirectShow audio devices
[dshow @ 0x1]  "Microphone (Realtek)" (audio)
[dshow @ 0x1]  "Stereo Mix (Realtek)" (audio)
"""
AVF_TEXT = """[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] [1] Capture screen 0
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] MacBook Microphone
"""


class AudioTests(unittest.TestCase):
    def test_parse_dshow_and_avfoundation(self):
        self.assertEqual(["Microphone (Realtek)", "Stereo Mix (Realtek)"],
                         parse_audio_devices(DSHOW_TEXT))
        self.assertEqual(["0 = MacBook Microphone"], parse_audio_devices(AVF_TEXT))
        self.assertEqual([], parse_audio_devices("nothing here"))

    def test_mute_opens_no_audio_device(self):
        for os_name, marker in (("linux", "pulse"), ("windows", "dshow"),
                                ("macos", "0")):
            argv = build_command(settings(mute=True, audio_device="Mic"), KEY,
                                 os_name, "libx264")
            self.assertNotIn(marker if marker != "0" else "1:0", argv)
            self.assertIn("anullsrc=r=44100:cl=stereo", argv)

    def test_macos_mute_uses_none(self):
        self.assertIn("1:none", capture_inputs("macos", 30, mute=True)[0])


class TestLocalTests(unittest.TestCase):
    def test_record_instead_of_live(self):
        argv = build_command(settings(), KEY, "linux", "libx264",
                             record_path="t.mkv")
        self.assertEqual(["-t", "10", "-f", "matroska", "-y", "t.mkv"], argv[-6:])
        self.assertFalse(any("rtmp" in a for a in argv))

    def test_cli_dry_run_test_local_needs_no_key(self):
        out = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != "STREAM_KEY"}
        old = os.environ.copy()
        os.environ.clear()
        os.environ.update(env)
        try:
            code = cli.main(["start", "--dry-run", "--test-local", "x.mkv"], out)
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(0, code)
        self.assertIn("x.mkv", out.getvalue())


class EncoderErrorTests(unittest.TestCase):
    def test_known_encoder_failures_match(self):
        for line in ("[h264_nvenc @ 0x1] OpenEncodeSessionEx failed: out of memory",
                     "Cannot load nvcuda.dll",
                     "Error while opening encoder for output stream #0:0",
                     "Error creating a MFX session: -9."):
            self.assertTrue(mentions_encoder_problem(line), line)

    def test_network_errors_do_not_match(self):
        for line in ("Connection to tcp://live.twitch.tv:1935 failed: Connection refused",
                     "av_interleaved_write_frame(): Broken pipe",
                     "rtmp://x/live_123: Input/output error",
                     "Encoder (codec aac) not found for output"):
            self.assertFalse(mentions_encoder_problem(line), line)


class RedactionTests(unittest.TestCase):
    def test_redact(self):
        self.assertNotIn(KEY, redact("url " + KEY, KEY))

    def test_format_command_hides_key(self):
        argv = build_command(settings(), KEY, "linux", "libx264")
        text = format_command(argv, KEY)
        self.assertNotIn(KEY, text)
        self.assertIn("****", text)


class ConfigTests(unittest.TestCase):
    def test_precedence_cli_over_file_over_preset(self):
        file_cfg = {"preset": "potato", "fps": 20, "bitrate": 500}
        s = resolve_settings({"fps": 30, "preset": None, "bitrate": None}, file_cfg)
        self.assertEqual(30, s.fps)
        self.assertEqual(500, s.video_kbps)
        self.assertEqual(640, s.width)

    def test_key_from_env_then_prompt(self):
        self.assertEqual(KEY, resolve_key({"STREAM_KEY": " %s " % KEY}, None))
        self.assertEqual("typed", resolve_key({}, lambda _: "typed"))
        with self.assertRaises(ValueError):
            resolve_key({}, lambda _: "  ")

    def test_rejects_invalid_numbers(self):
        for bad in ({"fps": 0}, {"fps": -5}, {"bitrate": 0}, {"bitrate": -1},
                    {"fps": "abc"}):
            with self.assertRaises(ValueError):
                resolve_settings(bad, {})
        with self.assertRaises(ValueError):
            resolve_settings({}, {"fps": 0})

    def test_config_must_be_object(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as fh:
                fh.write("[1, 2]")
            with self.assertRaises(ValueError):
                load_file_config(path)

    def test_paths_and_example(self):
        self.assertTrue(config_path("windows", {"APPDATA": "C:\\A"}).startswith("C:\\A"))
        self.assertIn("/x/", config_path("linux", {"XDG_CONFIG_HOME": "/x"}))
        self.assertEqual("windows", detect_os("win32"))
        self.assertEqual("macos", detect_os("darwin"))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "config.json")
            write_example_config(path)
            with open(path) as fh:
                self.assertNotIn("key", fh.read().lower())
            with self.assertRaises(FileExistsError):
                write_example_config(path)


class FakeProc:
    def __init__(self, code, lines):
        self.stderr, self._code = iter(lines), code

    def wait(self):
        return self._code


class RunnerTests(unittest.TestCase):
    def test_backoff(self):
        self.assertEqual([1, 2, 4, 8], [backoff_delay(n) for n in (1, 2, 3, 4)])
        self.assertEqual(30, backoff_delay(50))

    def test_priority(self):
        self.assertEqual({"creationflags": 0x4000}, priority_kwargs("windows"))
        self.assertIn("preexec_fn", priority_kwargs("linux"))

    def test_reconnect_and_redacted_output(self):
        procs = iter([FakeProc(1, ["fail " + KEY + "\n"]), FakeProc(1, []),
                      FakeProc(0, [])])
        sleeps, out = [], io.StringIO()
        code = run_with_reconnect(["ffmpeg"], KEY, "windows",
                                  popen=lambda *a, **k: next(procs),
                                  sleep=sleeps.append, clock=lambda: 0, out=out)
        self.assertEqual(0, code)
        self.assertEqual([1, 2], sleeps)
        self.assertNotIn(KEY, out.getvalue())

    def test_gives_up(self):
        code = run_with_reconnect(["ffmpeg"], KEY, "windows",
                                  popen=lambda *a, **k: FakeProc(3, []),
                                  sleep=lambda s: None, clock=lambda: 0,
                                  out=io.StringIO(), max_failures=3)
        self.assertEqual(3, code)


class StoppableProc(FakeProc):
    terminated = False

    def terminate(self):
        self.terminated = True


class ReliabilityTests(unittest.TestCase):
    def run_runner(self, procs, **kwargs):
        procs = iter(procs)
        events, out = [], io.StringIO()
        kwargs.setdefault("sleep", lambda s: None)
        code = run_with_reconnect(
            ["ffmpeg"], KEY, "windows", popen=lambda *a, **k: next(procs),
            clock=lambda: 0, out=out,
            on_status=lambda state, detail=None: events.append((state, detail)),
            **kwargs)
        return code, events, out.getvalue()

    def test_status_sequence_and_live_health(self):
        line = "frame=1 fps=30 bitrate=900.5kbits/s speed=1.0x\n"
        code, events, _ = self.run_runner(
            [FakeProc(1, []), FakeProc(0, [line])])
        self.assertEqual(0, code)
        self.assertEqual(
            [("starting", None), ("reconnecting", 1), ("starting", None),
             ("live", {"fps": 30.0, "bitrate_kbps": 900.5, "speed": 1.0}),
             ("stopped", None)], events)

    def test_failed_status_and_keep_trying_forever(self):
        code, events, _ = self.run_runner(
            [FakeProc(3, []) for _ in range(3)], max_failures=3)
        self.assertEqual(3, code)
        self.assertEqual(("failed", 3), events[-1])
        # max_failures=None never gives up: it only ends on a clean exit
        procs = [FakeProc(1, []) for _ in range(20)] + [FakeProc(0, [])]
        code, _, _ = self.run_runner(procs, max_failures=None)
        self.assertEqual(0, code)

    def test_stop_event_terminates_and_returns_zero(self):
        stop = threading.Event()
        proc = StoppableProc(1, [])
        stop.set()
        code, events, text = self.run_runner([proc], stop=stop)
        self.assertEqual(0, code)
        self.assertEqual(("stopped", None), events[-1])
        self.assertIn("Stopped.", text)

    def test_stop_during_reconnect_wait(self):
        stop = threading.Event()
        code, events, _ = self.run_runner(
            [FakeProc(1, [])], stop=stop, sleep=lambda d: stop.set())
        self.assertEqual(0, code)
        self.assertEqual("stopped", events[-1][0])

    def test_hardware_encoder_falls_back_to_libx264(self):
        seen = []
        def factory(encoder):
            seen.append(encoder)
            return ["ffmpeg", encoder]
        launched = []
        err = ["Error while opening encoder h264_nvenc\n"]
        procs = iter([FakeProc(1, err), FakeProc(1, err), FakeProc(0, [])])
        def popen(argv, **kwargs):
            launched.append(argv)
            return next(procs)
        out = io.StringIO()
        code = run_with_reconnect(
            ["ffmpeg", "h264_nvenc"], KEY, "windows", popen=popen,
            sleep=lambda s: None, clock=lambda: 0, out=out,
            encoder="h264_nvenc", argv_factory=factory)
        self.assertEqual(0, code)
        self.assertEqual(["libx264"], seen)
        self.assertEqual(["ffmpeg", "libx264"], launched[-1])
        self.assertIn("Switching to libx264", out.getvalue())

    def test_network_failures_do_not_trigger_fallback(self):
        err = ["Connection refused\n"]
        code, _, _ = self.run_runner(
            [FakeProc(1, err) for _ in range(3)], max_failures=3,
            encoder="h264_nvenc",
            argv_factory=lambda e: self.fail("no fallback"))
        self.assertEqual(1, code)

    def test_software_encoder_never_falls_back(self):
        code, events, _ = self.run_runner(
            [FakeProc(1, []) for _ in range(3)], max_failures=3,
            encoder="libx264", argv_factory=lambda e: self.fail("no fallback"))
        self.assertEqual(1, code)

    def test_health_parser(self):
        health = parse_progress(
            "frame=  99 fps= 28 q=-1.0 size=N/A time=00:00:03 "
            "bitrate=1500.2kbits/s speed=0.80x")
        self.assertEqual({"fps": 28.0, "bitrate_kbps": 1500.2, "speed": 0.8},
                         health)
        self.assertTrue(is_lagging(health))
        self.assertFalse(is_lagging({"speed": 1.0}))
        self.assertEqual({}, parse_progress("Connection refused"))
        self.assertEqual({"fps": 5.0}, parse_progress("fps=5 bitrate=N/A"))

    def test_progress_lines_are_not_echoed(self):
        _, _, text = self.run_runner([FakeProc(0, ["fps=30 speed=1.0x\n"])])
        self.assertEqual("", text)

    def test_progress_is_echoed_without_status_callback(self):
        out = io.StringIO()
        run_with_reconnect(["ffmpeg"], KEY, "linux",
                           popen=lambda *a, **k: FakeProc(0, ["fps=30 speed=1.0x\n"]),
                           out=out)
        self.assertIn("fps=30", out.getvalue())

    def test_linux_display_and_macos_device(self):
        args, _ = capture_inputs("linux", 30, display=":1.0")
        self.assertEqual(":1.0", args[args.index("-i") + 1])
        args, _ = capture_inputs("linux", 30)
        self.assertEqual(":0.0", args[args.index("-i") + 1])
        args, _ = capture_inputs("macos", 30, video_device="2")
        self.assertEqual("2:0", args[args.index("-i") + 1])
        self.assertEqual("1:0", capture_inputs("macos", 30)[0][-1])

    def test_display_env_reaches_command(self):
        s = resolve_settings({"display": ":2.0"}, {})
        argv = build_command(s, KEY, "linux", "libx264")
        self.assertIn(":2.0", argv)
        self.assertIn("-stats", argv)


class CliTests(unittest.TestCase):
    def run_cli(self, argv, env=None):
        out = io.StringIO()
        old = dict(os.environ)
        os.environ.pop("STREAM_KEY", None)
        os.environ.update(env or {})
        try:
            code = cli.main(argv, out=out)
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, out.getvalue()

    def test_dry_run_redacts(self):
        code, text = self.run_cli(
            ["start", "--platform", "twitch", "--preset", "potato", "--dry-run"],
            {"STREAM_KEY": KEY})
        self.assertEqual(0, code)
        self.assertNotIn(KEY, text)
        self.assertIn("rtmp://live.twitch.tv/app/****", text)
        self.assertIn("-b:v 700k", text)

    def test_start_wires_retry_cap_and_handles_launch_error(self):
        calls = {}
        def fake_run(argv, key, os_name, **kwargs):
            calls.update(kwargs)
            raise OSError("ffmpeg vanished")
        real = (cli.run_with_reconnect, cli.shutil.which, cli.probe_encoders)
        cli.run_with_reconnect = fake_run
        cli.shutil.which = lambda name: "/usr/bin/ffmpeg"
        cli.probe_encoders = lambda ffmpeg: set()
        try:
            code, text = self.run_cli(["start", "--software"], {"STREAM_KEY": KEY})
        finally:
            cli.run_with_reconnect, cli.shutil.which, cli.probe_encoders = real
        self.assertEqual(cli.MAX_QUICK_FAILURES, calls["max_failures"])
        self.assertEqual(1, code)
        self.assertIn("Could not start ffmpeg", text)
        self.assertNotIn(KEY, text)

    def test_keep_trying_removes_retry_cap_and_passes_fallback(self):
        calls = {}
        def fake_run(argv, key, os_name, **kwargs):
            calls.update(kwargs)
            return 0
        real = (cli.run_with_reconnect, cli.shutil.which, cli.probe_encoders)
        cli.run_with_reconnect = fake_run
        cli.shutil.which = lambda name: "/usr/bin/ffmpeg"
        cli.probe_encoders = lambda ffmpeg: set()
        try:
            code, _ = self.run_cli(["start", "--software", "--keep-trying"],
                                   {"STREAM_KEY": KEY})
        finally:
            cli.run_with_reconnect, cli.shutil.which, cli.probe_encoders = real
        self.assertEqual(0, code)
        self.assertIsNone(calls["max_failures"])
        self.assertEqual("libx264", calls["encoder"])
        self.assertIn("libx264", calls["argv_factory"]("libx264"))

    def test_presets_and_errors(self):
        code, text = self.run_cli(["presets"])
        self.assertEqual(0, code)
        self.assertIn("potato", text)
        code, text = self.run_cli(
            ["start", "--platform", "custom", "--dry-run"], {"STREAM_KEY": KEY})
        self.assertEqual(2, code)
        self.assertNotIn(KEY, text)


if __name__ == "__main__":
    unittest.main()
