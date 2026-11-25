"""Pick a preset and bitrate that fits the upload speed.

The upload speed is either typed in (--upload-mbps) or measured by posting
bytes to an endpoint the user supplies. No third-party endpoint is built in.
"""

import socket
import time
import urllib.parse
import urllib.request
from collections import namedtuple

from .hardware import cap_preset_name
from .presets import PRESETS

HEADROOM = 0.7  # use at most 70% of upload so bursts and Wi-Fi dips fit
MIN_VIDEO_KBPS = 300
PLATFORM_VIDEO_CAP_KBPS = {"twitch": 6000, "youtube": 9000, "custom": 6000}
MEASURE_BYTES = 1024 * 1024
MEASURE_TIMEOUT_SECONDS = 20

Recommendation = namedtuple("Recommendation", "preset video_kbps audio_kbps usable_kbps")


def recommend(upload_kbps, platform, hardware_profile=None):
    """Best preset whose video + audio fit in HEADROOM of upload_kbps.

    video_kbps never exceeds the preset's own bitrate or the platform cap.
    When even potato does not fit, potato is returned with a reduced bitrate.
    """
    if not upload_kbps or upload_kbps <= 0:
        raise ValueError("Upload speed must be greater than 0 kbps, got %r" % upload_kbps)
    cap = PLATFORM_VIDEO_CAP_KBPS.get(platform)
    if cap is None:
        raise ValueError("Unknown platform %r. Choose one of: %s"
                         % (platform, ", ".join(PLATFORM_VIDEO_CAP_KBPS)))
    usable = int(upload_kbps * HEADROOM)
    chosen = None
    for preset in PRESETS.values():  # ordered lightest to heaviest
        if min(preset.video_kbps, cap) + preset.audio_kbps <= usable:
            chosen = preset
    if chosen is None:
        chosen = PRESETS["potato"]
    name = chosen.name
    if hardware_profile:
        name = cap_preset_name(hardware_profile, name)
    preset = PRESETS[name]
    video = min(preset.video_kbps, cap, max(usable - preset.audio_kbps, MIN_VIDEO_KBPS))
    return Recommendation(name, video, preset.audio_kbps, usable)


def mbps_to_kbps(mbps):
    try:
        value = float(mbps)
    except (TypeError, ValueError):
        raise ValueError("Upload speed must be a number in Mbps, got %r" % (mbps,))
    if value <= 0:
        raise ValueError("Upload speed must be greater than 0 Mbps, got %r" % (mbps,))
    return value * 1000


def _urlopen_post(url, data):
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=MEASURE_TIMEOUT_SECONDS) as response:
        response.read(1)


def measure_upload(endpoint, post=_urlopen_post, clock=time.monotonic,
                   payload_bytes=MEASURE_BYTES):
    """Upload kbps from timing one POST of payload_bytes to endpoint."""
    if not endpoint:
        raise ValueError("Pass a speed test URL you control (--measure-url), "
                         "or give your upload speed with --upload-mbps.")
    if not endpoint.lower().startswith(("http://", "https://")):
        raise ValueError("Speed test URL must start with http:// or https://")
    started = clock()
    post(endpoint, b"\0" * payload_bytes)
    elapsed = clock() - started
    if elapsed <= 0:
        raise ValueError("Speed test finished too fast to measure. Use --upload-mbps.")
    return payload_bytes * 8 / 1000 / elapsed


DEFAULT_PORTS = {"rtmp": 1935, "rtmps": 443}
LATENCY_TIMEOUT_SECONDS = 3


def rtmp_host_port(url):
    """(host, port) of an rtmp:// or rtmps:// URL. The path (where the stream
    key lives) is dropped here so callers never see or log it."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme not in DEFAULT_PORTS or not parts.hostname:
        raise ValueError("Need an rtmp:// or rtmps:// address to test the connection")
    return parts.hostname, parts.port or DEFAULT_PORTS[parts.scheme]


def measure_connect_latency(host, port, connect=socket.create_connection,
                            clock=time.monotonic, timeout=LATENCY_TIMEOUT_SECONDS):
    """Milliseconds to open a TCP connection to host:port, or None on failure.

    This is connection setup time, a rough hint about distance and congestion.
    It is not packet loss and not stream latency."""
    started = clock()
    try:
        sock = connect((host, port), timeout)
    except OSError:
        return None
    elapsed = clock() - started
    try:
        sock.close()
    except OSError:
        pass
    return elapsed * 1000.0
