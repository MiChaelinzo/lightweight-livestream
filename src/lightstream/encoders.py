"""Pick the cheapest H.264 encoder available. Probing is injectable."""

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

HARDWARE_ORDER = (
    "h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox", "h264_vaapi",
)
SOFTWARE_ENCODER = "libx264"
PROBE_TIMEOUT_SECONDS = 8
_WORKS_CACHE = {}  # (ffmpeg, encoder) -> bool, for this run only


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


def _test_args(ffmpeg, encoder):
    args = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if encoder == "h264_vaapi":
        args += ["-vaapi_device", "/dev/dri/renderD128"]
    args += ["-f", "lavfi", "-i", "testsrc=size=256x144:rate=5"]
    if encoder == "h264_vaapi":
        args += ["-vf", "format=nv12,hwupload"]
    return args + ["-frames:v", "2", "-c:v", encoder, "-f", "null", "-"]


def encoder_works(ffmpeg, encoder, run=subprocess.run):
    """True if a tiny test encode succeeds. `-encoders` only lists compiled-in
    support, not what this machine's GPU can actually do. Cached per run."""
    cache_key = (ffmpeg, encoder)
    if cache_key not in _WORKS_CACHE:
        try:
            result = run(_test_args(ffmpeg, encoder), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, timeout=PROBE_TIMEOUT_SECONDS)
            _WORKS_CACHE[cache_key] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _WORKS_CACHE[cache_key] = False
    return _WORKS_CACHE[cache_key]


def choose_working_encoder(ffmpeg, available, prefer_hardware=True, forced=None,
                           run=subprocess.run):
    """Like choose_encoder, but skips hardware encoders that fail a test encode."""
    if forced or not prefer_hardware:
        return choose_encoder(available, prefer_hardware, forced)
    candidates = [n for n in HARDWARE_ORDER if n in available]
    if not candidates:
        return SOFTWARE_ENCODER
    # Test all at once so startup waits for the slowest probe, not the sum.
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        results = list(pool.map(lambda n: encoder_works(ffmpeg, n, run), candidates))
    for name, works in zip(candidates, results):
        if works:
            return name
    return SOFTWARE_ENCODER


def probe_encoders(ffmpeg="ffmpeg", run=subprocess.run):
    """Return the set of encoders ffmpeg reports. Raises RuntimeError on failure."""
    try:
        result = run([ffmpeg, "-hide_banner", "-encoders"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     universal_newlines=True,
                     timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not run %s: %s" % (ffmpeg, exc))
    return parse_encoders(result.stdout)
