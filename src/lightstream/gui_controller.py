"""Logic behind the beginner GUI. No tkinter here, so it is testable headlessly.

The stream key lives only in memory: it is never written to the preferences
file and it is redacted from the log shown on screen.
"""

import collections
import json
import os
import shutil
import threading

from .command import build_command
from .config import config_path, detect_os, resolve_settings
from .encoders import choose_working_encoder, probe_encoders
from .presets import DEFAULT_PRESET, PRESETS
from .runner import (STATUS_FALLBACK, STATUS_FAILED, STATUS_LIVE,
                     STATUS_RECONNECTING, STATUS_STARTING, STATUS_STOPPED,
                     is_lagging, redact, run_with_reconnect)

MAX_QUICK_FAILURES = 5
TEST_FILENAME = "lightstream-test.mkv"
LOG_LINES = 200
STOP_JOIN_SECONDS = 10
MIN_SUBSTRING_KEY_LENGTH = 8
PREFS_FILENAME = "gui.json"
PREF_FIELDS = ("platform", "url", "preset", "fps", "bitrate", "window",
               "audio_device", "keep_trying", "mute")

# (label shown to the user, value used internally)
PLATFORM_CHOICES = (("Twitch", "twitch"), ("YouTube", "youtube"),
                    ("Other site", "custom"))
STRENGTH_CHOICES = (
    ("Very old PC (potato)", "potato"),
    ("Old PC (light)", "light"),
    ("Normal PC (balanced)", "balanced"),
    ("Strong PC (720p60)", "720p60"),
)

# Banner states: (text, color name), plain words for beginners.
BANNER_OFFLINE = ("Offline. Press START when you are ready.", "grey")
BANNER_STARTING = ("Starting... please wait.", "orange")
BANNER_LIVE = ("YOU ARE LIVE!", "green")
BANNER_LAGGING = ("LIVE, but your PC is struggling. Try a weaker setting.",
                  "orange")
BANNER_RECONNECTING = ("Connection lost. Trying again...", "orange")
BANNER_PROBLEM = ("Problem. Could not stream. See 'What is wrong?'", "red")

HELP_TEXT = {
    "no_key": "Step 2 is empty. Copy your stream key from your streaming "
              "website and paste it in the box.",
    "no_url": "You picked 'Other site'. Type the address it gave you, "
              "starting with rtmp://",
    "no_ffmpeg": "FFmpeg is missing. It is the free program that sends your "
                 "screen. Install it, then press 'Check my PC'.",
    "failed": "The stream stopped again and again. Check that your key is "
              "right and your internet works. Try 'Normal' or a weaker PC "
              "setting.",
}


def suggest_strength(cpu_count):
    """Preset name for a PC with this many CPU threads (None means unknown)."""
    if not cpu_count or cpu_count <= 2:
        return "potato"
    if cpu_count <= 4:
        return DEFAULT_PRESET
    if cpu_count <= 8:
        return "balanced"
    return "720p60"


def label_for(choices, value):
    for label, val in choices:
        if val == value:
            return label
    return choices[0][0]


def value_for(choices, label):
    for lab, val in choices:
        if lab == label:
            return val
    return choices[0][1]


def banner_for(state, detail=None):
    """(text, color) for a runner status."""
    if state == STATUS_STARTING or state == STATUS_FALLBACK:
        return BANNER_STARTING
    if state == STATUS_LIVE:
        return BANNER_LAGGING if is_lagging(detail or {}) else BANNER_LIVE
    if state == STATUS_RECONNECTING:
        return BANNER_RECONNECTING
    if state == STATUS_FAILED:
        return BANNER_PROBLEM
    return BANNER_OFFLINE


def prefs_path(os_name=None):
    return os.path.join(os.path.dirname(config_path(os_name)), PREFS_FILENAME)


def _contains_key(value, key):
    """Short keys could match innocent text ("1" in "30"), so below
    MIN_SUBSTRING_KEY_LENGTH only a whole-value match counts."""
    if not key:
        return False
    text = str(value)
    if len(key) < MIN_SUBSTRING_KEY_LENGTH:
        return text == key
    return key in text


