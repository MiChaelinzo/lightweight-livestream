import io
import os
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import audio, audio_check as ac
from lightstream.cli import cmd_audio_check, main

FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")

VOLUMEDETECT = """[Parsed_volumedetect_0 @ 0x1] n_samples: 132300
[Parsed_volumedetect_0 @ 0x1] mean_volume: -2.0 dB
[Parsed_volumedetect_0 @ 0x1] max_volume: 0.0 dB
[Parsed_volumedetect_0 @ 0x1] histogram_0db: 65400
"""
EBUR = """[Parsed_ebur128_1 @ 0x2] t: 0.1  I: -70.0 LUFS
[Parsed_ebur128_1 @ 0x2] Summary:

  Integrated loudness:
    I:          -2.7 LUFS
    Threshold: -12.7 LUFS

  True peak:
    Peak:        0.5 dBFS
"""


class ParseTests(unittest.TestCase):
    def test_parses_volumedetect_and_summary_only(self):
        check = ac.parse_analysis(VOLUMEDETECT + EBUR)
        self.assertEqual(ac.AudioCheck(0.0, 65400, -2.7, 0.5), check)
        self.assertTrue(ac.is_clipping(check))

    def test_quiet_speech_is_not_clipping(self):
        check = ac.parse_analysis(
            "max_volume: -12.0 dB\nhistogram_0db: 0\nSummary:\n I: -20.0 LUFS\n"
            " Peak: -11.9 dBFS\n")
        self.assertFalse(ac.is_clipping(check))
        self.assertEqual(ac.LOUDNESS_OK, ac.loudness_class(check))

    def test_peak_threshold_is_inclusive(self):
        self.assertTrue(ac.is_clipping(ac.AudioCheck(-1.0, 0, None, None)))
        self.assertFalse(ac.is_clipping(ac.AudioCheck(-1.1, 0, None, None)))

    def test_unknown_values_are_not_clipping(self):
        check = ac.parse_analysis("nothing useful")
        self.assertEqual(ac.AudioCheck(None, None, None, None), check)
        self.assertFalse(ac.is_clipping(check))
        self.assertIsNone(ac.loudness_class(check))

    def test_silence_reports_none_for_inf(self):
        check = ac.parse_analysis("max_volume: -inf dB\nSummary:\n I: -inf LUFS\n")
        self.assertIsNone(check.peak_dbfs)
        self.assertIsNone(check.integrated_lufs)

    def test_loudness_classes(self):
        self.assertEqual("loud", ac.loudness_class(ac.AudioCheck(0, 0, -8.0, None)))
        self.assertEqual("quiet", ac.loudness_class(ac.AudioCheck(0, 0, -30.0, None)))

    def test_lines_mention_echo_limit(self):
        lines = ac.check_lines(ac.parse_analysis(VOLUMEDETECT + EBUR))
        self.assertIn("Clipping: YES", " ".join(lines))
        self.assertIn("cannot detect or remove echo", lines[-1])


class DegradeTests(unittest.TestCase):
    def test_missing_ffmpeg(self):
        with self.assertRaises(ValueError) as ctx:
            ac.analyze_file(None, "x.wav")
        self.assertIn("ffmpeg was not found", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(ValueError) as ctx:
            ac.analyze_file("ffmpeg", "/nonexistent/none.wav")
        self.assertIn("not found", str(ctx.exception))

    def test_ffmpeg_failure_is_explained(self):
        def run(*a, **k):
            return subprocess.CompletedProcess(a, 1, b"", b"boom\nInvalid data\n")
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            with self.assertRaises(ValueError) as ctx:
                ac.analyze_file("ffmpeg", f.name, run=run)
        self.assertIn("Invalid data", str(ctx.exception))

    def test_cli_error_is_exit_2(self):
        out = io.StringIO()
        code = main(["audio-check", "/nonexistent/none.wav", "--ffmpeg", "ffmpeg"], out=out)
        self.assertEqual(2, code)
        self.assertIn("Error:", out.getvalue())

    def test_cli_prints_report_from_injected_analyzer(self):
        out = io.StringIO()
        args = type("A", (), {"ffmpeg": "ff", "file": "f.wav"})()
        code = cmd_audio_check(args, out, analyze=lambda ff, path: ac.AudioCheck(
            -12.0, 0, -20.0, -11.0))
        self.assertEqual(0, code)
        self.assertIn("Clipping: no", out.getvalue())


class ProfileTests(unittest.TestCase):
    def test_teaching_and_meeting_use_autogain(self):
        for name in ("teaching", "meeting"):
            for chain in audio.AUDIO_CHAINS:
                self.assertIn("dynaudnorm", audio.audio_profile_chain(name, chain))

    def test_meeting_denoises_harder_than_teaching(self):
        self.assertIn("afftdn=nr=16", audio.audio_profile_chain("meeting"))
        self.assertIn("afftdn=nr=8", audio.audio_profile_chain("teaching"))

    def test_autogain_option_appends_once(self):
        base = audio.audio_profile_chain("gaming")
        self.assertNotIn("dynaudnorm", base)
        self.assertTrue(audio.audio_profile_chain("gaming", autogain=True)
                        .endswith(audio.AUTOGAIN_FILTER))
        meeting = audio.audio_profile_chain("meeting")
        self.assertEqual(meeting, audio.audio_profile_chain("meeting", autogain=True))

    def test_meeting_description_says_no_echo_removal(self):
        self.assertIn("Echo is not removed", audio.get_audio_profile("meeting").description)


@unittest.skipUnless(FFMPEG and os.path.exists(FFMPEG), "LIGHTSTREAM_TEST_FFMPEG not set")
class RealFfmpegTests(unittest.TestCase):
    def _make(self, directory, name, graph):
        path = os.path.join(directory, name)
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                        graph, "-c:a", "pcm_s16le", path], check=True)
        return path

    def test_clipped_sine_detected_and_quiet_sine_not(self):
        with tempfile.TemporaryDirectory() as d:
            clipped = self._make(d, "clip.wav", "sine=f=440:d=2,volume=20dB")
            quiet = self._make(d, "quiet.wav", "sine=f=440:d=2,volume=-12dB")
            loud_check = ac.analyze_file(FFMPEG, clipped)
            quiet_check = ac.analyze_file(FFMPEG, quiet)
        self.assertTrue(ac.is_clipping(loud_check), loud_check)
        self.assertGreater(loud_check.clipped_samples, 0)
        self.assertFalse(ac.is_clipping(quiet_check), quiet_check)
        self.assertIsNotNone(quiet_check.integrated_lufs)

    def test_every_profile_chain_is_accepted_by_ffmpeg(self):
        for name in audio.AUDIO_PROFILES:
            for chain in audio.AUDIO_CHAINS:
                argv = [FFMPEG, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                        "sine=f=440:d=1", "-af", audio.audio_profile_chain(name, chain),
                        "-f", "null", "-"]
                result = subprocess.run(argv, capture_output=True)
                self.assertEqual(0, result.returncode, (name, chain, result.stderr))


if __name__ == "__main__":
    unittest.main()
