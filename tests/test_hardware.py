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
        self.assertEqual("intel_hd_optimized", c(["Intel(R) HD Graphics 620"]))
        self.assertEqual("intel_hd_optimized", c(["Intel(R) HD Graphics 4000"]))
        self.assertEqual("intel_hd_optimized", c(["Intel(R) HD Graphics 520"]))
        self.assertEqual("intel_hd", c(["Intel(R) HD Graphics 5500"]))
        self.assertEqual("intel_hd", c(["Intel(R) Iris(R) Xe Graphics"]))
        self.assertEqual("mx250_streamer", c(["NVIDIA GeForce MX250"]))
        self.assertEqual("nvidia_mx", c(["NVIDIA GeForce MX150"]))
        self.assertEqual("optimus_mx250", c(["Intel(R) HD Graphics 620",
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
        self.assertEqual("powershell", seen[0][0])
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


class UltraLowEndProfileTests(unittest.TestCase):
    SCENE = {"scenes": [{"name": "cam", "sources": [
        {"kind": "screen"},
        {"kind": "webcam", "device": "Cam", "chromakey": {"color": "00ff00"}}]}]}

    def _scene_settings(self, hardware_name, **extra):
        from lightstream.scenes import parse_scenes
        scene = parse_scenes(self.SCENE)["cam"]
        s = resolve_settings(dict({"hardware": hardware_name, "preset": "balanced",
                                   "force_preset": True}, **extra), {})
        return s._replace(scene=scene)

    def test_intel_hd_optimized_forces_light_preset(self):
        s = resolve_settings({"preset": "720p60", "hardware": "intel_hd_optimized"}, {})
        self.assertEqual((854, 480, 30), (s.width, s.height, s.fps))

    def test_intel_hd_optimized_half_second_buffer(self):
        s = resolve_settings({"hardware": "intel_hd_optimized"}, {})
        argv = build_command(s, "K", "windows", "h264_qsv")
        self.assertEqual("%dk" % (s.video_kbps // 2), argv[argv.index("-bufsize") + 1])
        default = build_command(resolve_settings({"hardware": "generic"}, {}),
                                "K", "windows", "libx264")
        self.assertEqual("1000k", default[default.index("-bufsize") + 1])

    def test_intel_hd_optimized_caps_webcam_and_drops_chromakey(self):
        s = self._scene_settings("intel_hd_optimized")
        argv = build_command(s, "K", "linux", "libx264")
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("fps=%d," % hardware.INTEL_HD_WEBCAM_MAX_FPS, graph)
        self.assertNotIn("chromakey", graph)

    def test_other_profiles_keep_chromakey_and_default_webcam_cap(self):
        s = self._scene_settings("nvidia_mx")
        graph = build_command(s, "K", "linux", "libx264")
        graph = graph[graph.index("-filter_complex") + 1]
        self.assertIn("chromakey", graph)
        self.assertIn("fps=15,", graph)

    def test_intel_hd_optimized_disables_ai_audio_unless_explicit_cli(self):
        model = os.path.abspath(__file__)  # any existing file satisfies the model check
        from_file = resolve_settings({"hardware": "intel_hd_optimized"},
                                     {"noise": "ai", "noise_model": model})
        self.assertEqual("off", from_file.noise)
        explicit = resolve_settings({"hardware": "intel_hd_optimized", "noise": "ai",
                                     "noise_model": model}, {})
        self.assertEqual("ai", explicit.noise)
        other = resolve_settings({"hardware": "intel_hd"},
                                 {"noise": "ai", "noise_model": model})
        self.assertEqual("ai", other.noise)

    def test_mx250_prefers_nvenc_and_records_by_default(self):
        profile = hardware.get_profile("mx250_streamer")
        self.assertEqual("h264_nvenc", profile.encoder_order[0])
        s = resolve_settings({"hardware": "mx250_streamer"}, {})
        self.assertEqual("lightstream-recording.mkv", s.record_to)
        off = resolve_settings({"hardware": "mx250_streamer", "record": False}, {})
        self.assertIsNone(off.record_to)
        self.assertIsNone(resolve_settings({"hardware": "intel_hd"}, {}).record_to)

    def test_mx250_caps_bitrate_but_keeps_explicit_value(self):
        s = resolve_settings({"hardware": "mx250_streamer", "preset": "720p60",
                              "force_preset": True, "bitrate": None}, {"bitrate": 9000})
        self.assertEqual(hardware.MX250_MAX_VIDEO_KBPS, s.video_kbps)
        s = resolve_settings({"hardware": "mx250_streamer", "bitrate": 8000}, {})
        self.assertEqual(8000, s.video_kbps)

    def test_mx250_allows_webcam_overlay_filters(self):
        s = self._scene_settings("mx250_streamer")
        argv = build_command(s, "K", "windows", "h264_nvenc")
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("chromakey", graph)
        self.assertIn("p1", argv)  # tuned NVENC args


# Realistic outputs for an i7-1065G7 (Iris Plus G7) + GeForce MX250 laptop.
PS_OPTIMUS = "Intel(R) Iris(R) Plus Graphics\r\nNVIDIA GeForce MX250\r\n"
LSPCI_OPTIMUS = (
    "00:02.0 VGA compatible controller: Intel Corporation Iris Plus Graphics G7 (rev 07)\n"
    "00:1f.3 Audio device: Intel Corporation Ice Lake-LP Smart Sound Technology\n"
    "2d:00.0 3D controller: NVIDIA Corporation GP108M [GeForce MX250] (rev a1)\n")
LSPCI_MX250_ONLY = (
    "01:00.0 3D controller: NVIDIA Corporation GP108M [GeForce MX250] (rev a1)\n")
LSPCI_UHD620 = (
    "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics 620 (rev 07)\n")
LSPCI_AMD_APU = (
    "05:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] "
    "Picasso/Raven 2 [Radeon Vega Series / Radeon Vega Mobile Series] (rev c2)\n")


def classify_text(text):
    return hardware.classify_gpus(hardware.parse_gpu_names(text))


class OptimusDetectionTests(unittest.TestCase):
    def test_iris_plus_with_mx250_is_optimus(self):
        self.assertEqual("optimus_mx250", classify_text(LSPCI_OPTIMUS))
        self.assertEqual("optimus_mx250", classify_text(PS_OPTIMUS))

    def test_single_gpu_cases_unchanged(self):
        self.assertEqual("mx250_streamer", classify_text(LSPCI_MX250_ONLY))
        self.assertEqual("intel_hd_optimized", classify_text(LSPCI_UHD620))
        self.assertEqual("generic", classify_text(LSPCI_AMD_APU))
        self.assertEqual("generic", classify_text(""))

    def test_iris_plus_alone_is_intel(self):
        self.assertEqual("intel_hd", hardware.classify_gpus(
            ["Intel(R) Iris(R) Plus Graphics"]))
        self.assertEqual("intel_hd", hardware.classify_gpus(
            ["Intel(R) UHD Graphics"]))

    def test_optimus_profile_prefers_quick_sync_then_nvenc(self):
        profile = hardware.get_profile("optimus_mx250")
        self.assertEqual(("h264_qsv", "h264_nvenc"), profile.encoder_order)
        self.assertTrue(profile.record_by_default)
        self.assertEqual(hardware.MX250_MAX_VIDEO_KBPS,
                         hardware.cap_video_kbps("optimus_mx250", 9000))

    def test_optimus_tuned_args(self):
        qsv = hardware.tuned_encoder_args("optimus_mx250", "h264_qsv")
        self.assertIn("-look_ahead", qsv)
        nvenc = hardware.tuned_encoder_args("optimus_mx250", "h264_nvenc")
        self.assertIn("p1", nvenc)
        self.assertIsNone(hardware.tuned_encoder_args("optimus_mx250", "libx264"))

    def test_optimus_command_uses_quick_sync_first(self):
        encoder = choose_encoder({"h264_qsv", "h264_nvenc", "libx264"},
                                 order=hardware.get_profile("optimus_mx250").encoder_order)
        self.assertEqual("h264_qsv", encoder)


class WindowsDetectionTests(unittest.TestCase):
    def fake_run(self, outputs):
        """outputs maps the tool name to stdout text or an exception."""
        seen = []

        def run(cmd, **kwargs):
            seen.append(cmd[0])
            outcome = outputs[cmd[0]]
            if isinstance(outcome, Exception):
                raise outcome
            return Result(outcome)
        run.seen = seen
        return run

    def test_powershell_is_primary(self):
        run = self.fake_run({"powershell": PS_OPTIMUS, "wmic": WMIC})
        names = hardware.detect_gpu_names("windows", run)
        self.assertEqual(["Intel(R) Iris(R) Plus Graphics", "NVIDIA GeForce MX250"], names)
        self.assertEqual(["powershell"], run.seen)

    def test_powershell_command_shape(self):
        cmds = []
        hardware.detect_gpu_names("windows", lambda cmd, **kw: cmds.append(cmd) or Result("x"))
        self.assertEqual(["powershell", "-NoProfile", "-Command"], cmds[0][:3])
        self.assertIn("Win32_VideoController", cmds[0][3])
        self.assertIn("-ExpandProperty Name", cmds[0][3])

    def test_wmic_fallback_when_powershell_missing(self):
        run = self.fake_run({"powershell": OSError("no powershell"), "wmic": WMIC})
        self.assertEqual(2, len(hardware.detect_gpu_names("windows", run)))
        self.assertEqual(["powershell", "wmic"], run.seen)

    def test_wmic_fallback_when_powershell_prints_nothing(self):
        run = self.fake_run({"powershell": "", "wmic": WMIC})
        self.assertEqual(2, len(hardware.detect_gpu_names("windows", run)))

    def test_both_tools_failing(self):
        run = self.fake_run({"powershell": OSError("x"),
                             "wmic": subprocess.TimeoutExpired("wmic", 5)})
        self.assertEqual([], hardware.detect_gpu_names("windows", run))
        self.assertEqual(["powershell", "wmic"], run.seen)


if __name__ == "__main__":
    unittest.main()
