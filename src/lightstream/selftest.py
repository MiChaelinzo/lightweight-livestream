"""Headless integrity checks for source and frozen LightStream applications.

The self-test never opens a window or starts a stream. Missing FFmpeg is a
warning because LightStream deliberately does not bundle it; import, Tcl,
path, or writable-state failures are application integrity failures.
"""

import importlib
import json
import os
import sys
import tempfile

from . import __version__
from .config import config_path, detect_os
from .portable import (app_root, ffmpeg_guidance, find_ffmpeg, is_portable,
                       validate_ffmpeg)

REQUIRED_IMPORTS = (
    "lightstream.cli",
    "lightstream.command",
    "lightstream.config",
    "lightstream.gui_controller",
    "lightstream.gui_pages",
    "lightstream.gui_theme",
    "lightstream.portable",
    "lightstream.remote",
)


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": str(detail)}


def _inside(path, root):
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) \
            == os.path.realpath(root)
    except ValueError:  # different drives on Windows
        return False


def _probe_writable(directory):
    """Create and remove one private probe file in *directory*."""
    os.makedirs(directory, exist_ok=True)
    descriptor, path = tempfile.mkstemp(prefix=".lightstream-self-test-", dir=directory)
    try:
        os.write(descriptor, b"LightStream self-test\n")
    finally:
        os.close(descriptor)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def collect_report(root=None, environ=None, platform_name=None, importer=None,
                   writable_probe=None, ffmpeg_finder=None,
                   ffmpeg_validator=None, tcl_factory=None, frozen=None):
    """Return a JSON-serializable self-test report.

    Dependencies are injectable so the failure and warning paths are covered
    without requiring a display, a frozen binary, or FFmpeg in unit tests.
    """
    environ = os.environ if environ is None else environ
    importer = importer or importlib.import_module
    writable_probe = writable_probe or _probe_writable
    ffmpeg_finder = ffmpeg_finder or find_ffmpeg
    ffmpeg_validator = ffmpeg_validator or validate_ffmpeg
    root = os.path.abspath(root or app_root())
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    checks = []

    failed_imports = []
    for module_name in REQUIRED_IMPORTS:
        try:
            importer(module_name)
        except Exception as exc:  # report every broken frozen import together
            failed_imports.append("%s (%s: %s)" %
                                  (module_name, type(exc).__name__, exc))
    if failed_imports:
        checks.append(_check("imports", "fail", "; ".join(failed_imports)))
    else:
        checks.append(_check("imports", "pass",
                             "%d required modules imported" % len(REQUIRED_IMPORTS)))

    try:
        tkinter = importer("tkinter")
        interpreter = (tcl_factory or tkinter.Tcl)()
        patchlevel = str(interpreter.call("info", "patchlevel"))
        tk_version = str(getattr(tkinter, "TkVersion", "unknown"))
        checks.append(_check("tk_tcl", "pass",
                             "Tcl %s; Tk API %s; no display opened" %
                             (patchlevel, tk_version)))
    except Exception as exc:
        checks.append(_check("tk_tcl", "fail", "%s: %s" %
                             (type(exc).__name__, exc)))

    if os.path.isabs(root) and os.path.isdir(root):
        checks.append(_check("app_root", "pass", root))
    else:
        checks.append(_check("app_root", "fail",
                             "application root is not an existing absolute directory: " + root))

    portable_mode = is_portable(root=root, environ=environ)
    try:
        state_file = config_path(detect_os(platform_name), environ=environ, root=root)
        state_dir = os.path.dirname(state_file)
        if portable_mode and not _inside(state_file, root):
            raise OSError("portable state escaped the application root")
        writable_probe(state_dir)
        checks.append(_check("writable_state", "pass", state_dir))
    except Exception as exc:
        state_file = None
        checks.append(_check("writable_state", "fail", "%s: %s" %
                             (type(exc).__name__, exc)))

    try:
        ffmpeg = ffmpeg_finder()
        if not ffmpeg:
            checks.append(_check("ffmpeg", "warn",
                                 ffmpeg_guidance(platform_name).splitlines()[0]))
        else:
            valid, detail = ffmpeg_validator(ffmpeg)
            checks.append(_check("ffmpeg", "pass" if valid else "warn",
                                 "%s: %s" % (ffmpeg, detail)))
    except Exception as exc:
        checks.append(_check("ffmpeg", "fail",
                             "FFmpeg discovery failed (%s: %s)" %
                             (type(exc).__name__, exc)))

    ok = not any(item["status"] == "fail" for item in checks)
    return {
        "app": "LightStream",
        "version": __version__,
        "ok": ok,
        "frozen": frozen,
        "platform": detect_os(platform_name),
        "portable": portable_mode,
        "app_root": root,
        "state_path": state_file,
        "checks": checks,
    }


def format_plain(report):
    lines = ["LightStream %s self-test" % report["version"]]
    for item in report["checks"]:
        lines.append("%-4s %-16s %s" %
                     (item["status"].upper(), item["name"] + ":", item["detail"]))
    warnings = sum(item["status"] == "warn" for item in report["checks"])
    lines.append("Result: %s%s" %
                 ("PASS" if report["ok"] else "FAIL",
                  " (%d warning%s)" % (warnings, "" if warnings == 1 else "s")
                  if warnings else ""))
    return "\n".join(lines) + "\n"


def main(json_output=False, out=None, **kwargs):
    """Run the self-test and return 0 unless an integrity check failed."""
    out = out or sys.stdout
    report = collect_report(**kwargs)
    if json_output:
        out.write(json.dumps(report, sort_keys=True) + "\n")
    else:
        out.write(format_plain(report))
    return 0 if report["ok"] else 1
