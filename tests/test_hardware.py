import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import hardware
from lightstream.command import build_command
from lightstream.config import resolve_settings
from lightstream.encoders import choose_encoder, choose_working_encoder

WMIC = "Name\r\nIntel(R) HD Graphics 620\r\nNVIDIA GeForce MX250\r\n\r\n"
LSPCI = (
    "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics 620 (rev 07)\n"
    "00:1f.3 Audio device: Intel Corporation Sunrise Point-LP HD Audio\n"
    "01:00.0 3D controller: NVIDIA Corporation GP108M [GeForce MX250] (rev a1)\n"
)


class Result:
    def __init__(self, stdout):
        self.stdout = stdout


class GpuParsingTests(unittest.TestCase):
    def test_parse_wmic(self):
        self.assertEqual(["Intel(R) HD Graphics 620", "NVIDIA GeForce MX250"],
                         hardware.parse_gpu_names(WMIC))

    def test_parse_lspci_ignores_non_gpu_lines(self):
        self.assertEqual(
            ["Intel Corporation UHD Graphics 620 (rev 07)",
             "NVIDIA Corporation GP108M [GeForce MX250] (rev a1)"],
            hardware.parse_gpu_names(LSPCI))

    def test_classify(self):
        c = hardware.classify_gpus
        self.assertEqual("intel_hd", c(["Intel(R) HD Graphics 620"]))
        self.assertEqual("intel_hd", c(["Intel(R) Iris(R) Xe Graphics"]))
        self.assertEqual("nvidia_mx", c(["NVIDIA GeForce MX250"]))
        self.assertEqual("nvidia_mx", c(["Intel(R) HD Graphics 620",
                                         "NVIDIA GeForce MX250"]))
        self.assertEqual("nvidia", c(["NVIDIA GeForce GTX 1050"]))
        self.assertEqual("generic", c(["AMD Radeon R5"]))
        self.assertEqual("generic", c([]))

    def test_detect_gpu_names_uses_injected_runner(self):
        seen = []

        def run(cmd, **kwargs):
            seen.append(cmd)
            return Result(WMIC)

        self.assertEqual(2, len(hardware.detect_gpu_names("windows", run)))
        self.assertEqual(["wmic", "path", "win32_VideoController", "get", "name"],
                         seen[0])
        hardware.detect_gpu_names("linux", run)
        self.assertEqual(["lspci"], seen[1])
        self.assertEqual([], hardware.detect_gpu_names("macos", run))

    def test_detect_gpu_names_tool_missing(self):
        def run(cmd, **kwargs):
            raise OSError("no wmic")

        self.assertEqual([], hardware.detect_gpu_names("windows", run))

        def slow(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 5)

        self.assertEqual([], hardware.detect_gpu_names("linux", slow))


class ProfileTests(unittest.TestCase):
    def test_get_profile_unknown(self):
        with self.assertRaises(ValueError):
            hardware.get_profile("voodoo")

    def test_cap_preset(self):
        cap = hardware.cap_preset_name
        self.assertEqual("light", cap("intel_hd", "720p60"))
        self.assertEqual("potato", cap("intel_hd", "potato"))
        self.assertEqual("720p60", cap("intel_hd", "720p60", forced=True))
        self.assertEqual("720p60", cap("nvidia_mx", "720p60"))

    def test_tuned_encoder_args(self):
        self.assertEqual(
            ["-c:v", "h264_qsv", "-preset", "veryfast", "-look_ahead", "0",
             "-async_depth", "1"],
            hardware.tuned_encoder_args("intel_hd", "h264_qsv"))
        nv = hardware.tuned_encoder_args("nvidia_mx", "h264_nvenc")
        self.assertIn("-surfaces", nv)
        self.assertEqual("0", nv[nv.index("-rc-lookahead") + 1])
        self.assertIsNone(hardware.tuned_encoder_args("intel_hd", "libx264"))
        self.assertIsNone(hardware.tuned_encoder_args("generic", "h264_qsv"))

    def test_low_resource_input_args(self):
        args = ["-fflags", "nobuffer", "-thread_queue_size", "64", "-f", "gdigrab",
                "-rtbufsize", "32M", "-i", "desktop", "-f", "lavfi", "-i", "x"]
        self.assertEqual(
            ["-fflags", "nobuffer", "-thread_queue_size", "64", "-f", "gdigrab",
             "-rtbufsize", "32M", "-probesize", "32k", "-analyzeduration", "0",
             "-i", "desktop", "-f", "lavfi", "-probesize", "32k",
             "-analyzeduration", "0", "-i", "x"],
            hardware.low_resource_input_args(args))

    def test_low_resource_output_args(self):
        out = hardware.low_resource_output_args("intel_hd", "libx264", False)
        self.assertEqual(["-filter_threads", "1", "-sws_flags", "fast_bilinear",
                          "-threads", "2"], out)
        out = hardware.low_resource_output_args("intel_hd", "h264_qsv", True)
        self.assertEqual(["-filter_complex_threads", "1", "-sws_flags",
                          "fast_bilinear"], out)

    def test_encoder_order_param(self):
        available = {"h264_nvenc", "h264_qsv"}
        order = hardware.get_profile("intel_hd").encoder_order
        self.assertEqual("h264_qsv", choose_encoder(available, order=order))
        self.assertEqual("h264_nvenc", choose_encoder(available))
        self.assertEqual("libx264", choose_encoder({"h264_nvenc"}, order=order))
        self.assertEqual("h264_vaapi", choose_encoder({"h264_vaapi"}, order=order))
        self.assertEqual("libx264", choose_working_encoder(
            "ffmpeg", {"h264_nvenc"}, order=order))


class HardwareCommandTests(unittest.TestCase):
    def test_intel_hd_windows_qsv_command(self):
        s = resolve_settings({"hardware": "intel_hd"}, {})
        argv = build_command(s, "K", "windows", "h264_qsv")
        self.assertIn("-async_depth", argv)
        self.assertIn("32M", argv)
        self.assertEqual(1, argv.count("-probesize"))  # capture input only
        self.assertEqual(["-filter_threads", "1", "-sws_flags", "fast_bilinear"],
                         argv[argv.index("-filter_threads"):
                              argv.index("-filter_threads") + 4])
        self.assertNotIn("-threads", argv)

    def test_libx264_gets_thread_limit(self):
        s = resolve_settings({"hardware": "generic"}, {})
        argv = build_command(s, "K", "linux", "libx264")
        self.assertEqual("2", argv[argv.index("-threads") + 1])

    def test_config_caps_preset_for_intel_hd(self):
        s = resolve_settings({"preset": "720p60", "hardware": "intel_hd"}, {})
        self.assertEqual((854, 480, 30), (s.width, s.height, s.fps))
        s = resolve_settings({"preset": "720p60", "hardware": "intel_hd",
                              "force_preset": True}, {})
        self.assertEqual(60, s.fps)

    def test_unknown_hardware_rejected(self):
        with self.assertRaises(ValueError):
            resolve_settings({"hardware": "voodoo"}, {})


if __name__ == "__main__":
    unittest.main()
