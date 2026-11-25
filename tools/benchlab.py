"""Benchmark Lab: sample CPU and memory of running programs on YOUR machine.

    python3 tools/benchlab.py --pid "OBS Studio:4242" --pid "LightStream:5151"
    python3 tools/benchlab.py --command "ffmpeg:ffmpeg -f lavfi -i testsrc -f null -" \\
        --ready-text "frame=" --duration 10 --out benchlab.json --markdown benchlab.md

A target is `LABEL:PID` (a process that is already running) or `LABEL:COMMAND`
(the tool starts it, measures startup, and stops it afterwards; the command is
split with shlex and run without a shell). The default table has columns for
"OBS Studio" and "Streamlabs Desktop" that stay UNKNOWN until you measure them
yourself with the same label. This tool never ships competitor numbers.

Method (see docs/architecture/DELIVERY.md, "Competitive benchmark methodology"):
- CPU percent is (utime + stime ticks) used between two samples divided by the
  wall time between them, so 100 means one full core. Only the target process
  itself is sampled, not its children (a multi process app is under reported).
- Memory is VmRSS from /proc/PID/status.
- Startup is the time from launching a --command until its output first
  contains --ready-text. Without --ready-text, or for a --pid target, startup
  is UNKNOWN.
- Sampling needs /proc, so only Linux is supported. Elsewhere the report says
  so and every number is null (UNVERIFIED on Windows and macOS).

Only JSON goes to stdout. Standard library only; psutil is not used.
"""

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import threading
import time

SCHEMA_VERSION = 1
UNKNOWN = "UNKNOWN"
NOT_AVAILABLE = "n/a"
DEFAULT_DURATION_S = 10.0
DEFAULT_INTERVAL_S = 1.0
STOP_WAIT_S = 3.0
READ_CHUNK = 4096
READY_TAIL_BYTES = 1024
COMPETITORS = ("OBS Studio", "Streamlabs Desktop")
METRICS = (
    ("startup_s", "Startup (s)"),
    ("cpu_percent_avg", "CPU avg (% of one core)"),
    ("cpu_percent_max", "CPU max (% of one core)"),
    ("rss_mb_avg", "RSS avg (MB)"),
    ("rss_mb_peak", "RSS peak (MB)"),
)
BYTES_PER_MB = 1024 * 1024
BYTES_PER_KIB = 1024


# Pure helpers (unit tested in tests/test_benchlab.py)

def parse_stat_ticks(text):
    """utime + stime (clock ticks) from the text of /proc/PID/stat.

    The command name is in parentheses and may contain spaces or parentheses,
    so fields are counted after the last closing parenthesis.
    """
    fields = text.rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])  # utime is field 14, stime 15


def parse_status_rss_bytes(text):
    """VmRSS in bytes from the text of /proc/PID/status, or None (kernel threads)."""
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * BYTES_PER_KIB
    return None


def cpu_percent(ticks_before, ticks_after, wall_seconds, clock_ticks_per_second):
    """CPU use between two samples; 100 is one full core."""
    if wall_seconds <= 0:
        return 0.0
    return 100.0 * (ticks_after - ticks_before) / clock_ticks_per_second / wall_seconds


def summarize(samples):
    """Aggregate [{"cpu_percent": x, "rss_bytes": y}, ...]; None values when empty."""
    cpu = [s["cpu_percent"] for s in samples if s["cpu_percent"] is not None]
    rss = [s["rss_bytes"] for s in samples if s["rss_bytes"] is not None]
    return {
        "samples": len(samples),
        "cpu_percent_avg": round(sum(cpu) / len(cpu), 2) if cpu else None,
        "cpu_percent_max": round(max(cpu), 2) if cpu else None,
        "rss_mb_avg": round(sum(rss) / len(rss) / BYTES_PER_MB, 2) if rss else None,
        "rss_mb_peak": round(max(rss) / BYTES_PER_MB, 2) if rss else None,
    }


def parse_target(spec, is_command):
    """`LABEL:VALUE` into (label, pid or argv). Raises ValueError with a hint."""
    label, sep, value = spec.partition(":")
    if not sep or not label.strip() or not value.strip():
        raise ValueError("target %r must look like LABEL:%s" % (
            spec, "COMMAND" if is_command else "PID"))
    if is_command:
        return label.strip(), shlex.split(value)
    if not value.strip().isdigit():
        raise ValueError("target %r: PID must be a number" % spec)
    return label.strip(), int(value)


def format_value(value):
    if value is None:
        return NOT_AVAILABLE
    return str(value)


def build_markdown(report):
    """Table with one column per measured target, then unmeasured competitors."""
    columns = [t["label"] for t in report["targets"]] + list(report["competitors"])
    lines = ["| Metric | " + " | ".join(columns) + " |",
             "|---|" + "---|" * len(columns)]
    for key, title in METRICS:
        cells = [format_value(t["result"].get(key)) if key != "startup_s"
                 else format_value(t["startup_s"]) for t in report["targets"]]
        cells += [report["competitors"][name][key] for name in report["competitors"]]
        lines.append("| %s | %s |" % (title, " | ".join(cells)))
    lines += ["", "Platform: %s, %d CPUs. Duration %.1f s, interval %.1f s. "
              "UNKNOWN means not measured; this tool ships no competitor numbers." % (
                  report["host"]["system"], report["host"]["cpu_count"],
                  report["method"]["duration_s"], report["method"]["interval_s"])]
    if report["notes"]:
        lines += [""] + ["- " + note for note in report["notes"]]
    return "\n".join(lines) + "\n"


