import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import cli
from lightstream.scenes import EXAMPLE_SCENES, parse_scenes, write_example_scenes


class ParserTests(unittest.TestCase):
    def test_start_studio_flags(self):
        args = cli.build_parser().parse_args(
            ["start", "--scene", "a", "--scenes-file", "s.json", "--record",
             "--noise", "light", "--noise-model", "m.rnnn", "--hardware", "auto"])
        self.assertEqual(
            (args.scene, args.scenes_file, args.record, args.noise, args.hardware),
            ("a", "s.json", cli.DEFAULT_RECORDING_FILE, "light", "auto"))

    def test_record_with_name(self):
        args = cli.build_parser().parse_args(["start", "--record", "x.mkv"])
        self.assertEqual(args.record, "x.mkv")

    def test_rejects_unknown_noise(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            cli.build_parser().parse_args(["start", "--noise", "magic"])


class ResolveHardwareTests(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(cli.resolve_hardware("intel_hd", {"hardware": "nvidia"}, "linux",
                                              lambda _o: []), "intel_hd")

    def test_config_beats_detection(self):
        self.assertEqual(cli.resolve_hardware(None, {"hardware": "nvidia"}, "linux",
                                              lambda _o: ["Intel HD Graphics"]), "nvidia")

    def test_auto_detects(self):
        for flag in ("auto", None):
            self.assertEqual(cli.resolve_hardware(flag, {}, "linux",
                             lambda _o: ["Intel(R) HD Graphics 620"]), "intel_hd")
        self.assertEqual(cli.resolve_hardware("auto", {"hardware": "nvidia"}, "linux",
                         lambda _o: ["NVIDIA GeForce MX250"]), "nvidia_mx")

    def test_nothing_detected_is_generic(self):
        self.assertEqual(cli.resolve_hardware(None, {}, "linux", lambda _o: []), "generic")


class StartDryRunTests(unittest.TestCase):
    os_name = "linux"

    def run_cli(self, argv, home):
        out = io.StringIO()
        env = {"HOME": home, "XDG_CONFIG_HOME": home, "STREAM_KEY": "SECRETKEY123"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cli, "detect_gpu_names", lambda _o: ["Intel HD Graphics"]), \
                mock.patch.object(cli, "detect_os", lambda: self.os_name), \
                mock.patch.object(cli, "find_ffmpeg", lambda: None):
            code = cli.main(argv, out)
        return code, out.getvalue()

    def test_record_flag_adds_tee_and_hides_key(self):
        with tempfile.TemporaryDirectory() as d:
            code, text = self.run_cli(["start", "--dry-run", "--platform", "twitch",
                                       "--record", "copy.mkv"], d)
        self.assertEqual(code, 0)
        self.assertIn("tee", text)
        self.assertIn("copy.mkv", text)
        self.assertNotIn("SECRETKEY123", text)

    def test_scene_from_file(self):
        self.os_name = "windows"  # window capture (browser source) is Windows only
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            write_example_scenes(path)
            code, text = self.run_cli(["start", "--dry-run", "--scene", "browser-source",
                                      "--scenes-file", path], d)
        self.assertEqual(code, 0)
        self.assertIn("-filter_complex", text)

    def test_unknown_scene_is_plain_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            write_example_scenes(path)
            code, text = self.run_cli(["start", "--dry-run", "--scene", "nope",
                                      "--scenes-file", path], d)
        self.assertEqual(code, 2)
        self.assertIn("Unknown scene", text)

    def test_ai_noise_without_model_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            code, text = self.run_cli(["start", "--dry-run", "--noise", "ai"], d)
        self.assertEqual(code, 2)
        self.assertIn("Error", text)

    def test_auto_profile_applies_low_resource_args(self):
        with tempfile.TemporaryDirectory() as d:
            _code, text = self.run_cli(["start", "--dry-run"], d)
        self.assertIn("-sws_flags", text)


class ScenesCommandTests(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        return cli.main(argv, out), out.getvalue()

    def test_example_parses_and_covers_overlays(self):
        scenes = parse_scenes(EXAMPLE_SCENES)
        self.assertEqual(set(scenes), {"game-with-webcam", "browser-source",
                                       "webcam-green-screen"})

    def test_example_list_validate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "scenes.json")
            code, text = self.run_cli(["scenes", "example", "--scenes-file", path])
            self.assertEqual(code, 0)
            code, text = self.run_cli(["scenes", "list", "--scenes-file", path])
            self.assertIn("browser-source", text)
            code, text = self.run_cli(["scenes", "validate", "--scenes-file", path])
            self.assertEqual((code, "OK: 3" in text), (0, True))

    def test_example_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scenes.json")
            with open(path, "w") as fh:
                fh.write("mine")
            code, _text = self.run_cli(["scenes", "example", "--scenes-file", path])
            self.assertEqual(code, 2)
            with open(path) as fh:
                self.assertEqual(fh.read(), "mine")

    def test_validate_reports_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scenes.json")
            with open(path, "w") as fh:
                json.dump({"scenes": [{"name": "x", "sources": []}]}, fh)
            code, text = self.run_cli(["scenes", "validate", "--scenes-file", path])
            self.assertEqual(code, 2)
            self.assertIn("Scene 'x'", text)

    def test_missing_file(self):
        code, text = self.run_cli(["scenes", "list", "--scenes-file", "/nonexistent/x.json"])
        self.assertEqual(code, 1)
        self.assertIn("scenes example", text)


class DoctorTests(unittest.TestCase):
    def test_prints_gpu_profile(self):
        out = io.StringIO()
        with mock.patch.object(cli, "find_ffmpeg", lambda: None):
            cli.cmd_doctor(out, detect=lambda _o: ["NVIDIA GeForce MX250"])
        self.assertIn("Hardware profile: nvidia_mx", out.getvalue())


if __name__ == "__main__":
    unittest.main()
