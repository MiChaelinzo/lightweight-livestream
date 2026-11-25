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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
        self.assertEqual(snap.gui_filename("dark", "dashboard", 1280, 720, state="live"),
                         "gui-dark-dashboard-live-1280x720.png")
        self.assertEqual(snap.web_filename(390), "web-390.png")


class StateTests(unittest.TestCase):
    def test_parser_accepts_each_state_and_rejects_others(self):
        parser = snap.build_parser()
        for state in ("offline", "live", "reconnecting", "error"):
            args = parser.parse_args(["gui", "--out", "x", "--state", state])
            self.assertEqual(state, args.state)
        self.assertIsNone(parser.parse_args(["gui", "--out", "x"]).state)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["gui", "--out", "x", "--state", "burning"])

    def test_every_state_maps_to_a_real_banner(self):
        from lightstream import gui_controller as gc
        from lightstream import gui_theme
        for state in snap.BANNER_STATES:
            text, color, help_text, log, running = snap.fake_snapshot(state, gc)()
            self.assertTrue(text)
            gui_theme.banner_colors("light", color)  # raises on an unknown color
            self.assertEqual(state in ("live", "reconnecting"), running)
            self.assertEqual("", log)
        self.assertEqual(gc.HELP_TEXT["failed"],
                         snap.fake_snapshot("error", gc)()[2])
        with self.assertRaises(ValueError):
            snap.fake_snapshot("burning", gc)


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


class StateRenderTests(unittest.TestCase):
    """Need a display, Pillow and tkinter; skipped otherwise."""

    def test_banner_state_is_painted(self):
        if not os.environ.get("DISPLAY"):
            self.skipTest("no DISPLAY")
        import tkinter
        try:
            root = tkinter.Tk()
        except tkinter.TclError:
            self.skipTest("Tk cannot open the display")
        self.addCleanup(root.destroy)
        from lightstream import gui, gui_controller as gc, gui_theme
        home = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": home}):
            window = gui.StreamWindow(root)
        for state in snap.BANNER_STATES:
            window.controller.snapshot = snap.fake_snapshot(state, gc)
            window.poll()
            text, color = getattr(gc, snap.BANNER_STATES[state])
            self.assertEqual(text, window.banner.cget("text"))
            self.assertEqual(gui_theme.banner_colors(window.theme, color)[0],
                             window.banner.cget("bg"))


class WebImageLoadingTests(unittest.TestCase):
    def test_images_are_loaded_before_each_screenshot(self):
        calls = []
        page = mock.MagicMock()
        page.evaluate.side_effect = lambda js: calls.append(("evaluate", js)) or []
        page.screenshot.side_effect = lambda **kw: calls.append(("screenshot", None))
        browser = mock.MagicMock()
        browser.new_page.return_value = page
        playwright = mock.MagicMock()
        playwright.chromium.launch.return_value = browser
        sync_api = mock.MagicMock()
        sync_api.sync_playwright.return_value.__enter__.return_value = playwright
        args = mock.MagicMock(widths="1280", color_scheme="dark")
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(snap, "_require", return_value=sync_api):
            args.out = out
            with contextlib.redirect_stdout(io.StringIO()):
                snap.run_web(args)
        self.assertEqual([("evaluate", snap.LOAD_IMAGES_JS), ("screenshot", None)], calls)

    def test_broken_image_is_reported(self):
        page = mock.MagicMock()
        page.evaluate.return_value = ["http://x/img/missing.webp"]
        browser = mock.MagicMock()
        browser.new_page.return_value = page
        playwright = mock.MagicMock()
        playwright.chromium.launch.return_value = browser
        sync_api = mock.MagicMock()
        sync_api.sync_playwright.return_value.__enter__.return_value = playwright
        args = mock.MagicMock(widths="1280", color_scheme="dark")
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(snap, "_require", return_value=sync_api):
            args.out = out
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(RuntimeError):
                    snap.run_web(args)
        self.assertIn("missing.webp", err.getvalue())

    def test_script_makes_images_eager_and_waits(self):
        self.assertIn("loading = 'eager'", snap.LOAD_IMAGES_JS)
        self.assertIn("img.complete", snap.LOAD_IMAGES_JS)


if __name__ == "__main__":
    unittest.main()
