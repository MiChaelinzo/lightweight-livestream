"""Portable mode: keep settings next to the app and find a bundled FFmpeg.

Portable mode is on when the environment variable LIGHTSTREAM_PORTABLE=1 is set,
or when a file named portable.flag exists in the app folder. Then settings go
to <app folder>/data, scene collections to <app folder>/scenes and
default recordings to <app folder>/recordings instead of the per-user config location, so the whole
folder can live on a USB stick and be deleted without leaving traces.
"""

import json
import os
import shutil
import subprocess
import sys

FLAG_FILE = "portable.flag"
DATA_DIRNAME = "data"
SCENES_DIRNAME = "scenes"
RECORDINGS_DIRNAME = "recordings"
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


def scenes_dir(root=None):
    """Portable scene collections folder (the shareable one-scene files)."""
    return os.path.join(root or app_root(), SCENES_DIRNAME)


def recordings_dir(root=None):
    """Portable default folder for local recordings."""
    return os.path.join(root or app_root(), RECORDINGS_DIRNAME)


def _ffmpeg_candidates(root):
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return [os.path.join(root, exe),
            os.path.join(root, "ffmpeg", exe),
            os.path.join(root, "ffmpeg", "bin", exe),
            os.path.join(root, "bin", exe)]


CONFIG_KEY = "ffmpeg_path"
FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html"
WINDOWS_BUILDS_URL = "https://www.gyan.dev/ffmpeg/builds/"
VALIDATE_TIMEOUT_SECONDS = 10


def configured_ffmpeg(config_file=None):
    """The ffmpeg path the user chose in the first-run helper, or None.

    Reads "ffmpeg_path" from config.json. A missing or unreadable file means None.
    """
    from .config import config_path
    path = config_file or config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh).get(CONFIG_KEY)
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and os.path.isfile(value) else None


def save_configured_ffmpeg(ffmpeg_path, config_file=None):
    """Store the chosen ffmpeg in config.json, keeping every other setting."""
    from .config import config_path
    path = config_file or config_path()
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("Config file %s must contain a JSON object" % path)
    data[CONFIG_KEY] = ffmpeg_path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def validate_ffmpeg(path, run=subprocess.run):
    """Return (ok, message). ok is True when path is a file that answers -version."""
    if not path or not os.path.isfile(path):
        return False, "That file does not exist."
    try:
        result = run([path, "-version"], capture_output=True, text=True,
                     timeout=VALIDATE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as err:
        return False, "That file could not be run: %s" % err
    first_line = (result.stdout or "").strip().splitlines()[:1]
    if result.returncode != 0 or not first_line or "ffmpeg" not in first_line[0].lower():
        return False, "That file did not answer like FFmpeg (-version failed)."
    return True, first_line[0]


def ffmpeg_guidance(platform_name=None):
    """Plain-words help for getting FFmpeg, chosen by sys.platform."""
    name = platform_name or sys.platform
    lines = ["LightStream needs FFmpeg to stream, and could not find it.", ""]
    if name.startswith("win"):
        lines += ["1. Download a Windows build from " + WINDOWS_BUILDS_URL,
                  "2. Unzip it and pick bin\\ffmpeg.exe with 'Choose ffmpeg file...',",
                  "   or copy ffmpeg.exe next to LightStream.exe."]
    elif name == "darwin":
        lines += ["Install it with Homebrew: brew install ffmpeg",
                  "Then restart LightStream, or pick the file with 'Choose ffmpeg file...'."]
    else:
        lines += ["Install it with your package manager, for example:",
                  "  sudo apt install ffmpeg   (Debian, Ubuntu)",
                  "  sudo dnf install ffmpeg   (Fedora)",
                  "Then restart LightStream, or pick the file with 'Choose ffmpeg file...'."]
    lines += ["", "Official downloads: " + FFMPEG_DOWNLOAD_URL]
    return "\n".join(lines)


def ffmpeg_download_url(platform_name=None):
    name = platform_name or sys.platform
    return WINDOWS_BUILDS_URL if name.startswith("win") else FFMPEG_DOWNLOAD_URL


def find_ffmpeg(root=None, which=None, configured=None):
    """Order: copy next to the app, then the user's chosen file, then PATH.

    The chosen file is read from config.json only for real app calls (no root);
    pass configured to override it.
    """
    for path in _ffmpeg_candidates(root or app_root()):
        if os.path.isfile(path):
            return path
    if configured is None and root is None:
        configured = configured_ffmpeg()
    if configured and os.path.isfile(configured):
        return configured
    return (which or shutil.which)("ffmpeg")
