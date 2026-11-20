"""Portable mode: keep settings next to the app and find a bundled FFmpeg.

Portable mode is on when the environment variable LIGHTSTREAM_PORTABLE=1 is set,
or when a file named portable.flag exists in the app folder. Then settings go
to <app folder>/data instead of the per-user config location, so the whole
folder can live on a USB stick and be deleted without leaving traces.
"""

import os
import shutil
import sys

FLAG_FILE = "portable.flag"
DATA_DIRNAME = "data"
ENV_VAR = "LIGHTSTREAM_PORTABLE"


def app_root():
    """Folder that holds the app: the exe, the .pyz, or the source checkout."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.abspath(__file__)
    parts = here.split(os.sep)
    for i, part in enumerate(parts):  # inside a zipapp: use the .pyz's folder
        if part.endswith(".pyz"):
            return os.sep.join(parts[:i]) or os.sep
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def is_portable(root=None, environ=None):
    environ = os.environ if environ is None else environ
    if environ.get(ENV_VAR, "").strip() not in ("", "0"):
        return True
    return os.path.exists(os.path.join(root or app_root(), FLAG_FILE))


def data_dir(root=None):
    return os.path.join(root or app_root(), DATA_DIRNAME)


def _ffmpeg_candidates(root):
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return [os.path.join(root, exe),
            os.path.join(root, "ffmpeg", exe),
            os.path.join(root, "ffmpeg", "bin", exe),
            os.path.join(root, "bin", exe)]


def find_ffmpeg(root=None, which=None):
    """A copy bundled next to the app wins over the one on PATH."""
    for path in _ffmpeg_candidates(root or app_root()):
        if os.path.isfile(path):
            return path
    return (which or shutil.which)("ffmpeg")
