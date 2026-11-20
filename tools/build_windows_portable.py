"""Build the Windows portable folder: python tools/build_windows_portable.py [--layout-only] [--output DIR]

Creates LightStreamPortable/ with LightStream.exe, portable.flag, ffmpeg/, scenes/,
recordings/ and config/. The exe is built with PyInstaller, which must already be
installed (pip install pyinstaller) and must run on Windows to produce a Windows exe.
FFmpeg is never bundled: ffmpeg/ gets a note telling the user to add their own copy.
--layout-only (alias --dry-run) creates the folders and text files without the exe.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = "LightStreamPortable"
EXE_NAME = "LightStream.exe"
SUBFOLDERS = ("ffmpeg", "scenes", "recordings", "config")
FLAG_TEXT = "Settings are stored in ./data next to LightStream.exe\n"
FFMPEG_NOTE = ("LightStream does not include FFmpeg.\n"
               "Download ffmpeg.exe yourself (https://ffmpeg.org/download.html) and put it in this folder.\n"
               "LightStream uses it before any ffmpeg installed on the PC.\n")
ENTRY_SOURCE = "from lightstream.gui import main\nmain()\n"


class BuildError(Exception):
    pass


def create_layout(output):
    """Create the folder structure and text files. Returns the list of relative paths written."""
    written = []
    os.makedirs(output, exist_ok=True)
    for name in SUBFOLDERS:
        os.makedirs(os.path.join(output, name), exist_ok=True)
        written.append(name + "/")
    with open(os.path.join(output, "portable.flag"), "w", encoding="utf-8") as fh:
        fh.write(FLAG_TEXT)
    written.append("portable.flag")
    note = os.path.join("ffmpeg", "PUT-FFMPEG-HERE.txt")
    with open(os.path.join(output, note), "w", encoding="utf-8") as fh:
        fh.write(FFMPEG_NOTE)
    written.append(note.replace(os.sep, "/"))
    return written


def pyinstaller_command(entry, dist_dir, work_dir, python=sys.executable):
    return [python, "-m", "PyInstaller", "--onefile", "--windowed", "--name", "LightStream",
            "--paths", os.path.join(ROOT, "src"), "--distpath", dist_dir,
            "--workpath", work_dir, "--specpath", work_dir, entry]


def build_exe(output, run=subprocess.run, find_module=None):
    """Run PyInstaller and copy LightStream.exe into output. Raises BuildError with a clear message."""
    if find_module is None:
        import importlib.util
        find_module = importlib.util.find_spec
    if find_module("PyInstaller") is None:
        raise BuildError("PyInstaller is not installed. Run: pip install pyinstaller "
                         "(use --layout-only to build just the folder structure).")
    with tempfile.TemporaryDirectory() as tmp:
        entry = os.path.join(tmp, "lightstream_entry.py")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(ENTRY_SOURCE)
        dist_dir = os.path.join(tmp, "dist")
        result = run(pyinstaller_command(entry, dist_dir, os.path.join(tmp, "work")))
        if result.returncode != 0:
            raise BuildError("PyInstaller failed with exit code %d." % result.returncode)
        built = os.path.join(dist_dir, EXE_NAME)
        if not os.path.isfile(built):
            raise BuildError("PyInstaller finished but %s was not produced. "
                             "A Windows exe must be built on Windows." % EXE_NAME)
        shutil.copy2(built, os.path.join(output, EXE_NAME))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the LightStream Windows portable folder.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="folder to create (default: %(default)s)")
    parser.add_argument("--layout-only", "--dry-run", dest="layout_only", action="store_true",
                        help="create the folder structure only, without building the exe")
    args = parser.parse_args(argv)
    written = create_layout(args.output)
    print("Created %s with: %s" % (args.output, ", ".join(written)))
    if args.layout_only:
        print("Layout only: %s was not built." % EXE_NAME)
        return 0
    try:
        build_exe(args.output)
    except BuildError as err:
        print("error: " + str(err), file=sys.stderr)
        return 1
    print("Built " + os.path.join(args.output, EXE_NAME))
    return 0


if __name__ == "__main__":
    sys.exit(main())
