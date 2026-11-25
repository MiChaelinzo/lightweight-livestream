"""Pure helpers of tools/spikes.py. The ffmpeg experiments themselves are run
by `python3 tools/spikes.py --all`, not here (they take minutes)."""

import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import spikes  # noqa: E402

FRAMECRC = """#software: Lavf61.1.100
#tb 0: 1/1000
#media_type 0: video
#codec_id 0: h264
#dimensions 0: 640x360
#sar 0: 1/1
#stream#, dts,        pts, duration,     size, hash
0,          0,          0,       33,    12345, 0x1a2b3c4d, F=0x1
0,         33,         33,       33,      678, 0x00000000
0,         67,         67,       33,      700, 0x00000001
0,       1067,       1067,       33,      700, 0x00000002
0,       1000,       1000,       33,      700, 0x00000003
0,       1000,       1000,       33,      700, 0x00000004
1,          5,      NOPTS,       21,      300, 0x00000005
"""

PROC_NET_TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:7A69 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1
   1: 0100007F:1F90 0100007F:D431 01 00000000:00000000 00:00000000 00000000     0        0 2 1
   2: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 3 1
"""


class FramecrcTest(unittest.TestCase):
    def test_parses_timebase_and_packets(self):
        timebases, packets = spikes.parse_framecrc(FRAMECRC)
        self.assertEqual(timebases, {0: (1, 1000)})
        self.assertEqual(len(packets), 7)
        self.assertEqual(packets[0], {"stream": 0, "dts": 0, "pts": 0,
                                      "duration": 33, "size": 12345})
        self.assertIsNone(packets[-1]["pts"])
        self.assertEqual(packets[-1]["stream"], 1)

    def test_skips_garbage_lines(self):
        _, packets = spikes.parse_framecrc("hello\n0, x, y, 1, 2, 3\n\n")
        self.assertEqual(packets, [])

    def test_analyze_finds_gaps_and_backward_jumps(self):
        timebases, packets = spikes.parse_framecrc(FRAMECRC)
        result = spikes.analyze_packets(packets, timebases[0], gap_ms=500)
        self.assertEqual(result["packets"], 6)  # stream 1 ignored
        self.assertEqual(result["forward_gaps_ms"], [1000.0])
        self.assertEqual(result["backward_jumps_ms"], [-67.0])
        self.assertEqual(result["non_monotonic"], 2)  # 1067->1000 and 1000->1000
        self.assertEqual(result["span_ms"], 1000.0)
        self.assertEqual(result["first_dts_ms"], 0.0)

    def test_analyze_converts_90k_timebase(self):
        packets = [{"stream": 0, "dts": d, "pts": d, "duration": 3000, "size": 1}
                   for d in (0, 3000, 6000)]
        result = spikes.analyze_packets(packets, (1, 90000))
        self.assertEqual(result["span_ms"], 66.7)
        self.assertEqual(result["non_monotonic"], 0)

    def test_analyze_empty(self):
        result = spikes.analyze_packets([], (1, 1000))
        self.assertEqual(result["packets"], 0)
        self.assertIsNone(result["first_dts_ms"])


class FrameSizeTest(unittest.TestCase):
    def test_histogram_and_dimensions(self):
        size_360 = 640 * 360 * 3 // 2
        size_540 = 960 * 540 * 3 // 2
        packets = [{"stream": 0, "size": size_360}] * 2 + \
            [{"stream": 0, "size": size_540}] + [{"stream": 1, "size": 9}]
        counts = spikes.frame_size_histogram(packets)
        self.assertEqual(counts, {size_360: 2, size_540: 1})
        candidates = [(640, 360), (960, 540)]
        self.assertEqual(spikes.yuv420_dimensions(size_540, candidates), (960, 540))
        self.assertIsNone(spikes.yuv420_dimensions(7, candidates))


class ProcParsingTest(unittest.TestCase):
    def test_listening_ports_only(self):
        self.assertEqual(spikes.tcp_listening_ports(PROC_NET_TCP), {31337, 22})

    def test_wait_tcp_listening_uses_reader(self):
        self.assertTrue(spikes.wait_tcp_listening(31337, timeout=0.2,
                                                  read=lambda: PROC_NET_TCP))
        self.assertFalse(spikes.wait_tcp_listening(8080, timeout=0.1,
                                                   read=lambda: PROC_NET_TCP))


class TextHelpersTest(unittest.TestCase):
    def test_count_matches_case_insensitive(self):
        text = "Non monotonic DTS\nok\nnon-monotonic again\nDiscontinuity"
        self.assertEqual(spikes.count_matches(text, ["non monotonic", "non-monotonic"]), 2)

    def test_protocol_options(self):
        text = ("libsrt AVOptions:\n"
                "  -latency           <int64>      ED......... receiver delay\n"
                "  -mode              <int>        ED......... Connection mode\n"
                "     caller          1            ED.........\n")
        self.assertEqual(spikes.parse_protocol_options(text), ["latency", "mode"])

    def test_log_head(self):
        self.assertEqual(spikes._log_head("\n a \n\nb\nc\nd\ne\n", lines=2), ["a", "b"])


class NumbersTest(unittest.TestCase):
    def test_summarize(self):
        self.assertEqual(spikes.summarize([3, 1, 2]),
                         {"n": 3, "median": 2, "min": 1, "max": 3})
        self.assertEqual(spikes.summarize([4, None, 1, 2, 3])["median"], 2.5)
        self.assertEqual(spikes.summarize([None])["n"], 0)

    def test_bitrate(self):
        self.assertEqual(spikes.bitrate_kbps(250000, 10), 200.0)
        self.assertIsNone(spikes.bitrate_kbps(1, 0))


class MainTest(unittest.TestCase):
    def test_parse_args(self):
        opts = spikes.parse_args(["--spike", "c", "--repeats", "2", "--ffmpeg", "ff"])
        self.assertEqual(opts["spikes"], ["c"])
        self.assertEqual(opts["repeats"], 2)
        self.assertEqual(spikes.parse_args(["--all"])["spikes"], list(spikes.SPIKE_NAMES))
        for bad in ([], ["--spike", "z"], ["--repeats", "0", "--all"], ["--nope"]):
            with self.assertRaises(ValueError):
                spikes.parse_args(bad)

    def test_main_writes_json_and_reports_failures(self):
        def ok(ffmpeg, workdir, repeats):
            return {"repeats": repeats, "workdir_exists": os.path.isdir(workdir)}

        def broken(ffmpeg, workdir, repeats):
            raise RuntimeError("listener did not start")

        out = io.StringIO()
        original = spikes.host_summary
        spikes.host_summary = lambda ffmpeg: {"ffmpeg": ffmpeg}
        try:
            code = spikes.main(["--spike", "a", "--ffmpeg", "ff"],
                               funcs={"a": ok}, stdout=out)
            self.assertEqual(code, 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report["spikes"]["a"],
                             {"repeats": 3, "workdir_exists": True})
            out = io.StringIO()
            code = spikes.main(["--spike", "a", "--spike", "b"],
                               funcs={"a": ok, "b": broken}, stdout=out)
            self.assertEqual(code, 1)
            report = json.loads(out.getvalue())
            self.assertIn("listener did not start", report["spikes"]["b"]["error"])
        finally:
            spikes.host_summary = original

    def test_bad_args_exit_2(self):
        self.assertEqual(spikes.main(["--spike", "q"], stdout=io.StringIO()), 2)


if __name__ == "__main__":
    unittest.main()
