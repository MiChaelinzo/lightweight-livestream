import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import highlights as hl
from lightstream.cli import cmd_dashboard, main

FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")

SAMPLE = """frame:0    pts:0       pts_time:0
lavfi.scene_score=0.500000
frame:1    pts:1       pts_time:0.2
lavfi.signalstats.YDIF=12.5
frame:0    pts:0       pts_time:0.1
lavfi.astats.Overall.RMS_level=-inf
frame:1    pts:800     pts_time:1.1
lavfi.astats.Overall.RMS_level=-20.0
noise line
"""
INFO_TEXT = """  Duration: 00:01:02.50, start: 0.000000, bitrate: 300 kb/s
  Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 1280x720, 30 fps
  Stream #0:1[0x2](und): Audio: aac (LC), 44100 Hz, mono
"""


def signals(scene=(), motion=(), loudness=()):
    return hl.Signals(list(scene), list(motion), list(loudness))


class ParseTests(unittest.TestCase):
    def test_signals(self):
        s = hl.parse_signals(SAMPLE)
        self.assertEqual([(0.0, 0.5)], s.scene)
        self.assertEqual([(0.2, 12.5)], s.motion)
        self.assertEqual([(0.1, hl.SILENCE_FLOOR_DB), (1.1, -20.0)], s.loudness)

    def test_stream_info(self):
        info = hl.parse_stream_info(INFO_TEXT)
        self.assertEqual(hl.StreamInfo(62.5, True, True), info)
        self.assertEqual(hl.StreamInfo(0.0, False, False), hl.parse_stream_info("x"))


class ScoringTests(unittest.TestCase):
    def test_loudness_burst_scores_above_baseline(self):
        loud = [(i * 0.1, -50.0) for i in range(100)]
        loud[45] = (4.5, -20.0)
        scores = hl.score_windows(signals(loudness=loud), 10.0)
        self.assertEqual(10, len(scores))
        best = max(scores, key=lambda s: s.score)
        self.assertEqual(4, best.index)
        self.assertEqual(1.0, best.loudness)
        self.assertEqual(0.0, scores[0].score)

    def test_steady_signal_scores_zero(self):
        flat = [(i * 0.1, -30.0) for i in range(50)]
        scores = hl.score_windows(signals(loudness=flat), 5.0)
        self.assertTrue(all(s.score == 0.0 for s in scores))

    def test_scene_change_scores(self):
        scores = hl.score_windows(signals(scene=[(2.3, 0.6)]), 5.0)
        self.assertAlmostEqual(hl.SCENE_WEIGHT, scores[2].score)

    def test_empty_duration(self):
        self.assertEqual([], hl.score_windows(signals(), 0))

    def test_deterministic(self):
        s = hl.parse_signals(SAMPLE)
        self.assertEqual(hl.score_windows(s, 3.0), hl.score_windows(s, 3.0))


def ws(index, score):
    return hl.WindowScore(index, index + 0.5, 0, 0, 0, score)


class PeakTests(unittest.TestCase):
    def test_min_gap_and_top(self):
        scores = [ws(0, 0.9), ws(1, 0.8), ws(10, 0.7), ws(20, 0.6)]
        peaks = hl.pick_peaks(scores, top=2, min_gap=5)
        self.assertEqual([0, 10], [p.index for p in peaks])

    def test_tie_prefers_earlier_window(self):
        peaks = hl.pick_peaks([ws(7, 0.5), ws(3, 0.5)], top=1, min_gap=1)
        self.assertEqual(3, peaks[0].index)

    def test_low_scores_never_picked(self):
        self.assertEqual([], hl.pick_peaks([ws(0, hl.MIN_SCORE)], 3, 1))

    def test_clip_is_moved_inside_the_file(self):
        self.assertEqual(0.0, hl.clip_for_peak(ws(1, 1), 30, 100).start)
        self.assertEqual(70.0, hl.clip_for_peak(ws(98, 1), 30, 100).start)
        short = hl.clip_for_peak(ws(1, 1), 30, 10)
        self.assertEqual((0.0, 10.0), (short.start, short.length))

    def test_merge_overlapping(self):
        merged = hl.merge_clips([hl.Clip(10, 30, 0.5), hl.Clip(0, 20, 0.9),
                                 hl.Clip(100, 5, 0.1)])
        self.assertEqual([hl.Clip(0, 40, 0.9), hl.Clip(100, 5, 0.1)], merged)


