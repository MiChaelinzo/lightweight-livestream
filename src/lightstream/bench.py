"""Reproducible benchmark harness: `lightstream bench`.

Measures what this code costs and what a synthetic encode costs on THIS
machine, and writes numbers to a JSON report (no stream key, no URL, no
paths). Every metric is {"value": ..., "status": "measured"} or
{"value": None, "status": "unavailable", "reason": ...}. Nothing is estimated.

What it measures
    startup       wall time of `python -c "import lightstream.cli"` (median of
                  N runs) next to a bare interpreter start, plus resident
                  memory (RSS) of a child after the import and after N
                  simulated ticks of the health, advisor, optimizer,
                  auto-scaler and telemetry code. RSS needs /proc (Linux).
    tick costs    process CPU microseconds per call (time.process_time) for
                  each per-second component and for parse_progress.
    command build microseconds to resolve settings and build the ffmpeg argv
                  for each performance profile.
    encode        synthetic testsrc2 encode per profile geometry, null
                  output, for --seconds of stream time. Wall time, ffmpeg's
                  reported speed, child CPU seconds and peak RSS (from
                  os.wait4, so each child is measured on its own; Unix only),
                  and encoder CPU-seconds per stream-second.
    gaming first  the same encode with different encoder thread counts. This
                  is a PROXY: it shows how much CPU the encoder takes and how
                  its speed changes with fewer threads. It is NOT game FPS.

Limits
    The encode runs as fast as the CPU allows (no -re), so speed shows
    headroom, not real-time behavior. testsrc2 frame generation and the
    scaler are included in the CPU time; audio is not encoded. Results from
    one machine say nothing about another.
"""

import json
import os
import statistics
import subprocess
import sys
import time
from collections import namedtuple

from . import __version__
from .analytics import reports_dir
from .command import _encoder_args, build_command, thread_args
from .config import detect_os, resolve_settings
from .encoders import (HARDWARE_ORDER, SOFTWARE_ENCODER, encoder_works,
                       probe_encoders)
from .perf_profiles import PERF_PROFILES, resolve_tuning
from .presets import PRESETS
from .runner import parse_progress

BENCH_VERSION = 1
DEFAULT_ENCODE_SECONDS = 10
DEFAULT_TICKS = 1000
DEFAULT_IMPORT_RUNS = 5
MICROSECONDS = 1e6
KIB_PER_MIB = 1024.0
SYNTHETIC_KEY = "bench-not-a-real-key"
PROGRESS_SAMPLE_LINE = ("frame=  100 fps= 30 q=28.0 size=    1024kB time=00:00:03.33 "
                        "bitrate=2500.0kbits/s dup=0 drop=0 speed=1.0x")

CAVEAT = ("These numbers come from one machine. They measure software or detected "
          "encoders on synthetic video, with no game running. The Gaming First "
          "comparison is a proxy (encoder CPU and speed with different thread "
          "counts), not a game FPS measurement. Do not treat them as typical for "
          "other hardware.")

# Benchmark tiers. A machine earns the HIGHEST tier whose three minimums it
# meets (CPU threads, RAM in MiB, and ffmpeg speed of the uncapped software
# balanced encode, as a multiple of real time). Low-End has no minimums, so it
# is the floor. A metric that could not be measured is skipped (and listed),
# never guessed. The numbers are plain heuristics chosen for this project, not
# vendor or industry standards; they only rank results from this harness.
TIER_LOW_END = "Low-End"
TIERS = (
    # (name, min cpu threads, min RAM MiB, min speed x)
    (TIER_LOW_END, 0, 0, 0.0),
    ("Balanced", 4, 4096, 2.0),
    ("Performance", 6, 8192, 4.0),
    ("Creator", 8, 16384, 6.0),
    ("Power User", 12, 32768, 10.0),
)
TIER_BASIS = ("highest tier whose CPU threads, RAM and uncapped software "
              "encode speed minimums are all met; unmeasured metrics skipped")

# Child process code. Reads its own RSS from /proc (Linux). Kept as plain text
# so it also runs against an older source tree (--compare-src).
RSS_PROBE = (
    "import json\n"
    "#IMPORTS#\n"
    "rss = None\n"
    "try:\n"
    "    for line in open('/proc/self/status'):\n"
    "        if line.startswith('VmRSS:'):\n"
    "            rss = int(line.split()[1]) / 1024.0\n"
    "except OSError:\n"
    "    pass\n"
    "print(json.dumps({'rss_mb': rss}))\n")
