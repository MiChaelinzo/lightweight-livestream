import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import gui, selftest


class FakeTcl:
    def call(self, *args):
        if args == ("info", "patchlevel"):
            return "8.6.13"
        raise AssertionError(args)


def fake_importer(name):
    if name == "tkinter":
        return SimpleNamespace(Tcl=FakeTcl, TkVersion=8.6)
    return object()


class SelfTestReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "app")
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(self.root)
        self.environ = {"HOME": self.state, "XDG_CONFIG_HOME": self.state}

    def report(self, **overrides):
        options = dict(
            root=self.root,
            environ=self.environ,
            platform_name="linux",
            importer=fake_importer,
            ffmpeg_finder=lambda: None,
            frozen=True,
        )
        options.update(overrides)
        return selftest.collect_report(**options)

    def test_missing_ffmpeg_is_a_warning_not_an_integrity_failure(self):
        report = self.report()
        self.assertTrue(report["ok"])
        self.assertTrue(report["frozen"])
        self.assertEqual(report["platform"], "linux")
        ffmpeg = next(c for c in report["checks"] if c["name"] == "ffmpeg")
        self.assertEqual(ffmpeg["status"], "warn")
        self.assertTrue(os.path.isdir(self.state))
        self.assertFalse([n for n in os.listdir(self.state) if n.startswith(".lightstream-self-test-")])

    def test_portable_mode_keeps_the_writable_state_probe_under_app_root(self):
        open(os.path.join(self.root, "portable.flag"), "w").close()
        report = self.report()
        self.assertTrue(report["portable"])
        self.assertEqual(report["state_path"], os.path.join(self.root, "data", "config.json"))
        self.assertTrue(report["ok"])

    def test_import_tcl_root_and_writable_failures_are_integrity_failures(self):
        def broken_import(name):
            if name == selftest.REQUIRED_IMPORTS[0]:
                raise ImportError("not bundled")
            return fake_importer(name)

        cases = [
            self.report(importer=broken_import),
            self.report(tcl_factory=lambda: (_ for _ in ()).throw(RuntimeError("no Tcl"))),
            self.report(root=os.path.join(self.tmp.name, "missing")),
            self.report(writable_probe=lambda path: (_ for _ in ()).throw(PermissionError("read only"))),
        ]
        for report in cases:
            with self.subTest(checks=report["checks"]):
                self.assertFalse(report["ok"])
                self.assertTrue(any(c["status"] == "fail" for c in report["checks"]))

    def test_broken_ffmpeg_discovery_is_integrity_failure_but_invalid_binary_is_warning(self):
        broken = self.report(ffmpeg_finder=lambda: (_ for _ in ()).throw(RuntimeError("bug")))
        self.assertFalse(broken["ok"])
        invalid = self.report(ffmpeg_finder=lambda: "/tmp/ffmpeg",
                              ffmpeg_validator=lambda path: (False, "wrong binary"))
        self.assertTrue(invalid["ok"])
        status = next(c for c in invalid["checks"] if c["name"] == "ffmpeg")
        self.assertEqual(status["status"], "warn")

    def test_plain_and_json_output_are_machine_and_human_readable(self):
        kwargs = dict(root=self.root, environ=self.environ, platform_name="linux",
                      importer=fake_importer, ffmpeg_finder=lambda: None)
        plain = io.StringIO()
        self.assertEqual(selftest.main(out=plain, **kwargs), 0)
        self.assertIn("Result: PASS", plain.getvalue())
        structured = io.StringIO()
        self.assertEqual(selftest.main(json_output=True, out=structured, **kwargs), 0)
        payload = json.loads(structured.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["checks"], list)


class SelfTestEntryPointTests(unittest.TestCase):
    def test_gui_self_test_runs_before_tk_window_creation(self):
        out = io.StringIO()
        with mock.patch("lightstream.selftest.main", return_value=0) as run, \
                mock.patch.object(gui.tk, "Tk", side_effect=AssertionError("window opened")):
            self.assertEqual(gui.main(["--self-test", "--self-test-json"], out=out), 0)
        run.assert_called_once_with(json_output=True, out=out)

    def test_cli_rejects_json_without_self_test(self):
        out = io.StringIO()
        self.assertEqual(__import__("lightstream.cli", fromlist=["main"]).main(
            ["gui", "--self-test-json"], out), 2)
        self.assertIn("requires --self-test", out.getvalue())

    def test_source_cli_self_test_needs_no_display(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ,
                       PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"),
                       HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
                       PATH="")
            env.pop("DISPLAY", None)
            result = subprocess.run(
                [sys.executable, "-m", "lightstream", "gui", "--self-test",
                 "--self-test-json"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(next(c for c in payload["checks"] if c["name"] == "ffmpeg")["status"],
                         "warn")


if __name__ == "__main__":
    unittest.main()