class NameTests(unittest.TestCase):
    def test_safe_stem_blocks_traversal(self):
        self.assertEqual("evil", hl.safe_stem("../../evil.mkv"))
        self.assertEqual("a_b_c", hl.safe_stem("a b;c.mp4"))
        self.assertEqual("video", hl.safe_stem("..."))

    def test_unique_path_never_overwrites(self):
        taken = {os.path.join("d", "x.mp4"), os.path.join("d", "x-2.mp4")}
        got = hl.unique_path("d", "x", ".mp4", exists=taken.__contains__)
        self.assertEqual(os.path.join("d", "x-3.mp4"), got)


class ArgvTests(unittest.TestCase):
    def test_copy_cut(self):
        argv = hl.cut_argv("ff", "in.mkv", hl.Clip(5, 10, 1), "o.mp4")
        self.assertIn("copy", argv)
        self.assertIn("-n", argv)
        self.assertLess(argv.index("-ss"), argv.index("-i"))

    def test_vertical_cut_targets_1080x1920(self):
        argv = hl.cut_argv("ff", "in.mkv", hl.Clip(5, 10, 1), "o.mp4", vertical=True)
        self.assertIn("libx264", argv)
        self.assertIn("1080:1920", " ".join(argv))

    def test_blur_uses_filter_complex_and_maps_video_once(self):
        argv = hl.cut_argv("ff", "in.mkv", hl.Clip(0, 5, 1), "o.mp4", True, True)
        self.assertIn("-filter_complex", argv)
        self.assertEqual(1, argv.count("[v]"))

    def test_analysis_graph_follows_streams(self):
        audio_only = hl.analysis_argv("ff", "a.wav", hl.StreamInfo(5, False, True))
        self.assertNotIn("signalstats", " ".join(audio_only))
        video_only = hl.analysis_argv("ff", "v.mp4", hl.StreamInfo(5, True, False))
        self.assertNotIn("astats", " ".join(video_only))


class DegradeTests(unittest.TestCase):
    def test_missing_ffmpeg_and_file(self):
        with self.assertRaises(ValueError) as ctx:
            hl.probe_file(None, "x.mkv")
        self.assertIn("ffmpeg was not found", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            hl.probe_file("ffmpeg", "/nonexistent/x.mkv")
        self.assertIn("not found", str(ctx.exception))

    def test_bad_options(self):
        with self.assertRaises(ValueError):
            hl.find_highlights("ff", "x", top=0)

    def test_cli_error_is_exit_2(self):
        out = io.StringIO()
        self.assertEqual(2, main(["highlights", "/nonexistent/x.mkv",
                                  "--ffmpeg", "ffmpeg"], out=out))
        self.assertIn("Error:", out.getvalue())
        out = io.StringIO()
        self.assertEqual(2, main(["highlights", "x", "--blur-background"], out=out))
        self.assertIn("needs --vertical", out.getvalue())

    def test_find_highlights_with_injected_steps(self):
        info = hl.StreamInfo(100.0, False, True)
        loud = [(i * 0.1, -50.0) for i in range(1000)]
        loud[500] = (50.0, -10.0)
        cuts = []
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "my game.mkv")
            open(src, "w").close()
            report, path = hl.find_highlights(
                "ff", src, out_dir=os.path.join(d, "o"),
                probe=lambda f, p: info,
                analyze=lambda f, p, i: signals(loudness=loud),
                cutter=lambda *a: cuts.append(a))
            self.assertTrue(os.path.basename(path).startswith("my_game-highlights"))
            with open(path) as fh:
                self.assertEqual(report, json.load(fh))
            self.assertIn("HEURISTIC", report["heuristic"])
            self.assertEqual(1, len(cuts))
            self.assertEqual(50.5, report["peaks"][0]["time_seconds"])
            lines = hl.report_lines(report, path)
            self.assertTrue(any("keyframe" in line for line in lines))


