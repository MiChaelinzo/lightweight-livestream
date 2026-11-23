"""Run ffmpeg at low priority, reconnect with backoff, never leak the key."""

import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse

from .encoders import SOFTWARE_ENCODER

BACKOFF_CAP_SECONDS = 30
HEALTHY_RUN_SECONDS = 60
WINDOWS_BELOW_NORMAL = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
FALLBACK_AFTER_FAILURES = 2  # quick failures of a hardware encoder before libx264
LAGGING_BELOW_SPEED = 0.95   # ffmpeg speed under 1.0x means it cannot keep up
STOP_POLL_SECONDS = 0.2
FAILOVER_AFTER_FAILURES = 3  # consecutive quick network failures before switching ingest
# Known ffmpeg messages for a hardware encoder that cannot start. Network and
# key errors ("Connection refused", "Input/output error") never match these.
ENCODER_ERROR_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"error while opening encoder",
    r"cannot load nvcuda|no nvenc capable devices|openencodesessionex failed",
    r"error creating a mfx session|error initializing an internal mfx",
    r"failed to (set up|create|initiali[sz]e).*(vaapi|va display|hardware device)",
    r"no usable encoding profile found|device creation failed",
    r"amf.*(failed|error)|(failed|error).*amf",
    r"videotoolbox.*(failed|error)|(failed|error).*videotoolbox",
))

STATUS_STARTING = "starting"
STATUS_LIVE = "live"
STATUS_RECONNECTING = "reconnecting"
STATUS_FALLBACK = "fallback"
STATUS_RESTARTING = "restarting"
STATUS_FAILOVER = "failover"
TARGET_PRIMARY = "primary"
TARGET_BACKUP = "backup"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"

_PROGRESS_FIELDS = (
    ("fps", re.compile(r"fps=\s*([\d.]+)")),
    ("bitrate_kbps", re.compile(r"bitrate=\s*([\d.]+)\s*kbits/s")),
    ("speed", re.compile(r"speed=\s*([\d.]+)x")),
    ("dropped", re.compile(r"drop=\s*(\d+)")),
    ("dup", re.compile(r"dup=\s*(\d+)")),
)


def redact(text, key):
    """Hide key (a string, or a tuple/list of secrets) in text, including its
    percent-encoded and quote_plus (spaces as +) forms."""
    secrets = key if isinstance(key, (tuple, list)) else (key,)
    for secret in secrets:
        if not secret:
            continue
        forms = (secret, urllib.parse.quote(secret, safe=""),
                 urllib.parse.quote(secret), urllib.parse.quote_plus(secret))
        for form in sorted(set(forms), key=len, reverse=True):
            text = text.replace(form, "****")
    return text


def format_command(argv, key):
    return " ".join(redact(a, key) if " " not in a else '"%s"' % redact(a, key)
                    for a in argv)


def backoff_delay(failures):
    """1, 2, 4, 8 ... capped seconds, for the Nth consecutive quick failure."""
    return min(2 ** max(failures - 1, 0), BACKOFF_CAP_SECONDS)


def priority_kwargs(os_name, cpu_affinity=None, nice=os.nice,
                    set_affinity=getattr(os, "sched_setaffinity", None)):
    """Popen kwargs that make ffmpeg yield to the game.

    cpu_affinity is a set of CPU ids to confine ffmpeg to. It is applied only
    where os.sched_setaffinity exists (Linux); elsewhere it is a no-op.
    """
    if os_name == "windows":
        return {"creationflags": WINDOWS_BELOW_NORMAL}

    def lower_priority():
        nice(10)
        if cpu_affinity and set_affinity is not None:
            set_affinity(0, set(cpu_affinity))
    return {"preexec_fn": lower_priority}


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
    return any(pattern.search(line) for pattern in ENCODER_ERROR_PATTERNS)


def is_lagging(health):
    """True when ffmpeg encodes slower than real time (viewers will buffer)."""
    return "speed" in health and health["speed"] < LAGGING_BELOW_SPEED


def _watch_for_stop(stop, proc, finished, restart=None):
    """Terminate ffmpeg as soon as stop (or restart) is set, even while it
    prints nothing."""
    waiter = stop if stop is not None else finished
    while not finished.is_set():
        waiter.wait(STOP_POLL_SECONDS)
        wanted = (stop is not None and stop.is_set()) or (
            restart is not None and restart.is_set())
        if wanted and not finished.is_set():
            proc.terminate()
            return


