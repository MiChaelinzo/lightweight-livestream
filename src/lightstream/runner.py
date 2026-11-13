"""Run ffmpeg at low priority, reconnect with backoff, never leak the key."""

import os
import subprocess
import sys
import time

BACKOFF_CAP_SECONDS = 30
HEALTHY_RUN_SECONDS = 60
WINDOWS_BELOW_NORMAL = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS


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


def run_with_reconnect(argv, key, os_name, popen=subprocess.Popen,
                       sleep=time.sleep, clock=time.monotonic,
                       out=sys.stderr, max_failures=None):
    """Run ffmpeg until it exits cleanly or Ctrl+C. Returns an exit code."""
    failures = 0
    while True:
        started = clock()
        proc = popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE, universal_newlines=True,
                     **priority_kwargs(os_name))
        try:
            for line in proc.stderr:
                out.write(redact(line, key))
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            out.write("Stopped.\n")
            return 0
        if code == 0:
            return 0
        failures = 1 if clock() - started >= HEALTHY_RUN_SECONDS else failures + 1
        if max_failures is not None and failures >= max_failures:
            out.write("ffmpeg keeps failing (exit %d). Giving up.\n" % code)
            return code
        delay = backoff_delay(failures)
        out.write("ffmpeg exited (%d). Reconnecting in %ds...\n" % (code, delay))
        try:
            sleep(delay)
        except KeyboardInterrupt:
            return 0
