import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import portable
from lightstream.config import config_path
from tools import build_portable


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_portable_by_default(self):
        self.assertFalse(portable.is_portable(self.root, {}))

    def test_flag_file_enables_portable(self):
        open(os.path.join(self.root, "portable.flag"), "w").close()
        self.assertTrue(portable.is_portable(self.root, {}))

    def test_env_var_enables_portable_and_zero_disables(self):
        self.assertTrue(portable.is_portable(self.root, {"LIGHTSTREAM_PORTABLE": "1"}))
        self.assertFalse(portable.is_portable(self.root, {"LIGHTSTREAM_PORTABLE": "0"}))

    def test_config_path_goes_to_data_when_portable(self):
        open(os.path.join(self.root, "portable.flag"), "w").close()
        path = config_path("linux", {}, root=self.root)
        self.assertEqual(path, os.path.join(self.root, "data", "config.json"))

    def test_config_path_normal_when_not_portable(self):
        path = config_path("linux", {"XDG_CONFIG_HOME": "/x"}, root=self.root)
        self.assertEqual(path, os.path.join("/x", "lightstream", "config.json"))

    def test_bundled_ffmpeg_beats_path(self):
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        os.makedirs(os.path.join(self.root, "ffmpeg"))
        bundled = os.path.join(self.root, "ffmpeg", exe)
        open(bundled, "w").close()
        self.assertEqual(portable.find_ffmpeg(self.root, lambda n: "/usr/bin/ffmpeg"),
                         bundled)

    def test_falls_back_to_path(self):
        self.assertEqual(portable.find_ffmpeg(self.root, lambda n: "/usr/bin/ffmpeg"),
                         "/usr/bin/ffmpeg")
        self.assertIsNone(portable.find_ffmpeg(self.root, lambda n: None))

    def test_built_zip_layout(self):
        out = os.path.join(self.root, "p.zip")
        build_portable.build(out)
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        top = build_portable.TOP
        for expected in ("portable.flag", "src/lightstream/portable.py",
                         "launchers/start-gui.sh", "ffmpeg/PUT-FFMPEG-HERE.txt"):
            self.assertIn("%s/%s" % (top, expected), names)
        self.assertFalse([n for n in names if n.endswith(".pyc")])


if __name__ == "__main__":
    unittest.main()


class DoctorPortableTests(unittest.TestCase):
    def test_doctor_reports_portable_mode(self):
        import io
        from lightstream import cli
        old = os.environ.get("LIGHTSTREAM_PORTABLE")
        os.environ["LIGHTSTREAM_PORTABLE"] = "1"
        try:
            out = io.StringIO()
            cli.cmd_doctor(out)
        finally:
            if old is None:
                del os.environ["LIGHTSTREAM_PORTABLE"]
            else:
                os.environ["LIGHTSTREAM_PORTABLE"] = old
        self.assertIn("Mode: portable", out.getvalue())


class WindowsPortableBuilderTests(unittest.TestCase):
    def setUp(self):
        from tools import build_windows_portable
        self.builder = build_windows_portable
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "LightStreamPortable")

    def tearDown(self):
        self.tmp.cleanup()

    def test_layout_creates_expected_structure(self):
        self.builder.create_layout(self.out)
        for name in ("ffmpeg", "scenes", "recordings", "config"):
            self.assertTrue(os.path.isdir(os.path.join(self.out, name)), name)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "portable.flag")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "LightStream.exe")))

    def test_layout_never_bundles_ffmpeg(self):
        self.builder.create_layout(self.out)
        self.assertEqual(os.listdir(os.path.join(self.out, "ffmpeg")), ["PUT-FFMPEG-HERE.txt"])

    def test_layout_flag_name_matches_runtime(self):
        self.builder.create_layout(self.out)
        self.assertTrue(os.path.exists(os.path.join(self.out, portable.FLAG_FILE)))
        self.assertTrue(portable.is_portable(root=self.out, environ={}))

    def test_layout_is_repeatable(self):
        first = self.builder.create_layout(self.out)
        self.assertEqual(self.builder.create_layout(self.out), first)

    def test_missing_pyinstaller_gives_clear_error(self):
        os.makedirs(self.out)
        with self.assertRaises(self.builder.BuildError) as ctx:
            self.builder.build_exe(self.out, find_module=lambda name: None)
        self.assertIn("pip install pyinstaller", str(ctx.exception))

    def test_layout_only_cli_exits_zero_without_exe(self):
        self.assertEqual(self.builder.main(["--layout-only", "--output", self.out]), 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "LightStream.exe")))

    def test_failed_pyinstaller_run_is_reported(self):
        os.makedirs(self.out)

        class Result:
            returncode = 3

        with self.assertRaises(self.builder.BuildError):
            self.builder.build_exe(self.out, run=lambda cmd: Result(), find_module=lambda name: object())
