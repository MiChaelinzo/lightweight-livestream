"""One-click setup: pick safe low-resource settings for this PC.

build_recommended_config is pure. The stream key is never asked for or saved.
"""

import json
import os
import subprocess
from collections import namedtuple

from . import bandwidth
from .config import config_path, load_file_config
from .encoders import (SOFTWARE_ENCODER, choose_working_encoder, encoder_works,
                       probe_encoders)
from .fileio import write_private_text
from .gui_controller import suggest_strength
from .hardware import (cap_preset_name, classify_gpus, detect_gpu_names,
                       parse_gpu_names)
from .perf_profiles import LOW_RAM_MB, POTATO_RAM_MB, recommend_profile
from .platforms import INGEST_URLS, PLATFORMS
from .portable import find_ffmpeg
from .presets import PRESETS



def detect_ram_mb(os_name, opener=open, windows_probe=None):
    """Installed RAM in MB, or None when it cannot be read."""
    try:
        if os_name == "linux":
            with opener("/proc/meminfo", "r") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
            return None
        if os_name == "windows":
            return (windows_probe or _windows_ram_mb)()
    except (OSError, ValueError, IndexError):
        return None
    return None


def _windows_ram_mb():  # UNVERIFIED: needs a Windows machine
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong),
                    ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong),
                    ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_ext", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.total_phys // (1024 * 1024))


def _lighter(a, b):
    order = list(PRESETS)
    return a if order.index(a) <= order.index(b) else b


def build_recommended_config(gpu_text, cpu_count, ram_mb, upload_kbps, platform):
    """Config dict for this PC. Contains no stream key by construction."""
    if platform not in PLATFORMS:
        raise ValueError("Unknown platform %r. Choose one of: %s"
                         % (platform, ", ".join(PLATFORMS)))
    profile = classify_gpus(parse_gpu_names(gpu_text or ""))
    preset = suggest_strength(cpu_count)
    if ram_mb is not None and ram_mb <= LOW_RAM_MB:
        preset = _lighter(preset, "light")
    config = {"platform": platform, "hardware": profile, "noise": "off"}
    if upload_kbps:
        rec = bandwidth.recommend(upload_kbps, platform, profile)
        preset = _lighter(preset, rec.preset)
        if rec.preset == preset:
            config["bitrate"] = rec.video_kbps
    config["preset"] = cap_preset_name(profile, preset)
    return config


def save_config(path, recommended):
    """Merge recommended into the existing config file; other keys are kept."""
    current = load_file_config(path)
    current.update(recommended)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_private_text(path, json.dumps(current, indent=2) + "\n")


# Stream readiness score. Each factor earns points from a tier table of
# (minimum value, points). Factors that were not measured (no upload speed or
# no connection test) are left out of both the earned and the possible points,
# so the score is round(100 * earned / possible) over what is known.
FFMPEG_POINTS = 25
ENCODER_POINTS_HARDWARE = 20
ENCODER_POINTS_SOFTWARE = 12
RAM_TIERS_MB = ((8192, 15), (4096, 10), (2048, 5), (0, 2))
CPU_TIERS = ((8, 15), (4, 10), (2, 5), (1, 2))
UPLOAD_TIERS_MBPS = ((8, 15), (4, 10), (2, 6), (1, 3), (0, 0))
LATENCY_TIERS_MS = ((50, 10), (150, 7), (300, 3))  # (at most, points)
MAX_RAM_POINTS = RAM_TIERS_MB[0][1]
MAX_CPU_POINTS = CPU_TIERS[0][1]
MAX_UPLOAD_POINTS = UPLOAD_TIERS_MBPS[0][1]
MAX_LATENCY_POINTS = LATENCY_TIERS_MS[0][1]

ReadinessFacts = namedtuple(
    "ReadinessFacts",
    "ffmpeg_found encoder encoder_is_hardware ram_mb cpu_count upload_kbps "
    "latency_ms latency_checked",
    defaults=(None, False, None, None, None, None, False))
Factor = namedtuple("Factor", "name points max_points known detail fix")
ReadinessReport = namedtuple("ReadinessReport", "score factors")


def _tier_points(value, tiers):
    for minimum, points in tiers:
        if value >= minimum:
            return points
    return 0


