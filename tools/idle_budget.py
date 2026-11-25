"""Idle budgets of the GUI window: startup time, idle memory, idle CPU.

    DISPLAY=:99 python3 tools/idle_budget.py --duration 20 --out idle.json

Launches the real `StreamWindow` in a child Python on the current DISPLAY (for
a headless box start Xvfb first, see docs/DEV-RENDERING.md), waits until the
window has been built and drawn once, lets it settle, then samples the child
from /proc for `--duration` seconds. Prints one JSON object to stdout:

    startup_s         wall time from launching the child to the first drawn window
    rss_mb            VmRSS at the end of the idle window
    rss_mb_peak       highest VmRSS seen while idle
    idle_cpu_percent  mean CPU over the idle window (100 is one full core)
    budgets / violations  the limits below and which of them were exceeded

The exit status is 1 when a budget is exceeded. Sampling reuses
tools/benchlab.py (/proc parsing, ReadyWatcher, sample_pid), so the same method
notes apply: only the GUI process itself is sampled, Linux only. The child
uses a throw-away HOME so real preferences are neither read nor written.
Standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import benchlab  # noqa: E402

BUDGETS = {"startup_s": 2.0, "rss_mb": 150.0, "idle_cpu_percent": 5.0}
READY_TEXT = "LIGHTSTREAM-WINDOW-READY"
DEFAULT_DURATION_S = 20.0
DEFAULT_SETTLE_S = 2.0
DEFAULT_INTERVAL_S = 1.0
STARTUP_TIMEOUT_S = 30.0
POLL_S = 0.02
CHILD_CODE = (
    "import tkinter\n"
    "from lightstream import gui\n"
    "root = tkinter.Tk()\n"
    "gui.StreamWindow(root)\n"
    "root.update()\n"
    "print(%r, flush=True)\n"
    "root.mainloop()\n" % READY_TEXT)


# Pure helpers (unit tested in tests/test_idle_budget.py)

def build_result(startup_s, samples):
    """Report numbers from the idle samples ([{"cpu_percent", "rss_bytes"}])."""
    summary = benchlab.summarize(samples)
    rss_values = [s["rss_bytes"] for s in samples if s["rss_bytes"] is not None]
    last_rss = rss_values[-1] / benchlab.BYTES_PER_MB if rss_values else None
    return {
        "startup_s": None if startup_s is None else round(startup_s, 3),
        "rss_mb": None if last_rss is None else round(last_rss, 2),
        "rss_mb_peak": summary["rss_mb_peak"],
        "idle_cpu_percent": summary["cpu_percent_avg"],
        "idle_cpu_percent_max": summary["cpu_percent_max"],
        "samples": summary["samples"],
    }


def check_budgets(result, budgets=None):
    """Names of the budgets that `result` exceeds or could not measure."""
    budgets = BUDGETS if budgets is None else budgets
    violations = []
    for name, limit in sorted(budgets.items()):
        value = result.get(name)
        if value is None or value >= limit:
            violations.append(name)
    return violations


# Measurement

def display_available(environ=None):
    environ = os.environ if environ is None else environ
    return bool(environ.get("DISPLAY"))


def wait_for_ready(watcher, proc, timeout, clock=time.monotonic, sleep=time.sleep):
    """Block until the watcher saw the ready text, the child exited or time ran out."""
    end = clock() + timeout
    while watcher.found_at is None and proc.poll() is None and clock() < end:
        sleep(POLL_S)
    return watcher.found_at


def measure_window(duration=DEFAULT_DURATION_S, settle=DEFAULT_SETTLE_S,
                   interval=DEFAULT_INTERVAL_S, python=None):
    """Start the GUI on the current DISPLAY and return the result dict."""
    python = python or sys.executable
    with tempfile.TemporaryDirectory(prefix="lightstream-idle-") as home:
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
                   PYTHONPATH=os.path.join(ROOT, "src"))
        started = time.monotonic()
        proc = subprocess.Popen([python, "-c", CHILD_CODE], env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, shell=False)
        try:
            watcher = benchlab.ReadyWatcher(proc.stdout, READY_TEXT, started)
            startup = wait_for_ready(watcher, proc, STARTUP_TIMEOUT_S)
            if startup is None:
                return build_result(None, [])
            time.sleep(settle)
            samples = benchlab.sample_pid(proc.pid, duration, interval)
            return build_result(startup, samples)
        finally:
            benchlab.stop_process(proc)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S,
                        help="idle sampling window in seconds (default 20)")
    parser.add_argument("--settle", type=float, default=DEFAULT_SETTLE_S,
                        help="seconds to wait after the window is drawn before sampling")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    parser.add_argument("--out", help="also write the JSON report here")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.duration <= 0 or args.interval <= 0 or args.settle < 0:
        sys.stderr.write("Error: --duration and --interval must be above 0, "
                         "--settle must not be negative\n")
        return 2
    if not benchlab.proc_available():
        sys.stderr.write("Error: /proc is not available; only Linux is supported\n")
        return 2
    if not display_available():
        sys.stderr.write("Error: DISPLAY is not set; start Xvfb first "
                         "(docs/DEV-RENDERING.md)\n")
        return 2
    result = measure_window(args.duration, args.settle, args.interval)
    result["budgets"] = dict(BUDGETS)
    result["violations"] = check_budgets(result)
    text = json.dumps(result, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    sys.stdout.write(text)
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
