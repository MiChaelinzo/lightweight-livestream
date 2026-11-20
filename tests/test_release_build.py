import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import __version__, portable
from tools import build_release as br


class FakeRun:
    """Pretends to be PyInstaller: creates the output the real tool would."""

    def __init__(self, target, returncode=0, produce=True):
        self.target, self.returncode, self.produce = target, returncode, produce
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[1:3] == ["-m", "PyInstaller"] and self.produce and self.returncode == 0:
            dist = cmd[cmd.index("--distpath") + 1]
            os.makedirs(dist, exist_ok=True)
            if self.target == "macos":
                os.makedirs(os.path.join(dist, "LightStream.app", "Contents"))
            else:
                name = "LightStream.exe" if self.target == "windows" else "LightStream"
                with open(os.path.join(dist, name), "wb") as fh:
                    fh.write(b"fake-binary")
        return subprocess.CompletedProcess(cmd, self.returncode)


def has_pyinstaller(name):
    return object()


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "release")

    def tearDown(self):
        self.tmp.cleanup()

    def test_command_per_platform(self):
        win = br.pyinstaller_command("windows", "e.py", "d", "w")
        mac = br.pyinstaller_command("macos", "e.py", "d", "w")
        lin = br.pyinstaller_command("linux", "e.py", "d", "w")
        self.assertIn("--onefile", win)
        self.assertIn("--windowed", win)
        self.assertIn("--onedir", mac)
        self.assertIn("--osx-bundle-identifier", mac)
        self.assertIn("--onefile", lin)
        self.assertNotIn("--windowed", lin)
        for cmd in (win, mac, lin):
            self.assertNotIn("--add-binary", cmd)
            self.assertFalse(any(part.endswith(".spec") for part in cmd))

    def test_archive_names(self):
        self.assertEqual(br.archive_name("1.2.3", "windows"), "LightStream-1.2.3-windows-portable.zip")
        self.assertEqual(br.archive_name("1.2.3", "macos"), "LightStream-1.2.3-macos.zip")
        self.assertEqual(br.archive_name("1.2.3", "linux", "AMD64"), "LightStream-1.2.3-linux-x86_64.tar.gz")

    def test_detect_platform(self):
        self.assertEqual(br.detect_platform("win32"), "windows")
        self.assertEqual(br.detect_platform("darwin"), "macos")
        self.assertEqual(br.detect_platform("linux"), "linux")

    def test_windows_zip_has_exe_flag_and_folders_without_ffmpeg(self):
        run = FakeRun("windows")
        names = br.build("windows", "9.9.9", self.out, run=run, find_module=has_pyinstaller)
        self.assertEqual(names, ["LightStream-9.9.9-windows-portable.zip", "SHA256SUMS.txt"])
        with zipfile.ZipFile(os.path.join(self.out, names[0])) as zf:
            members = set(zf.namelist())
        for expected in ("LightStreamPortable/LightStream.exe", "LightStreamPortable/portable.flag",
                         "LightStreamPortable/scenes/", "LightStreamPortable/ffmpeg/PUT-FFMPEG-HERE.txt"):
            self.assertIn(expected, members)
        self.assertFalse([m for m in members if m.endswith("ffmpeg.exe")])

    def test_linux_tarball_has_executable_and_readme(self):
        run = FakeRun("linux")
        names = br.build("linux", "9.9.9", self.out, run=run, find_module=has_pyinstaller,
                         machine="x86_64")
        with tarfile.open(os.path.join(self.out, names[0])) as tf:
            self.assertEqual(sorted(tf.getnames()), ["LightStream", "README.txt"])
            self.assertTrue(tf.getmember("LightStream").mode & 0o111)

    def test_macos_zip_and_dmg_when_hdiutil_exists(self):
        run = FakeRun("macos")
        names = br.build("macos", "9.9.9", self.out, run=run, find_module=has_pyinstaller,
                         which=lambda n: "/usr/bin/" + n if n == "hdiutil" else None)
        self.assertIn("LightStream-9.9.9-macos.zip", names)
        hdiutil = [c for c in run.calls if c[0] == "hdiutil"]
        self.assertEqual(len(hdiutil), 1)
        self.assertEqual(names.count("LightStream-9.9.9-macos.dmg"), 0)  # fake hdiutil wrote nothing
        no_dmg = br.build("macos", "9.9.9", self.out, run=FakeRun("macos"),
                          find_module=has_pyinstaller, which=lambda n: None)
        self.assertEqual(no_dmg, ["LightStream-9.9.9-macos.zip", "SHA256SUMS.txt"])

    def test_checksums_match_files(self):
        names = br.build("linux", "1.0.0", self.out, run=FakeRun("linux"),
                         find_module=has_pyinstaller, machine="x86_64")
        with open(os.path.join(self.out, "SHA256SUMS.txt"), encoding="utf-8") as fh:
            line = fh.read()
        with open(os.path.join(self.out, names[0]), "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(line, "%s  %s\n" % (digest, names[0]))

    def test_missing_pyinstaller_is_a_clear_error(self):
        with self.assertRaises(br.BuildError) as ctx:
            br.build("linux", "1.0.0", self.out, run=FakeRun("linux"), find_module=lambda n: None)
        self.assertIn("pip install pyinstaller", str(ctx.exception))
        err = io.StringIO()
        with redirect_stderr(err):
            code = br.main(["--platform", "linux", "--output", self.out], run=FakeRun("linux"),
                           find_module=lambda n: None)
        self.assertEqual(code, 1)

    def test_pyinstaller_failure_and_missing_output(self):
        with self.assertRaises(br.BuildError):
            br.build("linux", "1.0.0", self.out, run=FakeRun("linux", returncode=3),
                     find_module=has_pyinstaller)
        with self.assertRaises(br.BuildError):
            br.build("windows", "1.0.0", self.out, run=FakeRun("windows", produce=False),
                     find_module=has_pyinstaller)

    def test_dry_run_prints_plan_and_builds_nothing(self):
        run = FakeRun("linux")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = br.main(["--dry-run", "--platform", "windows", "--output", self.out], run=run)
        self.assertEqual(code, 0)
        self.assertEqual(run.calls, [])
        self.assertFalse(os.path.exists(self.out))
        text = buf.getvalue()
        self.assertIn("LightStream-%s-windows-portable.zip" % __version__, text)
        self.assertIn("FFmpeg: not bundled", text)


class FfmpegHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make_file(self, name="ffmpeg-custom"):
        path = os.path.join(self.dir, name)
        open(path, "w").close()
        return path

    def test_guidance_per_platform(self):
        self.assertIn("gyan.dev", portable.ffmpeg_guidance("win32"))
        self.assertIn("brew install ffmpeg", portable.ffmpeg_guidance("darwin"))
        self.assertIn("apt install ffmpeg", portable.ffmpeg_guidance("linux"))
        for name in ("win32", "darwin", "linux"):
            self.assertIn("https://ffmpeg.org/download.html", portable.ffmpeg_guidance(name))
        self.assertEqual(portable.ffmpeg_download_url("win32"), portable.WINDOWS_BUILDS_URL)
        self.assertEqual(portable.ffmpeg_download_url("linux"), portable.FFMPEG_DOWNLOAD_URL)

    def test_validate_ok(self):
        path = self.make_file()
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "ffmpeg version 6.0\nmore", "")
        self.assertEqual(portable.validate_ffmpeg(path, run=run), (True, "ffmpeg version 6.0"))

    def test_validate_rejects_missing_wrong_and_failing(self):
        path = self.make_file()
        ok, _ = portable.validate_ffmpeg(os.path.join(self.dir, "nope"))
        self.assertFalse(ok)
        wrong = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "hello", "")
        self.assertFalse(portable.validate_ffmpeg(path, run=wrong)[0])
        failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "ffmpeg version", "")
        self.assertFalse(portable.validate_ffmpeg(path, run=failing)[0])

        def boom(cmd, **kw):
            raise OSError("not executable")
        self.assertFalse(portable.validate_ffmpeg(path, run=boom)[0])

    def test_save_keeps_other_settings_and_find_ffmpeg_uses_it(self):
        chosen = self.make_file()
        cfg = os.path.join(self.dir, "sub", "config.json")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w") as fh:
            json.dump({"platform": "youtube"}, fh)
        portable.save_configured_ffmpeg(chosen, cfg)
        with open(cfg) as fh:
            self.assertEqual(json.load(fh), {"platform": "youtube", "ffmpeg_path": chosen})
        self.assertEqual(portable.configured_ffmpeg(cfg), chosen)
        empty_root = os.path.join(self.dir, "root")
        os.makedirs(empty_root)
        found = portable.find_ffmpeg(empty_root, which=lambda n: "/usr/bin/ffmpeg", configured=chosen)
        self.assertEqual(found, chosen)

    def test_find_ffmpeg_falls_back_to_path_and_ignores_stale_config(self):
        root = os.path.join(self.dir, "root")
        os.makedirs(root)
        which = lambda n: "/usr/bin/ffmpeg"
        self.assertEqual(portable.find_ffmpeg(root, which=which), "/usr/bin/ffmpeg")
        stale = os.path.join(self.dir, "gone")
        self.assertEqual(portable.find_ffmpeg(root, which=which, configured=stale), "/usr/bin/ffmpeg")
        cfg = os.path.join(self.dir, "config.json")
        with open(cfg, "w") as fh:
            json.dump({"ffmpeg_path": stale}, fh)
        self.assertIsNone(portable.configured_ffmpeg(cfg))
        self.assertIsNone(portable.configured_ffmpeg(os.path.join(self.dir, "missing.json")))


if __name__ == "__main__":
    unittest.main()