IMPORT_CODE = "import lightstream.cli"
WORKLOAD_CODE = ("import json\n"
                 "from lightstream import bench\n"
                 "print(json.dumps(bench.tick_workload_rss(%d)))\n")


def metric(value, reason=None):
    """Labelled metric. value None means unavailable and needs a reason."""
    if value is None:
        return {"value": None, "status": "unavailable",
                "reason": reason or "not measured on this system"}
    return {"value": value, "status": "measured"}


def read_rss_mb(read_text=None):
    """This process's resident memory in MiB from /proc/self/status, or None."""
    from .telemetry import parse_vmrss_mb
    try:
        if read_text is None:
            with open("/proc/self/status", "r", encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = read_text("/proc/self/status")
        return parse_vmrss_mb(text)
    except (OSError, ValueError):
        return None


def host_info(cpu_count=None, ram_mb=None, os_name=None):
    from .wizard import detect_ram_mb
    os_name = os_name or detect_os()
    ram = ram_mb if ram_mb is not None else detect_ram_mb(os_name)
    return {"os": metric(os_name),
            "cpu_count": metric(cpu_count if cpu_count is not None else os.cpu_count()),
            "ram_mb": metric(ram, "RAM could not be read on this OS"),
            "python": metric(sys.version.split()[0])}


# -- startup and memory (child processes) ----------------------------------

def _child_env(src_path):
    env = dict(os.environ)
    if src_path:
        env["PYTHONPATH"] = src_path
    return env


def _timed_runs(python, code, runs, env, run, clock):
    millis = []
    for _ in range(runs):
        started = clock()
        result = run([python, "-c", code], env=env, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
        elapsed = (clock() - started) * 1000.0
        if result.returncode != 0:
            return None
        millis.append(elapsed)
    return millis


def _child_json(python, code, env, run):
    result = run([python, "-c", code], env=env, stdout=subprocess.PIPE,
                 stderr=subprocess.DEVNULL, universal_newlines=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def measure_startup(python=None, runs=DEFAULT_IMPORT_RUNS, src_path=None,
                    run=subprocess.run, clock=time.perf_counter):
    """Import time and RSS of a fresh interpreter. src_path sets PYTHONPATH
    (default: inherit), which is how an older source tree is compared."""
    python = python or sys.executable
    env = _child_env(src_path)
    bare = _timed_runs(python, "pass", runs, env, run, clock)
    imported = _timed_runs(python, IMPORT_CODE, runs, env, run, clock)
    bare_rss = _child_json(python, RSS_PROBE.replace("#IMPORTS#", ""), env, run)
    import_rss = _child_json(python, RSS_PROBE.replace("#IMPORTS#", IMPORT_CODE),
                             env, run)
    why = "child process failed (is src_path a lightstream source tree?)"
    return {
        "runs": runs,
        "bare_interpreter_ms_median": metric(
            statistics.median(bare) if bare else None, why),
        "import_cli_ms_median": metric(
            statistics.median(imported) if imported else None, why),
        "import_cli_ms_samples": imported or [],
        "rss_bare_interpreter_mb": metric(
            bare_rss and bare_rss["rss_mb"], "needs /proc (Linux)"),
        "rss_after_import_mb": metric(
            import_rss and import_rss["rss_mb"], "needs /proc (Linux)"),
    }


# -- per-tick CPU cost ------------------------------------------------------

def _tick_components():
    """Zero-argument callables, one per per-second component, built fresh."""
    from .adaptive import AdaptiveAdvisor
    from .autoscale import AutoScaler, assess, build_ladder, top_step
    from .health import HealthTracker
    from .optimizer import OptimizerContext, build_insights
    from .telemetry import TelemetrySampler

    preset = PRESETS["balanced"]
    settings = resolve_settings({"preset": preset.name}, {}, cpu_count=2)
    health_line = parse_progress(PROGRESS_SAMPLE_LINE)
    tracker = HealthTracker(target_kbps=preset.video_kbps)
    advisor = AdaptiveAdvisor(preset.name, preset.video_kbps, preset.fps)
    scaler = AutoScaler(build_ladder(top_step(settings)), enabled=True)
    sampler = TelemetrySampler()
    context = OptimizerContext(preset.name, preset.video_kbps, preset.fps,
                               SOFTWARE_ENCODER, "off")

    def optimizer():
        build_insights(advisor, tracker.summary(), sampler.history,
                       tracker.network_stability(), context)

    def autoscaler():
        scaler.update(assess(advisor, sampler.latest))

    return (
        ("parse_progress", lambda: parse_progress(PROGRESS_SAMPLE_LINE)),
        ("health_tracker_update", lambda: tracker.update(health_line)),
        ("adaptive_advisor_observe", lambda: advisor.observe(health_line)),
        ("telemetry_sampler_tick", sampler.tick),
        ("optimizer_build_insights", optimizer),
        ("autoscaler_update", autoscaler),
    )


def measure_tick_costs(ticks=DEFAULT_TICKS, cpu_clock=time.process_time,
                       components=None):
    """Mean CPU microseconds per call of each component over `ticks` calls.

    process_time has a coarse resolution on some systems; a mean over many
    calls keeps that error small, but very cheap calls can read as 0."""
    components = components if components is not None else _tick_components()
    costs = {}
    for name, call in components:
        started = cpu_clock()
        for _ in range(ticks):
            call()
        costs[name] = metric((cpu_clock() - started) / ticks * MICROSECONDS)
    return {"ticks": ticks, "cpu_microseconds_per_call": costs}


def tick_workload_rss(ticks=DEFAULT_TICKS):
    """Run in a child: RSS before and after `ticks` simulated ticks of every
    component (including a real telemetry sampler)."""
    components = _tick_components()
    before = read_rss_mb()
    for _ in range(ticks):
        for _name, call in components:
            call()
    return {"rss_before_mb": before, "rss_after_mb": read_rss_mb(), "ticks": ticks}


def measure_tick_memory(ticks=DEFAULT_TICKS, python=None, run=subprocess.run):
    data = _child_json(python or sys.executable, WORKLOAD_CODE % ticks,
                       _child_env(None), run)
    why = "needs /proc (Linux) and a working child process"
    return {"ticks": ticks,
            "rss_before_mb": metric(data and data["rss_before_mb"], why),
            "rss_after_mb": metric(data and data["rss_after_mb"], why)}


# -- command build ----------------------------------------------------------

def measure_command_build(os_name="linux", repeats=DEFAULT_TICKS,
                          cpu_clock=time.process_time, cpu_count=None):
    """Microseconds to resolve settings and build the argv, per profile."""
    results = {}
    for name in PERF_PROFILES:
        started = cpu_clock()
        for _ in range(repeats):
            settings = resolve_settings({"profile": name}, {}, cpu_count=cpu_count)
            build_command(settings, SYNTHETIC_KEY, os_name, SOFTWARE_ENCODER)
        results[name] = metric((cpu_clock() - started) / repeats * MICROSECONDS)
    return {"repeats": repeats, "cpu_microseconds_per_build": results}


# -- synthetic encode -------------------------------------------------------

def encode_argv(ffmpeg, encoder, preset_name, seconds, threads=None):
    """ffmpeg argv for a synthetic encode to a null sink, progress on stdout."""
    preset = PRESETS[preset_name]
    settings = resolve_settings({"preset": preset_name}, {})
    argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats",
            "-progress", "pipe:1"]
    if encoder == "h264_vaapi":
        argv += ["-vaapi_device", "/dev/dri/renderD128"]
    argv += ["-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=%d"
             % (preset.width, preset.height, preset.fps), "-t", str(seconds)]
    if encoder == "h264_vaapi":
        argv += ["-vf", "format=nv12,hwupload"]
    argv += _encoder_args(encoder, settings)
    if threads:
        argv += thread_args(threads, False, encoder)
    argv += ["-b:v", "%dk" % preset.video_kbps, "-maxrate", "%dk" % preset.video_kbps,
             "-bufsize", "%dk" % preset.video_kbps, "-g", str(preset.fps * 2),
             "-bf", "0", "-an", "-f", "null", "-"]
    return argv


def parse_speed(line):
    """Float from an ffmpeg -progress 'speed=12.3x' line, else None."""
    if not line.startswith("speed="):
        return None
    text = line[len("speed="):].strip().rstrip("x")
    try:
        return float(text)
    except ValueError:
        return None


EncodeResult = namedtuple(
    "EncodeResult", "returncode wall_seconds speed cpu_seconds max_rss_mb error")


def spawn_encode(argv, clock=time.perf_counter, popen=subprocess.Popen,
                 wait4=getattr(os, "wait4", None)):
    """Run one encode. CPU seconds and peak RSS come from os.wait4 (Unix); they
    are None where wait4 does not exist."""
    started = clock()
    proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 universal_newlines=True)
    speed = None
    errors = []
    for line in proc.stdout:
        parsed = parse_speed(line)
        if parsed is not None:
            speed = parsed
        elif "=" not in line:
            errors.append(line.strip())
    cpu = rss = None
    if wait4 is not None:
        _pid, status, usage = wait4(proc.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        cpu = usage.ru_utime + usage.ru_stime
        rss = usage.ru_maxrss / KIB_PER_MIB if sys.platform.startswith("linux") else None
    else:
        code = proc.wait()
    return EncodeResult(code, clock() - started, speed, cpu, rss,
                        " ".join(errors[-3:]) or None)


def _encode_entry(label, encoder, preset_name, seconds, threads, argv, spawn):
    result = spawn(argv)
    ok = result.returncode == 0
    why = result.error or "encode failed (exit %s)" % result.returncode
    cpu_per_second = (result.cpu_seconds / seconds
                      if ok and result.cpu_seconds is not None else None)
    return {
        "label": label,
        "encoder": encoder,
        "preset": preset_name,
        "geometry": "%dx%d@%d" % (PRESETS[preset_name].width,
                                  PRESETS[preset_name].height,
                                  PRESETS[preset_name].fps),
        "threads": threads,
        "stream_seconds": seconds,
        "ok": ok,
        "wall_seconds": metric(result.wall_seconds if ok else None, why),
        "ffmpeg_speed": metric(result.speed if ok else None,
                               why if not ok else "ffmpeg printed no speed"),
        "child_cpu_seconds": metric(result.cpu_seconds if ok else None,
                                    why if not ok else "needs os.wait4 (Unix)"),
        "peak_rss_mb": metric(result.max_rss_mb if ok else None,
                              why if not ok else "needs os.wait4 on Linux"),
        "cpu_seconds_per_stream_second": metric(
            cpu_per_second, why if not ok else "needs os.wait4 (Unix)"),
    }


def measure_encodes(ffmpeg, seconds=DEFAULT_ENCODE_SECONDS, cpu_count=None,
                    spawn=spawn_encode, run=subprocess.run):
    """Encode benchmark. Returns the 'encode' section of the report."""
    cpus = cpu_count or os.cpu_count() or 1
    try:
        available = probe_encoders(ffmpeg, run)
    except RuntimeError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    hardware = [e for e in HARDWARE_ORDER if e in available]
    working = [e for e in hardware if encoder_works(ffmpeg, e, run)]
    profiles = []
    seen = set()
    for name, profile in PERF_PROFILES.items():
        tuning = resolve_tuning(name, cpus)
        key = (profile.preset_name, tuning.threads)
        if key in seen:
            continue  # same geometry and threads as an earlier profile
        seen.add(key)
        argv = encode_argv(ffmpeg, SOFTWARE_ENCODER, profile.preset_name, seconds,
                           tuning.threads)
        entry = _encode_entry(name, SOFTWARE_ENCODER, profile.preset_name, seconds,
                              tuning.threads, argv, spawn)
        entry["same_settings_as"] = [
            other for other, p in PERF_PROFILES.items()
            if other != name and p.preset_name == profile.preset_name
            and resolve_tuning(other, cpus).threads == tuning.threads]
        profiles.append(entry)
    hardware_runs = [
        _encode_entry("hardware", enc, "balanced", seconds, None,
                      encode_argv(ffmpeg, enc, "balanced", seconds), spawn)
        for enc in working]
    return {
        "status": "measured",
        "seconds": seconds,
        "software_profiles": profiles,
        "gaming_first_proxy": measure_thread_comparison(ffmpeg, seconds, cpus, spawn),
        "hardware_encoders": {
            "listed_by_ffmpeg": hardware,
            "test_encode_works": working,
            "runs": hardware_runs,
            "note": "none detected" if not hardware else
                    "listed encoders that failed a test encode are not benchmarked",
        },
    }


def measure_thread_comparison(ffmpeg, seconds, cpus, spawn=spawn_encode):
    """Same balanced encode uncapped and with each Gaming First thread count."""
    counts = [None]
    for name in PERF_PROFILES:
        threads = resolve_tuning(name, cpus).threads
        if threads is not None and threads not in counts:
            counts.append(threads)
    runs = []
    for threads in counts:
        label = "uncapped" if threads is None else "%d threads" % threads
        argv = encode_argv(ffmpeg, SOFTWARE_ENCODER, "balanced", seconds, threads)
        runs.append(_encode_entry(label, SOFTWARE_ENCODER, "balanced", seconds,
                                  threads, argv, spawn))
    return {"proxy_note": "Encoder CPU and speed only. This is NOT game FPS.",
            "runs": runs}


# -- tiers ------------------------------------------------------------------

def _value(entry):
    """The number inside a metric dict, or None when unavailable."""
    if isinstance(entry, dict) and entry.get("status") == "measured":
        return entry.get("value")
    return None


def encode_speed_of(report):
    """Speed (x real time) of the uncapped software balanced run, or None."""
    encode = report.get("encode") or {}
    proxy = encode.get("gaming_first_proxy") or {}
    for run in proxy.get("runs", ()):
        if run.get("label") == "uncapped" and run.get("ok"):
            return _value(run.get("ffmpeg_speed"))
    return None


def compute_tier(cpu_count, ram_mb, speed):
    """Tier dict from three measured numbers (any may be None). Pure.

    Boundaries are inclusive: a value equal to a minimum meets it.
    """
    measured = {"cpu_count": cpu_count, "ram_mb": ram_mb, "encode_speed": speed}
    skipped = [name for name, v in measured.items() if v is None]
    earned = TIERS[0][0]
    for name, min_cpu, min_ram, min_speed in TIERS[1:]:
        checks = ((cpu_count, min_cpu), (ram_mb, min_ram), (speed, min_speed))
        if all(v is None or v >= m for v, m in checks):
            if all(v is None for v, _ in checks):
                break  # nothing measured: stay at the floor
            earned = name
        else:
            break
    return {"name": earned, "basis": TIER_BASIS, "skipped_metrics": skipped,
            "inputs": measured}


def tier_of_report(report):
    host = report.get("host") or {}
    return compute_tier(_value(host.get("cpu_count")), _value(host.get("ram_mb")),
                        encode_speed_of(report))


def tier_table_lines():
    return ["  %-11s cpu>=%-3d ram>=%-6d MiB speed>=%.1fx" % t for t in TIERS[1:]]


# -- report -----------------------------------------------------------------

def build_report(ffmpeg=None, seconds=DEFAULT_ENCODE_SECONDS, ticks=DEFAULT_TICKS,
                 import_runs=DEFAULT_IMPORT_RUNS, compare_src=None, now=None,
                 cpu_count=None, run=subprocess.run, spawn=spawn_encode):
    """The whole report dict. Nothing in it comes from user config or keys."""
    startup = measure_startup(runs=import_runs, run=run)
    report = {
        "bench_version": BENCH_VERSION,
        "lightstream_version": __version__,
        "date": time.strftime("%Y-%m-%d", now or time.localtime()),
        "caveat": CAVEAT,
        "host": host_info(cpu_count),
        "startup": startup,
        "tick_memory": measure_tick_memory(ticks, run=run),
        "tick_costs": measure_tick_costs(ticks),
        "command_build": measure_command_build(repeats=ticks, cpu_count=cpu_count),
    }
    if compare_src:
        report["startup_compare_src"] = measure_startup(
            runs=import_runs, src_path=compare_src, run=run)
    if ffmpeg:
        report["encode"] = measure_encodes(ffmpeg, seconds, cpu_count, spawn, run)
    else:
        report["encode"] = {"status": "unavailable",
                            "reason": "ffmpeg not found; pass --ffmpeg PATH"}
    report["tier"] = tier_of_report(report)
    return report


def report_path(date, directory=None):
    return os.path.join(directory or reports_dir(), "bench-%s.json" % date)


def write_report(report, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    return path
