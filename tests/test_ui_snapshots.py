"""Pure helpers and graceful degradation of tools/ui_snapshots.py.
No Xvfb, Pillow or playwright needed."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import ui_snapshots as snap  # noqa: E402


class ParsingTests(unittest.TestCase):
    def test_size(self):
        self.assertEqual(snap.parse_size("1366x768"), (1366, 768))
        self.assertEqual(snap.parse_size("1280X720"), (1280, 720))

    def test_bad_sizes(self):
        for bad in ("1366", "axb", "10x10", ""):
            with self.assertRaises(ValueError):
                snap.parse_size(bad)

    def test_widths(self):
        self.assertEqual(snap.parse_widths("1280,390"), [1280, 390])
        with self.assertRaises(ValueError):
            snap.parse_widths("1280,x")
        with self.assertRaises(ValueError):
            snap.parse_widths("50")

    def test_pages(self):
        known = ["dashboard", "setup", "scenes"]
        self.assertEqual(snap.resolve_pages("all", known), known)
        self.assertEqual(snap.resolve_pages("scenes,dashboard", known),
                         ["scenes", "dashboard"])
        with self.assertRaises(ValueError):
            snap.resolve_pages("nope", known)
        with self.assertRaises(ValueError):
            snap.resolve_pages("", known)


class NamingTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(snap.gui_filename("dark", "setup", 1366, 768),
                         "gui-dark-setup-1366x768.png")
        self.assertEqual(snap.gui_filename("light", "setup", 1366, 768, True),
                         "gui-light-compact-setup-1366x768.png")
        self.assertEqual(snap.web_filename(390), "web-390.png")


class DisplayTests(unittest.TestCase):
    def test_pick_skips_taken(self):
        first = snap.FIRST_DISPLAY
        self.assertEqual(snap.pick_display(set()), first)
        self.assertEqual(snap.pick_display({first, first + 1}), first + 2)

    def test_pick_exhausted(self):
        everything = set(range(snap.FIRST_DISPLAY, snap.LAST_DISPLAY + 1))
        with self.assertRaises(RuntimeError):
            snap.pick_display(everything)

    def test_taken_displays_reads_sockets_and_locks(self):
        with tempfile.TemporaryDirectory() as sockets, \
                tempfile.TemporaryDirectory() as locks:
            open(os.path.join(sockets, "X91"), "w").close()
            open(os.path.join(locks, ".X92-lock"), "w").close()
            open(os.path.join(locks, "unrelated"), "w").close()
            self.assertEqual(snap.taken_displays(sockets, locks), {91, 92})

    def test_find_xvfb_prefers_env(self):
        which = mock.Mock(return_value="/usr/bin/Xvfb")
        self.assertEqual(
            snap.find_xvfb({"LIGHTSTREAM_XVFB": "/opt/Xvfb"}, which), "/opt/Xvfb")
        self.assertEqual(snap.find_xvfb({}, which), "/usr/bin/Xvfb")


class MissingDependencyTests(unittest.TestCase):
    def run_main(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = snap.main(argv)
        return code, err.getvalue()

    def test_missing_pillow(self):
        with mock.patch.dict(sys.modules, {"PIL": None, "PIL.ImageGrab": None}):
            code, text = self.run_main(["gui", "--out", tempfile.gettempdir()])
        self.assertNotEqual(code, 0)
        self.assertIn("pip install pillow", text)
        self.assertNotIn("Traceback", text)

    def test_missing_playwright(self):
        with mock.patch.dict(sys.modules, {"playwright": None}):
            code, text = self.run_main(["web", "--out", tempfile.gettempdir()])
        self.assertNotEqual(code, 0)
        self.assertIn("pip install playwright", text)
        self.assertNotIn("Traceback", text)

    def test_missing_xvfb(self):
        fake_grab = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"PIL": mock.MagicMock(),
                                           "PIL.ImageGrab": fake_grab}), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(snap, "find_xvfb", return_value=None):
            os.environ.pop("DISPLAY", None)
            code, text = self.run_main(["gui", "--out", tempfile.gettempdir()])
        self.assertNotEqual(code, 0)
        self.assertIn("Xvfb not found", text)

    def test_bad_size_is_friendly(self):
        fake_grab = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"PIL": mock.MagicMock(),
                                           "PIL.ImageGrab": fake_grab}):
            code, text = self.run_main(
                ["gui", "--out", tempfile.gettempdir(), "--size", "big"])
        self.assertEqual(code, 1)
        self.assertIn("size must look like", text)


if __name__ == "__main__":
    unittest.main()