class DashboardTests(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual("512 B", hl.human_size(512))
        self.assertEqual("1.5 KB", hl.human_size(1536))

    def test_lines_with_and_without_data(self):
        empty = "\n".join(hl.dashboard_lines([], [], [], "rec", None))
        self.assertIn("Recent sessions: none", empty)
        self.assertIn("Free disk space: unknown", empty)
        full = "\n".join(hl.dashboard_lines(
            [{"date": "2025-01-02", "preset": "balanced", "health_score": 80,
              "dropped_frames": 1, "reconnect_count": 0}],
            [("a.mkv", 2048)], [("a-highlights/c.mp4", 1024)], "rec", (10, 100)))
        self.assertIn("2025-01-02", full)
        self.assertIn("a.mkv  2.0 KB", full)
        self.assertIn("Free disk space: 10 B of 100 B", full)

    def test_cmd_dashboard_lists_folder(self):
        usage = namedtuple("U", "total used free")
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as h:
            with open(os.path.join(d, "r.mkv"), "wb") as fh:
                fh.write(b"x" * 100)
            os.makedirs(os.path.join(d, "r-highlights"))
            with open(os.path.join(d, "r-highlights", "c.mp4"), "wb") as fh:
                fh.write(b"y" * 10)
            out = io.StringIO()
            args = type("A", (), {"recordings": d})()
            cmd_dashboard(args, out, history_dir=h,
                          disk_usage=lambda p: usage(1000, 1, 999))
        text = out.getvalue()
        self.assertIn("r.mkv", text)
        self.assertIn("c.mp4", text)
        self.assertIn("999 B of 1000 B", text)


def _probe_size(path):
    text = subprocess.run([FFMPEG, "-hide_banner", "-i", path], stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL).stderr.decode()
    import re
    return re.search(r"Video:.*?, (\d+)x(\d+)", text).groups()


@unittest.skipUnless(FFMPEG and os.path.exists(FFMPEG), "LIGHTSTREAM_TEST_FFMPEG not set")
class RealFfmpegTests(unittest.TestCase):
    BURSTS = (12.0, 33.0)   # start seconds of 1 s sine bursts in a 45 s file
    TOLERANCE = 1.5

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.src = os.path.join(cls.dir.name, "synthetic game.mp4")
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=s=1280x720:r=30:d=45",
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=45",
                        "-f", "lavfi", "-i", "sine=f=880:d=1",
                        "-f", "lavfi", "-i", "sine=f=880:d=1",
                        "-filter_complex",
                        "[2]adelay=%d[d1];[3]adelay=%d[d2];"
                        "[1][d1][d2]amix=inputs=3:normalize=0:duration=first[a]"
                        % (cls.BURSTS[0] * 1000, cls.BURSTS[1] * 1000),
                        "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
                        "-preset", "ultrafast", "-g", "30", "-c:a", "aac", cls.src],
                       check=True, stdin=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def _run(self, **kwargs):
        out_dir = os.path.join(self.dir.name, "out%d" % len(os.listdir(self.dir.name)))
        report, path = hl.find_highlights(FFMPEG, self.src, top=2, length=6,
                                          min_gap=10, out_dir=out_dir, **kwargs)
        return report, out_dir

    def test_burst_times_detected_and_clips_cut(self):
        report, out_dir = self._run()
        found = sorted(p["time_seconds"] for p in report["peaks"])
        self.assertEqual(2, len(found))
        for expected, got in zip(self.BURSTS, found):
            self.assertLess(abs(got - (expected + 0.5)), self.TOLERANCE)
        files = sorted(os.listdir(out_dir))
        self.assertEqual(2, sum(f.endswith(".mp4") for f in files))
        self.assertTrue(files[0].startswith("synthetic_game"))

    def test_vertical_clip_is_1080x1920(self):
        for blur in (False, True):
            report, out_dir = self._run(vertical=True, blur=blur)
            clip = os.path.join(out_dir, report["clips"][0]["file"])
            self.assertEqual(("1080", "1920"), _probe_size(clip))

    def test_existing_clip_is_never_overwritten(self):
        report, out_dir = self._run()
        before = sorted(os.listdir(out_dir))
        hl.find_highlights(FFMPEG, self.src, top=2, length=6, min_gap=10,
                           out_dir=out_dir)
        after = sorted(os.listdir(out_dir))
        self.assertEqual(2 * len(before), len(after))

    def test_video_without_audio_still_reports(self):
        silent = os.path.join(self.dir.name, "silent.mp4")
        subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "testsrc=s=320x240:r=10:d=4", "-c:v", "libx264", silent],
                       check=True, stdin=subprocess.DEVNULL)
        report, _ = hl.find_highlights(FFMPEG, silent, cut=False,
                                       out_dir=os.path.join(self.dir.name, "s"))
        self.assertFalse(report["has_audio"])
        self.assertEqual([], report["clips"])


if __name__ == "__main__":
    unittest.main()
