import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import cli
from lightstream.command import build_command
from lightstream.config import (config_path, detect_os, resolve_key,
                                resolve_settings, write_example_config)
from lightstream.encoders import choose_encoder, parse_encoders
from lightstream.platforms import capture_inputs, ingest_url
from lightstream.presets import PRESETS, get_preset, parse_resolution
from lightstream.runner import (backoff_delay, format_command, priority_kwargs,
                                redact, run_with_reconnect)

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


class CommandTests(unittest.TestCase):
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