def run_with_reconnect(argv, key, os_name, popen=subprocess.Popen,
                       sleep=None, clock=time.monotonic,
                       out=sys.stderr, max_failures=None, stop=None,
                       on_status=None, encoder=None, argv_factory=None,
                       argv_for_attempt=None, cpu_affinity=None, restart=None,
                       backup_argv_for_attempt=None):
    """Run ffmpeg until it exits cleanly, is stopped, or fails too often.

    max_failures=None keeps trying forever. stop is a threading.Event; setting
    it ends the stream and returns 0. on_status(state, detail) reports
    starting, live (detail is the health dict), reconnecting (detail is the
    delay), fallback (detail is the new encoder), stopped and failed.
    If a hardware encoder fails quickly FALLBACK_AFTER_FAILURES times in a
    row, with stderr naming the encoder, and argv_factory is given,
    argv_factory("libx264") replaces argv. Network or key failures never
    trigger it. Without on_status, progress lines are echoed to out.
    argv_for_attempt(attempt, encoder), when given, returns the argv for each
    relaunch (attempt 1, 2, ...), e.g. a new recording file name per attempt.
    cpu_affinity (a set of CPU ids) confines ffmpeg to those cores on Linux.
    restart (a threading.Event), when set, ends the running ffmpeg and starts
    it again at once with argv_for_attempt's argv: no backoff, no failure
    count, status "restarting". Auto-scaling uses it to apply a new step.
    backup_argv_for_attempt(attempt, encoder), when given, enables ingest
    failover: after FAILOVER_AFTER_FAILURES consecutive quick failures that
    are not encoder problems, the next launch uses its argv and the status is
    "failover" with detail "backup". If the backup fails as often, it switches
    back to "primary". A switch does not reset the max_failures count. A healthy run (HEALTHY_RUN_SECONDS) resets the count
    but stays on the ingest that worked. A restart keeps the current ingest.
    Returns an exit code.
    """
    def report(state, detail=None):
        if on_status:
            on_status(state, detail)

    if sleep is None:
        sleep = stop.wait if stop is not None else time.sleep
    failures = 0
    encoder_failures = 0
    attempt = 0
    primary_argv = argv
    on_backup = False
    network_failures = 0
    while True:
        if restart is not None:
            # A restart requested during a backoff sleep or a failed run is
            # satisfied by this very launch; leaving it set would relaunch
            # a second time. Cleared before argv is built so a request made
            # after this point is kept.
            restart.clear()
        if attempt and on_backup:
            argv = backup_argv_for_attempt(attempt, encoder)
        elif attempt and argv_for_attempt:
            argv = argv_for_attempt(attempt, encoder)
        elif attempt and backup_argv_for_attempt:
            argv = primary_argv  # back on the primary without a rebuild seam
        attempt += 1
        started = clock()
        report(STATUS_STARTING)
        proc = popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE, universal_newlines=True,
                     **priority_kwargs(os_name, cpu_affinity))
        finished = threading.Event()
        encoder_blamed = False
        if stop is not None or restart is not None:
            threading.Thread(target=_watch_for_stop,
                             args=(stop, proc, finished, restart),
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
        if restart is not None and restart.is_set():
            failures = 0
            encoder_failures = 0
            network_failures = 0
            report(STATUS_RESTARTING)
            continue
        if code == 0:
            report(STATUS_STOPPED)
            return 0
        quick = clock() - started < HEALTHY_RUN_SECONDS
        failures = failures + 1 if quick else 1
        network_failures = (network_failures + 1
                            if quick and not encoder_blamed else 0)
        encoder_failures = encoder_failures + 1 if quick and encoder_blamed else 0
        if (quick and argv_factory and encoder not in (None, SOFTWARE_ENCODER)
                and encoder_failures >= FALLBACK_AFTER_FAILURES):
            out.write("%s keeps failing. Switching to %s.\n"
                      % (encoder, SOFTWARE_ENCODER))
            encoder = SOFTWARE_ENCODER
            argv = primary_argv = argv_factory(encoder)
            failures = 0
            encoder_failures = 0
            report(STATUS_FALLBACK, encoder)
            continue
        if (backup_argv_for_attempt and quick
                and network_failures >= FAILOVER_AFTER_FAILURES):
            on_backup = not on_backup
            network_failures = 0  # failures is kept so max_failures still ends a dead link
            target = TARGET_BACKUP if on_backup else TARGET_PRIMARY
            out.write("Connection keeps failing. Switching to the %s ingest.\n"
                      % target)
            report(STATUS_FAILOVER, target)
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
