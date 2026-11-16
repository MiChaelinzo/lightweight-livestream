"""Build a portable zip: python tools/build_portable.py [output.zip]

The zip holds the source, launchers and an empty ffmpeg/ folder. Settings are
kept in data/ next to the app (portable.flag turns that on). No binaries are
added; drop a copy of ffmpeg(.exe) into the ffmpeg/ folder yourself.
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "lightstream-portable"
FFMPEG_NOTE = ("Put ffmpeg.exe (Windows) or ffmpeg (Linux/macOS) in this folder.\n"
               "Lightstream uses it before any ffmpeg installed on the PC.\n")


def collect_files(root=ROOT):
    """(disk path, archive path) pairs; skips caches and anything compiled."""
    pairs = []
    for folder in ("src", "launchers"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, folder)):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if name.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(dirpath, name)
                pairs.append((full, os.path.relpath(full, root)))
    for name in ("README.md", "LICENSE", "CHANGELOG.md"):
        if os.path.exists(os.path.join(root, name)):
            pairs.append((os.path.join(root, name), name))
    return pairs


def build(output, root=ROOT):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for disk, arc in collect_files(root):
            info = zipfile.ZipInfo.from_file(disk, "%s/%s" % (TOP, arc.replace(os.sep, "/")))
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(disk, "rb") as fh:
                zf.writestr(info, fh.read())
        zf.writestr("%s/portable.flag" % TOP, "Settings are stored in ./data\n")
        zf.writestr("%s/ffmpeg/PUT-FFMPEG-HERE.txt" % TOP, FFMPEG_NOTE)
    return output


if __name__ == "__main__":
    print("Wrote " + build(sys.argv[1] if len(sys.argv) > 1 else "lightstream-portable.zip"))
