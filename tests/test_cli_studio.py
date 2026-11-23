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
                             lambda _o: ["Intel(R) HD Graphics 620"]), "intel_hd_optimized")
        self.assertEqual(cli.resolve_hardware("auto", {"hardware": "nvidia"}, "linux",
                         lambda _o: ["NVIDIA GeForce MX250"]), "mx250_streamer")

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

    def test_explicit_preset_overrides_intel_cap(self):
        with tempfile.TemporaryDirectory() as d:
            _, forced = self.run_cli(["start", "--dry-run", "--preset", "720p60"], d)
            _, capped = self.run_cli(["start", "--dry-run"], d)
        self.assertIn("-r 60", forced)
        self.assertNotIn("-r 60", capped)

    def test_record_with_test_local_prints_notice(self):
        with tempfile.TemporaryDirectory() as d:
            _, text = self.run_cli(["start", "--dry-run", "--test-local", "t.mkv",
                                    "--record", "c.mkv"], d)
        self.assertIn("--record is ignored", text)

    def test_unwritable_record_folder_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "file")
            open(blocker, "w").close()
            code, text = self.run_cli(["start", "--dry-run", "--record",
                                       os.path.join(blocker, "sub", "r.mkv")], d)
        self.assertEqual(code, 2)
        self.assertIn("Cannot create the recording folder", text)
        self.assertNotIn("SECRETKEY123", text)

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
        self.assertIn("Hardware profile: mx250_streamer", out.getvalue())


class EmbeddedKeyTests(unittest.TestCase):
    def dry_run(self, url):
        out = io.StringIO()
        env = {"STREAM_KEY": "REALKEY123", "PATH": os.environ.get("PATH", "")}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cli, "find_ffmpeg", lambda: None):
            code = cli.main(["start", "--platform", "custom", "--url", url,
                             "--dry-run", "--hardware", "generic"], out=out)
        return code, out.getvalue()

    def test_plain_url_has_no_warning(self):
        code, text = self.dry_run("rtmp://ingest.example.test/app")
        self.assertEqual(0, code)
        self.assertNotIn("looks like it contains a stream key", text)
        self.assertNotIn("REALKEY123", text)

    def test_url_with_embedded_key_warns_and_is_redacted(self):
        code, text = self.dry_run("rtmp://ingest.example.test/app/LEAKEDSECRET")
        self.assertEqual(0, code)
        self.assertIn("looks like it contains a stream key", text)
        self.assertNotIn("LEAKEDSECRET", text)
        self.assertNotIn("REALKEY123", text)

    def test_embedded_key_detection(self):
        from lightstream.platforms import embedded_key_in_url as detect
        self.assertIsNone(detect("rtmp://h/app"))
        self.assertIsNone(detect("rtmp://h/app/"))
        self.assertIsNone(detect(None))
        self.assertEqual("abc", detect("rtmp://h/app/abc"))
        self.assertEqual("abc", detect("rtmp://h/app?key=abc"))
        self.assertEqual("tok", detect("rtmps://h:443/app?token=tok"))


if __name__ == "__main__":
    unittest.main()


class RecordingPathTests(unittest.TestCase):
    def test_numbered_path_keeps_first_attempt_and_adds_suffix_after(self):
        from lightstream.command import numbered_recording_path as n
        self.assertEqual("a/rec.mkv", n("a/rec.mkv", 0))
        self.assertEqual("a/rec-2.mkv", n("a/rec.mkv", 1))
        self.assertEqual("rec-3", n("rec", 2))

    def test_reconnect_does_not_reuse_recording_file(self):
        calls = []

        def fake_runner(argv, key, os_name, **kw):
            calls.append(argv[-1])
            calls.append(kw["argv_for_attempt"](1, "libx264")[-1])
            return 0
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"HOME": d, "XDG_CONFIG_HOME": d,
                                             "STREAM_KEY": "SECRETKEY123"}, clear=True), \
                mock.patch.object(cli, "detect_gpu_names", lambda _o: []), \
                mock.patch.object(cli, "detect_os", lambda: "linux"), \
                mock.patch.object(cli, "find_ffmpeg", lambda: "/bin/ffmpeg"), \
                mock.patch.object(cli, "probe_encoders", lambda _f: set()), \
                mock.patch.object(cli, "choose_working_encoder", lambda *a, **k: "libx264"), \
                mock.patch.object(cli, "run_with_reconnect", fake_runner):
            code = cli.main(["start", "--record", os.path.join(d, "rec.mkv")], out)
        self.assertEqual(0, code)
        self.assertTrue(calls[0].endswith("rec.mkv"))
        self.assertTrue(calls[1].endswith("rec-2.mkv"))
        self.assertNotIn("SECRETKEY123", out.getvalue())
