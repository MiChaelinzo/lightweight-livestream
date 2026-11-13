"""Pick the cheapest H.264 encoder available. Probing is injectable."""

import re
import subprocess

HARDWARE_ORDER = (
    "h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox", "h264_vaapi",
)
SOFTWARE_ENCODER = "libx264"


def parse_encoders(ffmpeg_output):
    """Extract encoder names from `ffmpeg -encoders` text."""
    names = set()
    for line in ffmpeg_output.splitlines():
        m = re.match(r"^\s*V[\w.]{5}\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return names


def choose_encoder(available, prefer_hardware=True, forced=None):
    if forced:
        return forced
    if prefer_hardware:
        for name in HARDWARE_ORDER:
            if name in available:
                return name
    return SOFTWARE_ENCODER


def probe_encoders(ffmpeg="ffmpeg", run=subprocess.run):
    """Return the set of encoders ffmpeg reports. Raises RuntimeError on failure."""
    try:
        result = run([ffmpeg, "-hide_banner", "-encoders"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     universal_newlines=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not run %s: %s" % (ffmpeg, exc))
    return parse_encoders(result.stdout)