def readiness_report(facts):
    """ReadinessReport from ReadinessFacts. Pure and deterministic."""
    f = []
    f.append(Factor("ffmpeg", FFMPEG_POINTS if facts.ffmpeg_found else 0, FFMPEG_POINTS,
                    True, "found" if facts.ffmpeg_found else "not found",
                    "" if facts.ffmpeg_found else
                    "Install ffmpeg and add it to PATH, or put ffmpeg next to the app."))
    if facts.encoder is None:
        f.append(Factor("encoder", 0, ENCODER_POINTS_HARDWARE, True, "no working encoder",
                        "Install ffmpeg with libx264, or update your graphics driver."))
    elif facts.encoder_is_hardware:
        f.append(Factor("encoder", ENCODER_POINTS_HARDWARE, ENCODER_POINTS_HARDWARE, True,
                        "%s (hardware)" % facts.encoder, ""))
    else:
        f.append(Factor("encoder", ENCODER_POINTS_SOFTWARE, ENCODER_POINTS_HARDWARE, True,
                        "%s (software)" % facts.encoder,
                        "A hardware encoder (NVENC, Quick Sync) would use less CPU. "
                        "Update your graphics driver if your PC has one."))
    if facts.ram_mb is None:
        f.append(Factor("memory", 0, MAX_RAM_POINTS, False, "could not be read", ""))
    else:
        pts = _tier_points(facts.ram_mb, RAM_TIERS_MB)
        f.append(Factor("memory", pts, MAX_RAM_POINTS, True, "%d MB" % facts.ram_mb,
                        "" if pts == MAX_RAM_POINTS else
                        "Close other programs while streaming. More memory helps."))
    if not facts.cpu_count:
        f.append(Factor("processor", 0, MAX_CPU_POINTS, False, "could not be read", ""))
    else:
        pts = _tier_points(facts.cpu_count, CPU_TIERS)
        f.append(Factor("processor", pts, MAX_CPU_POINTS, True,
                        "%d cores" % facts.cpu_count,
                        "" if pts == MAX_CPU_POINTS else
                        "Use the potato or light strength so the game keeps its cores."))
    if facts.upload_kbps is None:
        f.append(Factor("upload speed", 0, MAX_UPLOAD_POINTS, False,
                        "not given", "Add --upload-mbps with your upload speed."))
    else:
        mbps = facts.upload_kbps / 1000.0
        pts = _tier_points(mbps, UPLOAD_TIERS_MBPS)
        f.append(Factor("upload speed", pts, MAX_UPLOAD_POINTS, True, "%.1f Mbps" % mbps,
                        "" if pts == MAX_UPLOAD_POINTS else
                        "Use a lower bitrate (lightstream bandwidth) or a network cable."))
    if not facts.latency_checked:
        f.append(Factor("connection", 0, MAX_LATENCY_POINTS, False, "not tested",
                        "Add --platform or --url to test the connection."))
    elif facts.latency_ms is None:
        f.append(Factor("connection", 0, MAX_LATENCY_POINTS, True, "could not connect",
                        "Check your internet connection and the address."))
    else:
        pts = next((p for limit, p in LATENCY_TIERS_MS if facts.latency_ms <= limit), 0)
        f.append(Factor("connection", pts, MAX_LATENCY_POINTS, True,
                        "%.0f ms to connect" % facts.latency_ms,
                        "" if pts == MAX_LATENCY_POINTS else
                        "Move closer to the router or use a network cable."))
    possible = sum(x.max_points for x in f if x.known)
    earned = sum(x.points for x in f if x.known)
    return ReadinessReport(round(100 * earned / possible) if possible else 0, tuple(f))


def readiness_lines(report):
    """Plain text lines: the score, then each factor with points and its fix."""
    lines = ["Stream readiness: %d/100" % report.score]
    for x in report.factors:
        if x.known:
            lines.append("  %-13s %2d/%-2d  %s" % (x.name, x.points, x.max_points,
                                                    x.detail))
        else:
            lines.append("  %-13s skipped  %s" % (x.name, x.detail))
        if x.fix:
            lines.append("      fix: " + x.fix)
    lines.append("  (skipped items are left out of the score. Measured here, "
                 "not a promise for your stream.)")
    return lines


def gather_readiness_facts(os_name, cpu_count=None, ram_mb=None, upload_kbps=None,
                           ffmpeg=None, latency_target=None, run=subprocess.run,
                           find=find_ffmpeg, connect=None):
    """Probe this PC. latency_target is (host, port) or None (not tested).
    ffmpeg overrides the search. Every probe failure becomes 'not available'."""
    from .bandwidth import measure_connect_latency
    ffmpeg = ffmpeg or find()
    encoder = None
    if ffmpeg:
        try:
            available = probe_encoders(ffmpeg, run)
            encoder = choose_working_encoder(ffmpeg, available, run=run)
            if encoder == SOFTWARE_ENCODER and not encoder_works(ffmpeg, encoder, run):
                encoder = None
        except RuntimeError:
            encoder = None
    latency = None
    if latency_target:
        kwargs = {"connect": connect} if connect else {}
        latency = measure_connect_latency(*latency_target, **kwargs)
    return ReadinessFacts(
        bool(ffmpeg), encoder, bool(encoder) and encoder != SOFTWARE_ENCODER,
        ram_mb if ram_mb is not None else detect_ram_mb(os_name),
        cpu_count if cpu_count is not None else (os.cpu_count() or 0),
        upload_kbps, latency, latency_target is not None)


def platform_latency_target(platform):
    """(host, port) of a built-in platform's ingest server, or None."""
    from .bandwidth import rtmp_host_port
    url = INGEST_URLS.get(platform)
    return rtmp_host_port(url) if url else None