def save_prefs(path, prefs, key=""):
    """Write only whitelisted fields, and never any value containing the key.

    The key check covers a user pasting a full rtmp://.../KEY address into the
    "Other site" box.
    """
    safe = {k: prefs[k] for k in PREF_FIELDS if k in prefs
            and not _contains_key(prefs[k], key)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(safe, fh, indent=2)
        fh.write("\n")


def load_prefs(path):
    """Saved choices, or {} when missing or unreadable (never crash the GUI)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in PREF_FIELDS if k in data}


def validate(prefs, key, ffmpeg, test_local=False):
    """Friendly error text for the first problem found, else None."""
    if not test_local and not (key or "").strip():
        return HELP_TEXT["no_key"]
    if prefs.get("platform") == "custom" and not (prefs.get("url") or "").strip():
        return HELP_TEXT["no_url"]
    if not ffmpeg:
        return HELP_TEXT["no_ffmpeg"]
    return None


def _blank_to_none(value):
    value = (value or "").strip() if isinstance(value, str) else value
    return value or None


def settings_from_prefs(prefs, display=None):
    """StreamSettings from GUI fields. Raises ValueError with plain words."""
    try:
        return resolve_settings({
            "platform": prefs.get("platform"),
            "url": _blank_to_none(prefs.get("url")),
            "preset": prefs.get("preset"),
            "fps": _blank_to_none(prefs.get("fps")),
            "bitrate": _blank_to_none(prefs.get("bitrate")),
            "window": _blank_to_none(prefs.get("window")),
            "audio_device": _blank_to_none(prefs.get("audio_device")),
            "mute": bool(prefs.get("mute")) or None,
            "display": display,
        }, {})
    except ValueError as exc:
        raise ValueError("One of your numbers looks wrong (%s). Leave "
                         "Advanced boxes empty if unsure." % exc)


class StreamController:
    """Runs one stream in a background thread and exposes status to the GUI.

    The GUI only calls start/stop and reads snapshot() from its timer, so no
    tkinter object is ever touched from the worker thread.
    """

    def __init__(self, runner=run_with_reconnect, which=shutil.which,
                 os_name=None, display=None, probe=probe_encoders,
                 pick_encoder=choose_working_encoder):
        self._runner = runner
        self._which = which
        self._os_name = os_name or detect_os()
        self._display = display
        self._probe = probe
        self._pick_encoder = pick_encoder
        self._lock = threading.Lock()
        self._log = collections.deque(maxlen=LOG_LINES)
        self._banner = BANNER_OFFLINE
        self._help = ""
        self._thread = None
        self._stop = None
        self._key = ""

    # -- state for the GUI -------------------------------------------------
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self):
        """(banner_text, color, help_text, log_text, running)."""
        with self._lock:
            text, color = self._banner
            return (text, color, self._help, "".join(self._log),
                    self.is_running())

    # -- worker callbacks (called from the worker thread) -------------------
    def _write(self, text):
        with self._lock:
            self._log.append(redact(text, self._key))

    def _on_status(self, state, detail):
        with self._lock:
            self._banner = banner_for(state, detail)
            if state == STATUS_FAILED:
                self._help = HELP_TEXT["failed"]
            elif state == STATUS_LIVE:
                self._help = ""

    class _LogSink:
        def __init__(self, write):
            self.write = write

    # -- actions ------------------------------------------------------------
    def start(self, prefs, key, test_local=False):
        """Begin streaming, or with test_local record a short file instead
        (no key needed, nothing goes live). Returns None or an error message."""
        if self.is_running():
            return "You are already streaming."
        ffmpeg = self._which("ffmpeg")
        problem = validate(prefs, key, ffmpeg, test_local)
        if problem:
            with self._lock:
                self._help = problem
            return problem
        try:
            settings = settings_from_prefs(prefs, self._display)
        except ValueError as exc:
            with self._lock:
                self._help = str(exc)
            return str(exc)
        key = key.strip() or "test"
        self._key = key
        with self._lock:
            self._help = ""
            self._banner = BANNER_STARTING
            self._log.clear()
        self._stop = threading.Event()
        keep_trying = bool(prefs.get("keep_trying"))
        self._thread = threading.Thread(
            target=self._work, args=(settings, key, ffmpeg, keep_trying,
                  TEST_FILENAME if test_local else None),
            daemon=True)
        self._thread.start()
        return None

    def _work(self, settings, key, ffmpeg, keep_trying, record_path=None):
        try:
            try:
                available = self._probe(ffmpeg)
            except RuntimeError as exc:
                self._write("Warning: %s. Using libx264.\n" % exc)
                available = set()
            encoder = self._pick_encoder(ffmpeg, available)
            self._write("Encoder: %s\n" % encoder)
            argv = build_command(settings, key, self._os_name, encoder, ffmpeg,
                                 record_path)
            self._runner(
                argv, key, self._os_name,
                max_failures=(1 if record_path else
                              None if keep_trying else MAX_QUICK_FAILURES),
                stop=self._stop, on_status=self._on_status, encoder=encoder,
                out=self._LogSink(self._write),
                argv_factory=lambda enc: build_command(
                    settings, key, self._os_name, enc, ffmpeg, record_path))
        except (OSError, ValueError) as exc:
            self._write("Could not start: %s\n" % exc)
            self._on_status(STATUS_FAILED, None)
        finally:
            self._key = ""

    def stop(self, wait=True):
        """Stop the stream. wait=False returns at once (for the GUI thread);
        the status poll then sees running turn False."""
        if self._stop is not None:
            self._stop.set()
        thread = self._thread
        if not wait:
            return
        if thread is not None:
            thread.join(STOP_JOIN_SECONDS)
        if not self.is_running():
            self._on_status(STATUS_STOPPED, None)
