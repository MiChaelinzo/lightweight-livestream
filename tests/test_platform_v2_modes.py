"""Potato Stream, ladder tiers, SRT validation and the v0.12 CLI flags."""

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import autoscale as au
from lightstream import cli
from lightstream.command import build_command, ignored_setting_notes
from lightstream.config import resolve_settings
from lightstream.emergency import POTATO_STREAM_PROFILES, potato_stream_settings
from lightstream.platforms import ingest_url, validate_srt_url
from lightstream.runner import format_command

KEY = "live_SECRET123"


def base(**cli_values):
    return resolve_settings(dict(cli_values), {}, cpu_count=8)


class PotatoStreamTests(unittest.TestCase):
    def test_targets_are_2000_and_4000(self):
        self.assertEqual({2000, 4000}, set(POTATO_STREAM_PROFILES))
        with self.assertRaises(ValueError):
            potato_stream_settings(base(), 3000)

    def test_2000_tier(self):
        s = potato_stream_settings(base(preset="720p60"), 2000)
        self.assertEqual((640, 360, 15, 2000, 1), (
            s.width, s.height, s.fps, s.video_kbps, s.threads))
        self.assertEqual("ultrafast", s.x264_preset)
        self.assertFalse(s.grayscale)

    def test_4000_tier_uses_two_threads(self):
        s = potato_stream_settings(base(preset="720p60"), 4000)
        self.assertEqual((854, 480, 15, 4000, 2), (
            s.width, s.height, s.fps, s.video_kbps, s.threads))

    def test_never_raises_size_or_fps(self):
        s = potato_stream_settings(base(preset="potato"), 4000)  # 640x360 at 24
        self.assertEqual((640, 360), (s.width, s.height))
        low = base(preset="potato", fps=10)
        self.assertEqual(10, potato_stream_settings(low, 2000).fps)

    def test_drops_scene_and_audio_filters(self):
        s = potato_stream_settings(base()._replace(audio_filter="x"), 2000)
        self.assertIsNone(s.scene)
        self.assertIsNone(s.audio_filter)

    def test_presets_and_profiles_exist(self):
        for name in ("potato_2000", "potato_4000"):
            s = base(profile=name)
            self.assertEqual("ultrafast", s.x264_preset)
            self.assertIn(s.threads, (1, 2))

    def test_grayscale_and_skip_static_add_filters(self):
        s = potato_stream_settings(base(), 2000, grayscale=True)
        argv = build_command(s, KEY, "linux", "libx264")
        self.assertIn("format=gray,format=yuv420p", argv[argv.index("-vf") + 1])
        s = potato_stream_settings(base(), 2000, skip_static=True)
        argv = build_command(s, KEY, "linux", "libx264")
        self.assertTrue(argv[argv.index("-vf") + 1].endswith("mpdecimate"))
        self.assertEqual("vfr", argv[argv.index("-fps_mode") + 1])
        self.assertNotIn("-r", argv)

    def test_inapplicable_settings_are_reported_not_dropped_silently(self):
        s = potato_stream_settings(base(rate_mode="cbr"), 2000, grayscale=True,
                                   skip_static=True)
        self.assertEqual([], ignored_setting_notes(s, "libx264"))
        notes = " ".join(ignored_setting_notes(s, "h264_vaapi"))
        for word in ("cbr", "grayscale", "skip-static", "VAAPI"):
            self.assertIn(word, notes)
        self.assertEqual(1, len(ignored_setting_notes(s, "h264_nvenc")))

    def test_cli_prints_note_for_cbr_with_hardware_encoder(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"HOME": d, "XDG_CONFIG_HOME": d,
                                             "STREAM_KEY": KEY}, clear=True), \
                mock.patch.object(cli, "detect_gpu_names", lambda _o: []), \
                mock.patch.object(cli, "detect_os", lambda: "linux"), \
                mock.patch.object(cli, "find_ffmpeg", lambda: None):
            cli.main(["start", "--dry-run", "--rate-mode", "cbr",
                      "--encoder", "h264_nvenc"], out)
        self.assertIn("Note: --rate-mode cbr only applies to libx264", out.getvalue())

    def test_default_filters_have_neither(self):
        argv = build_command(potato_stream_settings(base(), 2000), KEY, "linux",
                             "libx264")
        self.assertNotIn("gray", argv[argv.index("-vf") + 1])
        self.assertNotIn("mpdecimate", " ".join(argv))