def build_report(targets, duration, interval, system, cpu_count):
    """Assemble the JSON report from finished target results."""
    measured = {t["label"].lower() for t in targets}
    unknown = {metric: UNKNOWN for metric, _ in METRICS}
    notes = []
    if system != "Linux":
        notes.append("Sampling needs /proc (Linux). On %s nothing was measured: "
                     "UNVERIFIED." % system)
    return {
        "tool": "benchlab",
        "schema": SCHEMA_VERSION,
        "host": {"system": system, "cpu_count": cpu_count,
                 "python": platform.python_version()},
        "method": {"duration_s": duration, "interval_s": interval,
                   "cpu": "utime+stime ticks / wall seconds, 100 = one core, target process only",
                   "memory": "VmRSS from /proc/PID/status"},
        "targets": targets,
        "competitors": {name: dict(unknown) for name in COMPETITORS
                        if name.lower() not in measured},
        "notes": notes,
    }


# Process access (Linux /proc)

def proc_available():
    return os.path.isdir("/proc/self")


def read_proc(pid):
    """(ticks, rss_bytes) for a live PID, or None when it is gone."""
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8") as fh:
            ticks = parse_stat_ticks(fh.read())
        with open("/proc/%d/status" % pid, "r", encoding="utf-8") as fh:
            rss = parse_status_rss_bytes(fh.read())
    except (OSError, IndexError, ValueError):
        return None
    return ticks, rss


def sample_pid(pid, duration, interval, read=read_proc, clock=time.monotonic,
               sleep=time.sleep, ticks_per_second=None):
    """Sample one PID until `duration` passes or it exits. Returns the samples."""
    ticks_per_second = ticks_per_second or os.sysconf("SC_CLK_TCK")
    first = read(pid)
    samples = []
    if first is None:
        return samples
    previous_ticks, previous_time = first[0], clock()
    start = previous_time
    samples.append({"cpu_percent": None, "rss_bytes": first[1]})
    while clock() - start < duration:
        sleep(interval)
        current = read(pid)
        now = clock()
        if current is None:
            break
        samples.append({"cpu_percent": cpu_percent(previous_ticks, current[0],
                                                    now - previous_time, ticks_per_second),
                        "rss_bytes": current[1]})
        previous_ticks, previous_time = current[0], now
    return samples


class ReadyWatcher:
    """Drains a child's output and records when `text` first appears."""

    def __init__(self, stream, text, started, clock=time.monotonic):
        self.found_at = None
        self._text = text.encode("utf-8") if text else None
        self._started = started
        self._clock = clock
        self._stream = stream
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        tail = b""
        while True:
            chunk = self._stream.read1(READ_CHUNK)
            if not chunk:
                return
            if self.found_at is None and self._text:
                tail = (tail + chunk)[-(READY_TAIL_BYTES + len(chunk)):]
                if self._text in tail:
                    self.found_at = self._clock() - self._started


def measure_pid(label, pid, duration, interval):
    samples = sample_pid(pid, duration, interval)
    result = summarize(samples)
    result["pid_found"] = bool(samples)
    return {"label": label, "kind": "pid", "pid": pid, "startup_s": UNKNOWN, "result": result}


def measure_command(label, argv, duration, interval, ready_text):
    """Start argv (no shell), time startup, sample it, then stop it."""
    started = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, shell=False)
    try:
        watcher = ReadyWatcher(proc.stdout, ready_text, started)
        samples = sample_pid(proc.pid, duration, interval)
        found = watcher.found_at
        startup = round(found, 3) if found is not None else UNKNOWN
        exited_early = proc.poll() is not None
        result = summarize(samples)
        result["pid_found"] = bool(samples)
        result["exited_before_end"] = exited_early
        return {"label": label, "kind": "command", "pid": proc.pid, "startup_s": startup,
                "result": result}
    finally:
        stop_process(proc)


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    try:
        proc.stdout.close()
    except OSError:
        pass


def run(args):
    """Measure every target and return the report dict."""
    pairs = [(parse_target(spec, False), False) for spec in args.pid] + \
            [(parse_target(spec, True), True) for spec in args.command]
    if not pairs:
        raise ValueError("give at least one --pid LABEL:PID or --command LABEL:COMMAND")
    if args.duration <= 0 or args.interval <= 0:
        raise ValueError("--duration and --interval must be greater than 0")
    targets = []
    if proc_available():
        for (label, value), is_command in pairs:
            if is_command:
                targets.append(measure_command(label, value, args.duration,
                                               args.interval, args.ready_text))
            else:
                targets.append(measure_pid(label, value, args.duration, args.interval))
    else:
        for (label, value), is_command in pairs:
            targets.append({"label": label, "kind": "command" if is_command else "pid",
                            "pid": None if is_command else value, "startup_s": None,
                            "result": summarize([])})
    return build_report(targets, args.duration, args.interval, platform.system(),
                        os.cpu_count() or 1)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pid", action="append", default=[], metavar="LABEL:PID",
                        help="a running process to sample (repeatable)")
    parser.add_argument("--command", action="append", default=[], metavar="LABEL:COMMAND",
                        help="a command to start, sample and stop (repeatable)")
    parser.add_argument("--ready-text", help="text in a --command's output that marks "
                                             "the end of startup")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    parser.add_argument("--out", help="write the JSON report here")
    parser.add_argument("--markdown", help="write the markdown table here")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except ValueError as exc:
        sys.stderr.write("Error: %s\n" % exc)
        return 2
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(build_markdown(report))
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
