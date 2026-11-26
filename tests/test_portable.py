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
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["config", "ffmpeg", "portable.flag", "recordings", "scenes"])
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

    def test_frozen_entry_propagates_self_test_exit_code(self):
        self.assertIn("raise SystemExit(main())", self.builder.ENTRY_SOURCE)


class PortableFoldersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        open(os.path.join(self.root, "portable.flag"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_collection_dir_uses_portable_scenes_folder(self):
        from lightstream.scene_collections import collection_dir
        self.assertEqual(collection_dir("/x/scenes.json", root=self.root, environ={}),
                         os.path.join(self.root, "scenes"))

    def test_collection_dir_normal_when_not_portable(self):
        from lightstream.scene_collections import collection_dir
        other = os.path.join(self.root, "none")
        os.makedirs(other)
        self.assertEqual(collection_dir("/x/scenes.json", root=other, environ={}),
                         os.path.join("/x", "scenes"))

    def test_default_recording_goes_to_recordings_when_portable(self):
        from lightstream.config import DEFAULT_RECORDING_FILE, default_recording_path
        self.assertEqual(default_recording_path(self.root, {}),
                         os.path.join(self.root, "recordings", DEFAULT_RECORDING_FILE))

    def test_default_recording_plain_when_not_portable(self):
        from lightstream.config import DEFAULT_RECORDING_FILE, default_recording_path
        other = os.path.join(self.root, "none")
        os.makedirs(other)
        self.assertEqual(default_recording_path(other, {}), DEFAULT_RECORDING_FILE)


class PortableStatePathTests(unittest.TestCase):
    """With portable.flag, every kind of saved state lands inside the app folder.

    app_root is pointed at a temp folder and HOME, XDG_CONFIG_HOME and APPDATA
    at a second, empty one. After writing each kind of state through the real
    functions, nothing may exist in the second folder. VERIFIED on Linux only;
    Windows paths are built by the same os.path code but not run here.
    """

    def setUp(self):
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "app")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.root)
        os.makedirs(self.home)
        open(os.path.join(self.root, "portable.flag"), "w").close()
        env = {"HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
               "APPDATA": os.path.join(self.home, "AppData"), "USERPROFILE": self.home}
        patches = [mock.patch.dict(os.environ, env),
                   mock.patch("lightstream.portable.app_root", return_value=self.root)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("LIGHTSTREAM_PORTABLE", None)
        self.data = os.path.join(self.root, "data")

    def tearDown(self):
        self.tmp.cleanup()

    def _inside(self, path, folder):
        folder = os.path.realpath(folder)
        return os.path.realpath(path).startswith(folder + os.sep)

    def _write_all_state(self):
        """Write one file of every kind of state. Returns {label: path}."""
        import io
        from lightstream import analytics, cli, gui_controller, gui_theme, highlights, plugins
        from lightstream import scene_collections
        from lightstream.config import config_path, scenes_path, default_recording_path
        paths = {}
        paths["config"] = config_path()
        os.makedirs(os.path.dirname(paths["config"]))
        with open(paths["config"], "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        paths["ffmpeg_choice"] = paths["config"]
        portable.save_configured_ffmpeg(os.path.join(self.root, "ffmpeg"))
        paths["scenes"] = scenes_path()
        paths["gui_prefs"] = gui_controller.prefs_path()
        gui_controller.save_prefs(paths["gui_prefs"], {"profile": "potato_pc"})
        paths["ui.json"] = gui_theme.ui_prefs_path(paths["gui_prefs"])
        gui_theme.save_ui_prefs(paths["ui.json"], "dark", False)
        reports = analytics.reports_dir()
        paths["history"] = analytics.append_history(reports, {"date": "2026-01-01"})
        paths["snapshot"] = analytics.save_performance_snapshot(reports, {"health": 90})
        paths["crash_report"] = analytics.write_crash_report(
            os.path.join(os.path.dirname(paths["config"]), analytics.CRASH_DIRNAME),
            analytics.build_crash_report(ValueError("x"), "0", "linux"))
        out = io.StringIO()
        args = cli.build_parser().parse_args(["support-bundle"])
        cli.cmd_support_bundle(args, out, find=lambda: None,
                               probe=lambda ffmpeg: set(), environ={})
        paths["support_bundle"] = os.path.join(
            os.path.dirname(paths["config"]), analytics.BUNDLE_FILENAME)
        paths["plugins_dir"] = plugins.plugins_dir(paths["config"])
        os.makedirs(paths["plugins_dir"])
        paths["scene_collection"] = os.path.join(
            scene_collections.collection_dir(paths["scenes"]), "one.json")
        os.makedirs(os.path.dirname(paths["scene_collection"]))
        with open(paths["scene_collection"], "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        paths["recording_cli"] = default_recording_path()
        paths["recording_gui"] = gui_controller.recording_path()
        for key in ("recording_cli", "recording_gui"):
            os.makedirs(os.path.dirname(paths[key]), exist_ok=True)
            with open(paths[key], "wb") as fh:
                fh.write(b"x")
        paths["highlights_out"] = highlights.default_out_dir(paths["recording_cli"])
        os.makedirs(paths["highlights_out"])
        return paths

    def test_settings_history_crashes_bundle_and_plugins_live_under_data(self):
        paths = self._write_all_state()
        for label in ("config", "ffmpeg_choice", "scenes", "gui_prefs", "ui.json",
                      "history", "snapshot", "crash_report", "support_bundle",
                      "plugins_dir"):
            with self.subTest(label):
                self.assertTrue(self._inside(paths[label], self.data), paths[label])

    def test_scenes_recordings_and_highlights_stay_in_the_app_folder(self):
        # By design (see portable.py) these are siblings of data/, not inside it.
        paths = self._write_all_state()
        for label in ("scene_collection", "recording_cli", "recording_gui",
                      "highlights_out"):
            with self.subTest(label):
                self.assertTrue(self._inside(paths[label], self.root), paths[label])

    def test_nothing_is_written_outside_the_app_folder(self):
        self._write_all_state()
        self.assertEqual([], os.listdir(self.home))
        self.assertEqual([os.path.basename(self.root), os.path.basename(self.home)],
                         sorted(os.listdir(self.tmp.name), key=lambda n: n != "app"))

    def test_environment_flag_alone_also_keeps_state_in_data(self):
        os.remove(os.path.join(self.root, "portable.flag"))
        os.environ["LIGHTSTREAM_PORTABLE"] = "1"
        from lightstream.config import config_path
        self.assertEqual(os.path.join(self.data, "config.json"), config_path())


class PortableSecureStoreTests(unittest.TestCase):
    """The stream key is never written as plain text in portable mode."""

    KEY = "live_123456789_SecretKeyValue"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)

    def _tree_text(self):
        found = ""
        for folder, _, files in os.walk(self.tmp.name):
            for name in files:
                with open(os.path.join(folder, name), "rb") as fh:
                    found += fh.read().decode("latin-1")
        return found

    def test_no_backend_refuses_and_writes_nothing(self):
        from lightstream import secure_store
        store = secure_store.SecureKeyStore(
            secure_store.select_backend("linux", self.data, which=lambda name: None))
        with self.assertRaises(secure_store.SecureStoreUnavailable):
            store.save(self.KEY, opt_in=True)
        self.assertEqual([], os.listdir(self.data))

    def test_windows_blob_in_data_is_not_the_plain_key(self):
        from lightstream import secure_store
        backend = secure_store.DpapiBackend(
            os.path.join(self.data, secure_store.BLOB_FILENAME),
            protect=lambda raw: raw[::-1], unprotect=lambda blob: blob[::-1])
        secure_store.SecureKeyStore(backend).save(self.KEY, opt_in=True)
        self.assertEqual([secure_store.BLOB_FILENAME], os.listdir(self.data))
        self.assertNotIn(self.KEY, self._tree_text())

    def test_default_save_without_opt_in_writes_nothing(self):
        from lightstream import secure_store
        store = secure_store.SecureKeyStore(
            secure_store.select_backend("linux", self.data, which=lambda name: "/bin/x"))
        with self.assertRaises(secure_store.OptInRequired):
            store.save(self.KEY)
        self.assertEqual([], os.listdir(self.data))

    def test_gui_prefs_never_keep_the_key(self):
        from lightstream import gui_controller
        path = os.path.join(self.data, "gui.json")
        gui_controller.save_prefs(path, {"custom_url": "rtmp://h/app/" + self.KEY},
                                  key=self.KEY)
        self.assertNotIn(self.KEY, self._tree_text())
