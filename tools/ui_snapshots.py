#!/usr/bin/env python3
"""Dev-only UI snapshots: render the Tk GUI and the web page to PNG files.

Never imported by the runtime. Needs OPTIONAL dev dependencies:
  gui: Xvfb (or an existing DISPLAY) and Pillow
  web: playwright with a Chromium build (`playwright install chromium`)

Capture choice (gui): the whole virtual screen is grabbed at --size, so a
window taller than the screen shows up as visibly clipped, exactly as it
would for a user on a screen of that size. The window keeps the size Tk
requests; it is not resized to fit.

Screenshots are Linux renders: fonts differ from Windows (no Segoe UI).

  python3 tools/ui_snapshots.py gui --out DIR [--size 1366x768] [--theme dark]
                                    [--state offline|live|reconnecting|error]
  python3 tools/ui_snapshots.py web --out DIR [--widths 1280,390]
"""

import argparse
import functools
import http.server
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SIZE = (1366, 768)
DEFAULT_WIDTHS = (1280, 390)
WEB_VIEWPORT_HEIGHT = 900
FIRST_DISPLAY = 90
LAST_DISPLAY = 199
THEMES = ("light", "dark")
# --state drives the banner through a fake controller snapshot, so no ffmpeg
# runs. Maps the option to the gui_controller banner constant and a help line.
BANNER_STATES = {"offline": "BANNER_OFFLINE", "live": "BANNER_LIVE",
                 "reconnecting": "BANNER_RECONNECTING", "error": "BANNER_PROBLEM"}
# Lazy <img> elements outside the viewport never load in a full-page capture
# (they show as empty boxes). Make them eager, then wait until every image has
# finished (or failed) so the screenshot shows the real pictures.
LOAD_IMAGES_JS = """async () => {
  const images = Array.from(document.images);
  images.forEach(img => { img.loading = 'eager'; });
  await Promise.all(images.map(img => img.complete ? null : new Promise(done => {
    img.addEventListener('load', done, {once: true});
    img.addEventListener('error', done, {once: true});
  })));
  return images.filter(img => !img.naturalWidth).map(img => img.src);
}"""
IMAGE_LOAD_TIMEOUT_MS = 10000
INSTALL_HINTS = {
    "PIL": "Pillow is missing: pip install pillow",
    "playwright": ("playwright is missing: pip install playwright && "
                   "playwright install chromium"),
    "xvfb": ("Xvfb not found: install it, set LIGHTSTREAM_XVFB to its path, "
             "or run with DISPLAY set"),
}


class MissingDependency(Exception):
    """A dev-only dependency is absent; the message is the install hint."""


def parse_size(text):
    """'1366x768' -> (1366, 768). ValueError on anything else."""
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise ValueError("size must look like 1366x768, got %r" % text)
    if width < 200 or height < 200:
        raise ValueError("size is too small: %r" % text)
    return width, height


def parse_widths(text):
    widths = []
    for part in text.split(","):
        try:
            width = int(part)
        except ValueError:
            raise ValueError("widths must be comma separated integers, got %r" % text)
        if width < 200:
            raise ValueError("width is too small: %d" % width)
        widths.append(width)
    if not widths:
        raise ValueError("no widths given")
    return widths


def resolve_pages(spec, known):
    """'all' or 'a,b' -> list of known page ids in the order requested."""
    if spec == "all":
        return list(known)
    pages = [part.strip() for part in spec.split(",") if part.strip()]
    unknown = [page for page in pages if page not in known]
    if unknown or not pages:
        raise ValueError("unknown pages %s; known: %s"
                         % (", ".join(unknown) or "(none)", ", ".join(known)))
    return pages


def pick_display(taken):
    """Lowest display number in the dev range that is not in `taken`."""
    for number in range(FIRST_DISPLAY, LAST_DISPLAY + 1):
        if number not in taken:
            return number
    raise RuntimeError("no free X display between :%d and :%d"
                       % (FIRST_DISPLAY, LAST_DISPLAY))


def taken_displays(socket_dir="/tmp/.X11-unix", lock_dir="/tmp"):
    taken = set()
    for directory, prefix in ((socket_dir, "X"), (lock_dir, ".X")):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.startswith(prefix):
                digits = name[len(prefix):].split("-")[0]
                if digits.isdigit():
                    taken.add(int(digits))
    return taken


def gui_filename(theme, page, width, height, compact=False, state=None):
    return "gui-%s%s-%s%s-%dx%d.png" % (
        theme, "-compact" if compact else "", page,
        "-" + state if state else "", width, height)


def fake_snapshot(state, controller_module):
    """A StreamController.snapshot() replacement showing `state` (a key of
    BANNER_STATES). Returns (banner_text, color, help_text, log_text, running)."""
    if state not in BANNER_STATES:
        raise ValueError("unknown state %r; known: %s"
                         % (state, ", ".join(BANNER_STATES)))
    text, color = getattr(controller_module, BANNER_STATES[state])
    help_text = controller_module.HELP_TEXT["failed"] if state == "error" else ""
    return lambda: (text, color, help_text, "", state in ("live", "reconnecting"))


