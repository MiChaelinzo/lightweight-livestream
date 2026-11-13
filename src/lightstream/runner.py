"""Run ffmpeg at low priority, reconnect with backoff, never leak the key."""

import os
import re
import subprocess
import sys
import threading
import time

from .encoders import SOFTWARE_ENCODER

BACKOFF_CAP_SECONDS = 30
HEALTHY_RUN_SECONDS = 60
WINDOWS_BELOW_NORMAL = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
FALLBACK_AFTER_FAILURES = 2  # quick failures of a hardware encoder before libx264
LAGGING_BELOW_SPEED = 0.95   # ffmpeg speed under 1.0x means it cannot keep up
STOP_POLL_SECONDS = 0.2
# ffmpeg stderr words that point at the encoder itself, not the network or key
ENCODER_ERROR_HINTS = ("nvenc", "qsv", "amf", "vaapi", "videotoolbox", "cuda",
                       "encoder", "hwaccel", "libmfx", "device creation")

STATUS_STARTING = "starting"
STATUS_LIVE = "live"
STATUS_RECONNECTING = "reconnecting"
STATUS_FALLBACK = "fallback"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"

_PROGRESS_FIELDS = (
    ("fps", re.compile(r"fps=\s*([\d.]+)")),
    ("bitrate_kbps", re.compile(r"bitrate=\s*([\d.]+)\s*kbits/s")),
    ("speed", re.compile(r"speed=\s*([\d.]+)x")),
)


def redact(text, key):
    if key:
        text = text.replace(key, "****")
    return text


def format_command(argv, key):
    return " ".join(redact(a, key) if " " not in a else '"%s"' % redact(a, key)
                    for a in argv)


def backoff_delay(failures):
    """1, 2, 4, 8 ... capped seconds, for the Nth consecutive quick failure."""
    return min(2 ** max(failures - 1, 0), BACKOFF_CAP_SECONDS)


def priority_kwargs(os_name):
    """Popen kwargs that make ffmpeg yield to the game."""
    if os_name == "windows":
        return {"creationflags": WINDOWS_BELOW_NORMAL}
    return {"preexec_fn": lambda: os.nice(10)}


def parse_progress(line):
    """Numbers from an ffmpeg -stats line, e.g. {'fps': 30.0, 'speed': 1.0}.

    Returns {} when the line is not a progress line.
    """
    found = {}
    for name, pattern in _PROGRESS_FIELDS:
        match = pattern.search(line)
        if match:
            try:
                found[name] = float(match.group(1))
            except ValueError:
                continue
    return found if "fps" in found or "speed" in found else {}


def mentions_encoder_problem(line):
    """True when an ffmpeg error line looks like a hardware encoder failure."""
    lowered = line.lower()
    return any(hint in lowered for hint in ENCODER_ERROR_HINTS)


def is_lagging(health):
    """True when ffmpeg encodes slower than real time (viewers will buffer)."""
    return "speed" in health and health["speed"] < LAGGING_BELOW_SPEED


def _watch_for_stop(stop, proc, finished):
    """Terminate ffmpeg as soon as stop is set, even while it prints nothing."""
    while not finished.is_set():
        if stop.wait(STOP_POLL_SECONDS) and not finished.is_set():
            proc.terminate()
            return


def run_with_reconnect(argv, key, os_name, popen=subprocess.Popen,
                       sleep=None, clock=time.monotonic,
                       out=sys.stderr, max_failures=None, stop=None,
                       on_status=None, encoder=None, argv_factory=None):
    """Run ffmpeg until it exits cleanly, is stopped, or fails too often.

    max_failures=None keeps trying forever. stop is a threading.Event; setting
    it ends the stream and returns 0. on_status(state, detail) reports
    starting, live (detail is the health dict), reconnecting (detail is the
    delay), fallback (detail is the new encoder), stopped and failed.
    If a hardware encoder fails quickly FALLBACK_AFTER_FAILURES times in a
    row, with stderr naming the encoder, and argv_factory is given,
    argv_factory("libx264") replaces argv. Network or key failures never
    trigger it. Without on_status, progress lines are echoed to out.
    Returns an exit code.
    """
    def report(state, detail=None):
        if on_status:
            on_status(state, detail)

    if sleep is None:
        sleep = stop.wait if stop is not None else time.sleep
    failures = 0
    encoder_failures = 0
    while True:
        started = clock()
        report(STATUS_STARTING)
        proc = popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE, universal_newlines=True,
                     **priority_kwargs(os_name))
        finished = threading.Event()
        encoder_blamed = False
        if stop is not None:
            threading.Thread(target=_watch_for_stop, args=(stop, proc, finished),
                             daemon=True).start()
        try:
            for line in proc.stderr:
                health = parse_progress(line)
                if health:
                    report(STATUS_LIVE, health)
                    if not on_status:
                        out.write(redact(line.rstrip("\n"), key) + "\r")
                else:
                    out.write(redact(line, key))
                    encoder_blamed = encoder_blamed or mentions_encoder_problem(line)
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            out.write("Stopped.\n")
            report(STATUS_STOPPED)
            return 0
        finally:
            finished.set()
        if stop is not None and stop.is_set():
            out.write("Stopped.\n")
            report(STATUS_STOPPED)
            return 0
        if code == 0:
            report(STATUS_STOPPED)
            return 0
        quick = clock() - started < HEALTHY_RUN_SECONDS
        failures = failures + 1 if quick else 1
        encoder_failures = encoder_failures + 1 if quick and encoder_blamed else 0
        if (quick and argv_factory and encoder not in (None, SOFTWARE_ENCODER)
                and encoder_failures >= FALLBACK_AFTER_FAILURES):
            out.write("%s keeps failing. Switching to %s.\n"
                      % (encoder, SOFTWARE_ENCODER))
            encoder = SOFTWARE_ENCODER
            argv = argv_factory(encoder)
            failures = 0
            encoder_failures = 0
            report(STATUS_FALLBACK, encoder)
            continue
        if max_failures is not None and failures >= max_failures:
            out.write("ffmpeg keeps failing (exit %d). Giving up.\n" % code)
            report(STATUS_FAILED, code)
            return code
        delay = backoff_delay(failures)
        out.write("ffmpeg exited (%d). Reconnecting in %ds...\n" % (code, delay))
        report(STATUS_RECONNECTING, delay)
        try:
            sleep(delay)
        except KeyboardInterrupt:
            report(STATUS_STOPPED)
            return 0
        if stop is not None and stop.is_set():
            report(STATUS_STOPPED)
            return 0
