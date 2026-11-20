"""GPU detection and low-resource tuning per hardware profile. Pure parsing.

Everything here describes mechanisms (smaller probe, fewer threads, no
lookahead). No speed or memory numbers are claimed; real FFmpeg behavior on
Intel HD / MX250 machines is UNVERIFIED until tested on that hardware.
"""

import re
import subprocess
from collections import namedtuple

from .presets import PRESETS

DEFAULT_BUFSIZE_SECONDS = 1.0
LEAN_BUFSIZE_SECONDS = 0.5      # half a second of rate-control buffer: less delay
INTEL_HD_WEBCAM_MAX_FPS = 10    # fewer webcam frames to scale and overlay
MX250_MAX_VIDEO_KBPS = 4500     # moderate 1080p30 bitrate, fits most uploads

HardwareProfile = namedtuple(
    "HardwareProfile",
    "name encoder_order max_preset x264_threads description "
    "webcam_max_fps strip_expensive_filters bufsize_seconds allow_ai_audio "
    "record_by_default max_video_kbps",
    defaults=(None, False, DEFAULT_BUFSIZE_SECONDS, True, False, None),
)

PROFILES = {
    p.name: p
    for p in (
        HardwareProfile("intel_hd", ("h264_qsv", "h264_vaapi"), "light", 2,
                        "Intel HD/UHD graphics: Quick Sync, then VAAPI, preset capped at light."),
        HardwareProfile("intel_hd_optimized", ("h264_qsv", "h264_vaapi"), "light", 2,
                        "Intel HD 4000/520/620: light preset, small buffer, webcam capped, "
                        "no blur/chromakey, AI audio off.",
                        webcam_max_fps=INTEL_HD_WEBCAM_MAX_FPS,
                        strip_expensive_filters=True,
                        bufsize_seconds=LEAN_BUFSIZE_SECONDS,
                        allow_ai_audio=False),
        HardwareProfile("mx250_streamer", ("h264_nvenc", "h264_qsv"), None, 2,
                        "GeForce MX250 laptops: NVENC first, webcam overlay allowed, "
                        "local recording on, moderate bitrate for 1080p.",
                        record_by_default=True,
                        max_video_kbps=MX250_MAX_VIDEO_KBPS),
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
_MX250 = re.compile(r"\bMX\s*250\b", re.IGNORECASE)
_INTEL_HD_OPTIMIZED = re.compile(r"\bU?HD\s+Graphics\s+(4000|520|620)\b", re.IGNORECASE)
_INTEL_GRAPHICS = re.compile(r"intel.*(graphics|iris)", re.IGNORECASE)

INPUT_PROBESIZE = "32k"


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
    """Profile name for the best GPU: MX250, NVIDIA MX, NVIDIA, Intel HD 4000/520/620,
    other Intel graphics, else generic."""
    joined = [n for n in names if n]
    nvidia = [n for n in joined if "nvidia" in n.lower()]
    if any(_MX250.search(n) for n in nvidia):
        return "mx250_streamer"
    if any(_MX_SERIES.search(n) for n in nvidia):
        return "nvidia_mx"
    if nvidia:
        return "nvidia"
    if any(_INTEL_HD_OPTIMIZED.search(n) for n in joined):
        return "intel_hd_optimized"
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
    if encoder == "h264_qsv" and profile_name in ("intel_hd", "intel_hd_optimized"):
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-look_ahead", "0",
                "-async_depth", "1"]
    if encoder == "h264_nvenc" and profile_name in (
            "nvidia_mx", "nvidia", "mx250_streamer"):
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "cbr",
                "-rc-lookahead", "0", "-surfaces", "4", "-pix_fmt", "yuv420p"]
    return None


def low_resource_input_args(args):
    """Capture args with a smaller probe (faster start). Capture buffers are
    left alone: a 1080p BGRA frame is about 8 MB, so shrinking -rtbufsize risks
    dropped frames. Input options must sit right before their own -i."""
    out = []
    i = 0
    while i < len(args):
        token = args[i]
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


def rate_control_bufsize_kbps(profile_name, video_kbps):
    """-bufsize in kbit: video_kbps times the profile's buffer seconds."""
    seconds = get_profile(profile_name).bufsize_seconds if profile_name else DEFAULT_BUFSIZE_SECONDS
    return max(1, int(video_kbps * seconds))


def cap_video_kbps(profile_name, video_kbps):
    """Moderate-bitrate cap for profiles that define one (MX250)."""
    cap = get_profile(profile_name).max_video_kbps
    return video_kbps if cap is None else min(video_kbps, cap)