def web_filename(width):
    return "web-%d.png" % width


def find_xvfb(environ=None, which=shutil.which):
    environ = os.environ if environ is None else environ
    return environ.get("LIGHTSTREAM_XVFB") or which("Xvfb")


def _require(module_name):
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise MissingDependency(INSTALL_HINTS[module_name.split(".")[0]])


def _load_gui_modules():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lightstream import gui, gui_pages
    return gui, gui_pages


def _start_xvfb(xvfb, size):
    number = pick_display(taken_displays())
    display = ":%d" % number
    proc = subprocess.Popen(
        [xvfb, display, "-screen", "0", "%dx%dx24" % size, "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    if proc.poll() is not None:
        raise RuntimeError("Xvfb exited immediately (display %s)" % display)
    return proc, display


def _settle(root, seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def run_gui(args):
    image_grab = _require("PIL.ImageGrab")
    size = parse_size(args.size)
    owns_display = not os.environ.get("DISPLAY")
    proc = None
    if owns_display:
        xvfb = find_xvfb()
        if not xvfb:
            raise MissingDependency(INSTALL_HINTS["xvfb"])
        proc, display = _start_xvfb(xvfb, size)
        os.environ["DISPLAY"] = display
    display = os.environ["DISPLAY"]
    home = tempfile.mkdtemp(prefix="ls-ui-snap-")
    os.environ["HOME"] = home
    os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    os.environ["APPDATA"] = home
    os.makedirs(args.out, exist_ok=True)
    written = []
    try:
        import tkinter
        gui, gui_pages = _load_gui_modules()
        pages = resolve_pages(args.pages, gui_pages.page_ids())
        root = tkinter.Tk()
        try:
            # StreamWindow only, not gui.main(): main() schedules the ffmpeg
            # help dialog, which must not appear in a capture.
            window = gui.StreamWindow(root)
            window.theme, window.compact = args.theme, args.compact
            window.apply_look()
            if args.state:
                from lightstream import gui_controller
                window.controller.snapshot = fake_snapshot(args.state, gui_controller)
            for page in pages:
                window.show_page(page)
                _settle(root)
                path = os.path.join(args.out, gui_filename(
                    args.theme, page, size[0], size[1], args.compact, args.state))
                image_grab.grab(
                    bbox=(0, 0, size[0], size[1]), xdisplay=display).save(path)
                written.append(path)
                print("saved %s (window %dx%d on a %dx%d screen)" % (
                    path, root.winfo_width(), root.winfo_height(), *size))
        finally:
            root.destroy()
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
        shutil.rmtree(home, ignore_errors=True)
    return written


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve_web(directory):
    handler = functools.partial(_QuietHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_web(args):
    sync_api = _require("playwright.sync_api")
    widths = parse_widths(args.widths)
    os.makedirs(args.out, exist_ok=True)
    server = serve_web(os.path.join(ROOT, "web"))
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    errors, written = [], []
    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
            for width in widths:
                page = browser.new_page(
                    viewport={"width": width, "height": WEB_VIEWPORT_HEIGHT},
                    color_scheme=args.color_scheme)
                page.on("console", lambda m, w=width: print(
                    "console[%d] %s: %s" % (w, m.type, m.text))
                    if m.type in ("error", "warning") else None)
                page.on("pageerror", lambda e, w=width: errors.append(
                    "pageerror[%d]: %s" % (w, e)))
                page.goto(url)
                page.wait_for_timeout(1500)
                broken = page.evaluate(LOAD_IMAGES_JS)
                for src in broken:
                    errors.append("image[%d] did not load: %s" % (width, src))
                path = os.path.join(args.out, web_filename(width))
                page.screenshot(path=path, full_page=True)
                written.append(path)
                print("saved", path)
                page.close()
            browser.close()
    finally:
        server.shutdown()
    for line in errors:
        print(line, file=sys.stderr)
    if errors:
        raise RuntimeError("%d page error(s)" % len(errors))
    return written


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gui = sub.add_parser("gui", help="render the Tk GUI pages")
    gui.add_argument("--out", required=True)
    gui.add_argument("--size", default="%dx%d" % DEFAULT_SIZE)
    gui.add_argument("--theme", choices=THEMES, default="light")
    gui.add_argument("--compact", action="store_true")
    gui.add_argument("--pages", default="all")
    gui.add_argument("--state", choices=tuple(BANNER_STATES),
                     help="show this banner state (fake controller, no ffmpeg)")
    web = sub.add_parser("web", help="screenshot the web/ site")
    web.add_argument("--out", required=True)
    web.add_argument("--widths", default=",".join(map(str, DEFAULT_WIDTHS)))
    web.add_argument("--color-scheme", choices=("light", "dark"), default="dark",
                     help="emulated prefers-color-scheme (default: dark)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        (run_gui if args.command == "gui" else run_web)(args)
    except MissingDependency as exc:
        print("ui_snapshots: %s" % exc, file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print("ui_snapshots: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
