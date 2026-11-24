import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import network as nw

ROUTE = ("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
         "wlan0\t00000000\t012BA8C0\t0003\t0\t0\t600\t00000000\n"
         "wlan0\t0000A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\n")


def summary(**kw):
    base = {"recent_speed": 1.0, "recent_bitrate_kbps": 1000.0, "samples": 100,
            "recent_fps": 30.0, "dup_frames": 0}
    base.update(kw)
    return base


class CongestionTests(unittest.TestCase):
    def kinds(self, s, target=1000, kind=nw.KIND_RTMP, cpu=None):
        return [f.kind for f in nw.detect_congestion(s, target, kind, cpu)]

    def test_healthy_has_no_findings(self):
        self.assertEqual([], self.kinds(summary()))

    def test_slow_with_free_cpu_is_backpressure_on_rtmp(self):
        self.assertEqual(["backpressure"], self.kinds(summary(recent_speed=0.8), cpu=40))

    def test_slow_with_busy_cpu_is_not_blamed_on_network(self):
        self.assertEqual([], self.kinds(summary(recent_speed=0.8), cpu=97))

    def test_low_bitrate_with_good_speed(self):
        self.assertEqual(["bitrate_below_target"],
                         self.kinds(summary(recent_bitrate_kbps=300.0)))

    def test_dup_frames(self):
        self.assertIn("duplicated_frames", self.kinds(summary(dup_frames=500)))

    def test_unknown_speed_gives_nothing(self):
        self.assertEqual([], self.kinds(summary(recent_speed=None)))

    def test_loss_only_for_srt_and_udp(self):
        self.assertNotIn("loss_not_read", self.kinds(summary()))
        self.assertIn("loss_not_read", self.kinds(summary(), kind=nw.KIND_SRT))
        self.assertFalse(nw.packet_loss_reportable(nw.KIND_RTMP))
        self.assertTrue(nw.packet_loss_reportable(nw.KIND_UDP))

    def test_output_kind(self):
        self.assertEqual("srt", nw.output_kind("srt://h:1?streamid=x"))
        self.assertEqual("rtmp", nw.output_kind("rtmps://h/a/k"))
        self.assertEqual("udp", nw.output_kind("udp://h:1"))


class LinkTests(unittest.TestCase):
    def test_linux_wifi_and_hotspot_hint(self):
        link = nw.probe_linux(lambda p: ROUTE, lambda p: True)
        self.assertEqual("wifi", link.kind)
        self.assertTrue(link.hotspot_hint)  # 192.168.43.1

    def test_linux_ethernet(self):
        link = nw.probe_linux(lambda p: ROUTE.replace("wlan0", "eth0"), lambda p: False)
        self.assertEqual(("ethernet", False), (link.kind, link.hotspot_hint))

    def test_missing_route_table_is_na(self):
        def boom(path):
            raise OSError("none")
        self.assertEqual("n/a", nw.probe_linux(boom).kind)

    def test_windows_and_macos_parsers(self):
        self.assertEqual("wifi", nw.parse_netsh_wlan("    State                  : connected").kind)
        self.assertEqual("n/a", nw.parse_netsh_wlan("    State : disconnected").kind)
        self.assertEqual("wifi", nw.parse_networksetup("Current Wi-Fi Network: Home").kind)
        self.assertEqual("n/a", nw.parse_networksetup("You are not associated").kind)

    def test_missing_command_degrades_to_na(self):
        def missing(*a, **k):
            raise FileNotFoundError("netsh")
        self.assertEqual("n/a", nw.detect_link("windows", run=missing).kind)
        self.assertEqual("n/a", nw.detect_link("plan9").kind)

    def test_wifi_advice_needs_real_instability(self):
        wifi = nw.LinkInfo("wifi", False, "wlan0")
        self.assertEqual([], nw.link_advice(wifi, [1.0, 1.0, 1.0], 0))
        self.assertEqual(1, len(nw.link_advice(wifi, [1.0, 0.7, 1.0, 0.6], 0)))
        self.assertEqual(1, len(nw.link_advice(wifi, [1.0], 2)))
        eth = nw.LinkInfo("ethernet", False, "eth0")
        self.assertEqual([], nw.link_advice(eth, [1.0, 0.5], 3))

    def test_hotspot_advice(self):
        self.assertEqual(1, len(nw.link_advice(nw.LinkInfo("wifi", True, "gw"), [1.0], 0)))


if __name__ == "__main__":
    unittest.main()