class LadderTierTests(unittest.TestCase):
    def test_1080_steps_down_through_every_tier(self):
        ladder = au.build_ladder(au.LadderStep(1920, 1080, 30, 4500))
        heights = [s.height for s in ladder]
        for h in (1080, 720, 480, 360):
            self.assertIn(h, heights)
        self.assertNotIn(240, heights)  # below the default floor

    def test_240p_tier_is_reachable_with_its_floor(self):
        ladder = au.build_ladder(au.LadderStep(1280, 720, 30, 2500),
                                 floor_preset=au.TIER_240P)
        self.assertEqual((426, 240), (ladder[-1].width, ladder[-1].height))
        heights = [s.height for s in ladder]
        self.assertEqual(sorted(set(heights), reverse=True), sorted(
            set(heights), reverse=True))
        for h in (720, 480, 360, 240):
            self.assertIn(h, heights)

    def test_ladder_tiers_are_not_stream_presets(self):
        from lightstream.presets import PRESETS
        self.assertNotIn(au.TIER_240P, PRESETS)

    def test_default_ladder_is_unchanged_for_720p60(self):
        ladder = au.build_ladder(au.LadderStep(1280, 720, 60, 4000))
        self.assertEqual(ladder[-1].height, 360)


class SrtTests(unittest.TestCase):
    def test_valid_and_invalid_addresses(self):
        self.assertEqual("srt://host:9000", validate_srt_url("srt://host:9000"))
        for bad in ("srt://host", "rtmp://host:1", "srt://:9000", "srt://h:9 0",
                    "srt://h:9000?streamid=abc/KEYVALUE"):
            with self.assertRaises(ValueError, msg=bad):
                validate_srt_url(bad)

    def test_key_becomes_streamid_and_is_redacted(self):
        url = ingest_url("custom", KEY, "srt://host:9000?latency=120")
        self.assertEqual("srt://host:9000?latency=120&streamid=" + KEY, url)
        self.assertNotIn(KEY, format_command([url], KEY))

    def test_srt_output_is_mpegts(self):
        s = base(platform="custom", url="srt://host:9000")
        argv = build_command(s, KEY, "linux", "libx264")
        self.assertEqual(["-f", "mpegts"], argv[-3:-1])
        self.assertNotIn("-flvflags", argv)

    def test_srt_with_recording_uses_mpegts_slot(self):
        s = base(platform="custom", url="srt://host:9000", record="a.mkv")
        argv = build_command(s, KEY, "linux", "libx264")
        self.assertTrue(argv[-1].startswith("[f=mpegts:onfail=abort]srt://"))

    def test_bad_srt_url_is_a_config_error(self):
        with self.assertRaises(ValueError):
            base(platform="custom", url="srt://host")


class RecordingConfigTests(unittest.TestCase):
    def test_rate_mode_validated(self):
        self.assertEqual("cbr", base(rate_mode="cbr").rate_mode)
        with self.assertRaises(ValueError):
            base(rate_mode="abr")

    def test_webm_record_is_a_config_error(self):
        with self.assertRaises(ValueError):
            base(record="x.webm")


class CliTests(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            env = {"HOME": d, "XDG_CONFIG_HOME": d, "STREAM_KEY": KEY}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(cli, "detect_gpu_names", lambda _o: []), \
                    mock.patch.object(cli, "detect_os", lambda: "linux"), \
                    mock.patch.object(cli, "find_ffmpeg", lambda: None):
                code = cli.main(argv, out)
        return code, out.getvalue()

    def test_potato_stream_flag(self):
        code, text = self.run_cli(["start", "--dry-run", "--potato-stream", "2000"])
        self.assertEqual(0, code)
        self.assertIn("-b:v 2000k", text)
        self.assertIn("-threads 1", text)
        self.assertNotIn(KEY, text)

    def test_grayscale_needs_potato_stream(self):
        code, text = self.run_cli(["start", "--dry-run", "--grayscale"])
        self.assertEqual(2, code)
        self.assertIn("--potato-stream", text)

    def test_rate_mode_flag(self):
        code, text = self.run_cli(["start", "--dry-run", "--rate-mode", "cbr"])
        self.assertEqual(0, code)
        self.assertIn("nal-hrd=cbr", text)

    def test_webm_record_flag_is_refused(self):
        code, text = self.run_cli(["start", "--dry-run", "--record", "x.webm"])
        self.assertEqual(2, code)
        self.assertIn("VP8/VP9", text)


if __name__ == "__main__":
    unittest.main()
