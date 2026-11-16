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
