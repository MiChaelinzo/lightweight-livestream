"""GPU detection and low-resource tuning per hardware profile. Pure parsing.

Everything here describes mechanisms (smaller buffers, fewer threads, no
lookahead). No speed or memory numbers are claimed; real FFmpeg behavior on
Intel HD / MX250 machines is UNVERIFIED until tested on that hardware.
"""

import re
import subprocess
from collections import namedtuple

from .presets import PRESETS

HardwareProfile = namedtuple(
    "HardwareProfile", "name encoder_order max_preset x264_threads description")

PROFILES = {
    p.name: p
    for p in (
        HardwareProfile("intel_hd", ("h264_qsv",), "light", 2,
                        "Intel HD/UHD graphics: Quick Sync, preset capped at light."),
        HardwareProfile("nvidia_mx", ("h264_nvenc", "h264_qsv"), None, 2,
                        "NVIDIA MX series laptop GPU: NVENC, Quick Sync fallback."),
        HardwareProfile("nvidia", ("h264_nvenc",), None, 2, "NVIDIA GPU: NVENC."),
        HardwareProfile("generic", ("h264_nvenc", "h264_qsv", "h264_amf",
                                    "h264_videotoolbox", "h264_vaapi"), None, 2,
                        "Unknown GPU: low-resource settings, default encoder order."),
    )
}

_LSPCI_LINE = re.compile(
    r"(?:VGA compatible controller|3D controller|Display controller):\s*(.+)$")
_MX_SERIES = re.compile(r"\bMX\s*\d{3}", re.IGNORECASE)
_INTEL_GRAPHICS = re.compile(r"intel.*(graphics|iris)", re.IGNORECASE)

INPUT_PROBESIZE = "32k"
INPUT_RTBUFSIZE = "16M"
INPUT_THREAD_QUEUE = "32"


def get_profile(name):
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError("Unknown hardware profile %r. Choose one of: %s"
                         % (name, ", ".join(PROFILES)))


def parse_gpu_names(text):
    """GPU names from `wmic path win32_VideoController get name` (Windows) or
    `lspci` (Linux) text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    pci = [m.group(1) for m in (_LSPCI_LINE.search(l) for l in lines) if m]
    if pci:
        return pci
    return [l for l in lines if l.lower() != "name"]


def classify_gpus(names):
    """Profile name for the best GPU: NVIDIA MX, NVIDIA, Intel HD, else generic."""
    joined = [n for n in names if n]
    nvidia = [n for n in joined if "nvidia" in n.lower()]
    if any(_MX_SERIES.search(n) for n in nvidia):
        return "nvidia_mx"
    if nvidia:
        return "nvidia"
    if any(_INTEL_GRAPHICS.search(n) for n in joined):
        return "intel_hd"
    return "generic"


def detect_gpu_names(os_name, run=subprocess.run):
    """Ask the OS for GPU names. Empty list when the tool is missing or fails."""
    if os_name == "windows":
        cmd = ["wmic", "path", "win32_VideoController", "get", "name"]
    elif os_name == "linux":
        cmd = ["lspci"]
    else:
        return []
    try:
        result = run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                     universal_newlines=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_gpu_names(result.stdout or "")


def cap_preset_name(profile_name, preset_name, forced=False):
    """Intel HD profile caps heavy presets at 'light' unless the user forced one."""
    cap = get_profile(profile_name).max_preset
    if forced or cap is None:
        return preset_name
    order = list(PRESETS)
    if order.index(preset_name) > order.index(cap):
        return cap
    return preset_name


def tuned_encoder_args(profile_name, encoder):
    """Encoder args tuned for the profile, or None to use the default args."""
    if encoder == "h264_qsv" and profile_name == "intel_hd":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-look_ahead", "0",
                "-async_depth", "1"]
    if encoder == "h264_nvenc" and profile_name in ("nvidia_mx", "nvidia"):
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "cbr",
                "-rc-lookahead", "0", "-surfaces", "4", "-pix_fmt", "yuv420p"]
    return None


def low_resource_input_args(args):
    """Capture args with smaller probe and capture buffers (less RAM, faster
    start). Input options must sit right before their own -i."""
    smaller = {"-rtbufsize": INPUT_RTBUFSIZE, "-thread_queue_size": INPUT_THREAD_QUEUE}
    out = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in smaller and i + 1 < len(args):
            out += [token, smaller[token]]
            i += 2
            continue
        if token == "-i":
            out += ["-probesize", INPUT_PROBESIZE, "-analyzeduration", "0"]
        out.append(token)
        i += 1
    return out


def low_resource_output_args(profile_name, encoder, complex_graph):
    """Fewer threads and the cheapest scaler. -threads applies to libx264 only."""
    graph_threads = "-filter_complex_threads" if complex_graph else "-filter_threads"
    args = [graph_threads, "1", "-sws_flags", "fast_bilinear"]
    if encoder == "libx264":
        args += ["-threads", str(get_profile(profile_name).x264_threads)]
    return args
