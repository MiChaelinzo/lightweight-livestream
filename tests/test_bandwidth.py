import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import bandwidth
from lightstream.cli import main


class RecommendTests(unittest.TestCase):
    def test_headroom_is_applied(self):
        rec = bandwidth.recommend(2000, "twitch")  # usable 1400
        self.assertEqual(rec.preset, "light")
        self.assertLessEqual(rec.video_kbps + rec.audio_kbps, 1400)

    def test_fast_connection_gets_heaviest_preset(self):
        self.assertEqual(bandwidth.recommend(20000, "youtube").preset, "720p60")

    def test_very_slow_connection_reduces_bitrate(self):
        rec = bandwidth.recommend(800, "twitch")  # usable 560
        self.assertEqual(rec.preset, "potato")
        self.assertEqual(rec.video_kbps, 560 - 64)

    def test_floor_bitrate(self):
        self.assertEqual(bandwidth.recommend(200, "twitch").video_kbps,
                         bandwidth.MIN_VIDEO_KBPS)

    def test_intel_hd_caps_preset(self):
        self.assertEqual(bandwidth.recommend(20000, "twitch", "intel_hd").preset,
                         "light")

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            bandwidth.recommend(0, "twitch")
        with self.assertRaises(ValueError):
            bandwidth.recommend(1000, "nowhere")
        with self.assertRaises(ValueError):
            bandwidth.mbps_to_kbps("fast")


class MeasureTests(unittest.TestCase):
    def test_measure_with_fakes(self):
        times = iter([0.0, 2.0])
        sent = []
        kbps = bandwidth.measure_upload(
            "https://example.test/up", post=lambda url, data: sent.append(len(data)),
            clock=lambda: next(times), payload_bytes=250000)
        self.assertEqual(sent, [250000])
        self.assertEqual(kbps, 1000)

    def test_requires_explicit_endpoint(self):
        with self.assertRaises(ValueError):
            bandwidth.measure_upload(None)
        with self.assertRaises(ValueError):
            bandwidth.measure_upload("ftp://x")

    def test_rejects_plain_http(self):
        sent = []
        with self.assertRaises(ValueError) as caught:
            bandwidth.measure_upload("http://example.test/up",
                                     post=lambda u, d: sent.append(u))
        self.assertIn("https://", str(caught.exception))
        self.assertEqual([], sent)

    def test_zero_elapsed(self):
        with self.assertRaises(ValueError):
            bandwidth.measure_upload("https://x", post=lambda u, d: None,
                                     clock=lambda: 1.0)


class CommandTests(unittest.TestCase):
    def test_bandwidth_command_manual(self):
        out = io.StringIO()
        code = main(["bandwidth", "--upload-mbps", "3"], out=out)
        self.assertEqual(code, 0)
        self.assertIn("--preset", out.getvalue())

    def test_bandwidth_command_without_source_errors(self):
        out = io.StringIO()
        self.assertEqual(main(["bandwidth"], out=out), 2)


if __name__ == "__main__":
    unittest.main()


class LatencyTests(unittest.TestCase):
    def test_host_port_drops_the_key(self):
        self.assertEqual(("live.example.com", 1935),
                         bandwidth.rtmp_host_port("rtmp://live.example.com/app/SECRETKEY"))
        self.assertEqual(("a.tv", 443), bandwidth.rtmp_host_port("rtmps://a.tv/x/KEY"))
        self.assertEqual(("a.tv", 1936), bandwidth.rtmp_host_port("rtmp://a.tv:1936/x"))
        with self.assertRaises(ValueError):
            bandwidth.rtmp_host_port("http://a.tv/x")

    def test_connect_time_uses_injected_socket_and_clock(self):
        ticks = iter([10.0, 10.05])
        closed = []

        class Sock:
            def close(self):
                closed.append(True)
        seen = []

        def connect(addr, timeout):
            seen.append((addr, timeout))
            return Sock()
        ms = bandwidth.measure_connect_latency("h", 1935, connect, lambda: next(ticks))
        self.assertAlmostEqual(50.0, ms)
        self.assertEqual([(("h", 1935), bandwidth.LATENCY_TIMEOUT_SECONDS)], seen)
        self.assertEqual([True], closed)

    def test_failure_is_none(self):
        def connect(addr, timeout):
            raise OSError("timed out")
        self.assertIsNone(bandwidth.measure_connect_latency("h", 1, connect))