def run_setup(os_name, out, input_fn=input, yes=False, platform=None,
              upload_mbps=None, cpu_count=None, ram_mb=None, run=subprocess.run,
              path=None, find=find_ffmpeg):
    """Ask at most two questions (platform, upload speed), then save the config."""
    if platform is None:
        platform = "twitch"
        if not yes:
            answer = input_fn("Where do you stream? (%s) [twitch]: "
                              % "/".join(PLATFORMS)).strip().lower()
            platform = answer or platform
    if upload_mbps is None and not yes:
        answer = input_fn("Upload speed in Mbps (Enter to skip): ").strip()
        upload_mbps = answer or None
    upload_kbps = bandwidth.mbps_to_kbps(upload_mbps) if upload_mbps else None
    gpu_text = "\n".join(detect_gpu_names(os_name, run))
    cpu_count = cpu_count if cpu_count is not None else (os.cpu_count() or 0)
    ram_mb = ram_mb if ram_mb is not None else detect_ram_mb(os_name)
    config = build_recommended_config(gpu_text, cpu_count, ram_mb, upload_kbps, platform)
    path = path or config_path(os_name)
    save_config(path, config)
    out.write("Saved %s\n" % path)
    for name, value in config.items():
        out.write("  %s: %s\n" % (name, value))
    facts = gather_readiness_facts(os_name, cpu_count, ram_mb, upload_kbps,
                                   run=run, find=find)
    for line in readiness_lines(readiness_report(facts)):
        out.write(line + "\n")
    out.write("The stream key is never saved. Start with: lightstream start\n")
    return 0


# -- one-click optimize ------------------------------------------------------
# Reuses build_recommended_config, readiness and the bench tier. It only PROPOSES
# a config and a diff. Nothing is written until the person confirms.
OptimizeProposal = namedtuple("OptimizeProposal", "config diff notes readiness tier")


def config_diff(current, proposed):
    """[(key, old, new)] for keys whose value would change, sorted by key."""
    return [(k, current.get(k), v) for k, v in sorted(proposed.items())
            if current.get(k) != v]


def propose_optimization(current, gpu_text, cpu_count, ram_mb, upload_kbps,
                         platform, facts, tier=None):
    """OptimizeProposal. Pure: no file or process access.

    tier is the bench tier name or None (bench skipped). The potato fallback
    applies when the bench says Low-End, or when it was skipped and the PC has
    two or fewer CPU threads or at most LOW_RAM_MB of RAM.
    """
    config = build_recommended_config(gpu_text, cpu_count, ram_mb, upload_kbps, platform)
    weak = (cpu_count is not None and 0 < cpu_count <= 2) or \
           (ram_mb is not None and ram_mb <= LOW_RAM_MB)
    notes = []
    if tier == "Low-End" or (tier is None and weak):
        config["profile"] = "potato_2000" if (ram_mb is not None
                                              and ram_mb <= POTATO_RAM_MB) else "potato"
        notes.append("Potato fallback: lowest CPU use profile (%s)." % config["profile"])
    suggested = recommend_profile(cpu_count, ram_mb, hardware_profile=config["hardware"])
    notes.append("One-click profile for this PC: %s (use --profile %s)." % (suggested, suggested))
    report = readiness_report(facts)
    return OptimizeProposal(config, config_diff(current, config), notes,
                            report.score, tier)


def run_optimize(os_name, out, input_fn=input, yes=False, platform="twitch",
                 upload_mbps=None, cpu_count=None, ram_mb=None, run=subprocess.run,
                 path=None, find=find_ffmpeg, tier_fn=None):
    """Detect, bench (tier_fn() -> tier name or None), propose, then ask.

    Writes the config only after a typed yes (or --yes). Never touches the key.
    """
    upload_kbps = bandwidth.mbps_to_kbps(upload_mbps) if upload_mbps else None
    gpu_text = "\n".join(detect_gpu_names(os_name, run))
    cpu_count = cpu_count if cpu_count is not None else (os.cpu_count() or 0)
    ram_mb = ram_mb if ram_mb is not None else detect_ram_mb(os_name)
    path = path or config_path(os_name)
    current = load_file_config(path)
    facts = gather_readiness_facts(os_name, cpu_count, ram_mb, upload_kbps,
                                   run=run, find=find)
    tier = tier_fn() if tier_fn else None
    prop = propose_optimization(current, gpu_text, cpu_count, ram_mb, upload_kbps,
                                platform, facts, tier)
    out.write("Readiness %d/100. Bench tier: %s.\n"
              % (prop.readiness, tier or "not measured"))
    for note in prop.notes:
        out.write(note + "\n")
    if not prop.diff:
        out.write("Your config already matches. Nothing to change.\n")
        return 0
    out.write("Proposed changes to %s:\n" % path)
    for key, old, new in prop.diff:
        out.write("  %s: %s -> %s\n" % (key, old, new))
    try:
        answer = "y" if yes else input_fn("Apply these changes? [y/N]: ").strip().lower()
    except EOFError:  # no terminal to ask on: treat as "no"
        answer = ""
    if answer not in ("y", "yes"):
        out.write("Not applied. Config unchanged.\n")
        return 0
    save_config(path, prop.config)
    out.write("Applied. The stream key is never saved.\n")
    return 0
