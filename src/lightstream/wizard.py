"""One-click setup: pick safe low-resource settings for this PC.

build_recommended_config is pure. The stream key is never asked for or saved.
"""

import json
import os
import subprocess

from . import bandwidth
from .config import config_path, load_file_config
from .gui_controller import suggest_strength
from .hardware import (cap_preset_name, classify_gpus, detect_gpu_names,
                       parse_gpu_names)
from .platforms import PLATFORMS
from .presets import PRESETS

LOW_RAM_MB = 4096  # at or below this, never start above the 'light' preset


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
    config = {"platform": platform, "hardware": profile, "noise": "light"}
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
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2)
        fh.write("\n")


def run_setup(os_name, out, input_fn=input, yes=False, platform=None,
              upload_mbps=None, cpu_count=None, ram_mb=None, run=subprocess.run,
              path=None):
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
    out.write("The stream key is never saved. Start with: lightstream start\n")
    return 0
