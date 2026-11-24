"""Congestion detection and network intelligence from signals that exist.

Inputs are the numbers ffmpeg already prints (speed, dup, drop, bitrate), the
output URL scheme and, best effort, the kind of network link. Nothing here
changes a setting. Findings are advice for the person and the session report.

Packet loss: only SRT and UDP can report it, and LightStream does not read SRT
statistics yet (Roadmap). RTMP runs over TCP, which hides loss as delay, so
for RTMP the honest signal is backpressure: ffmpeg falls behind real time
while the encoder is not the limit. A congestion finding is an inference.

Link probes (Linux /sys and /proc, `netsh` on Windows, `networksetup` on
macOS) degrade to "n/a" when a command or file is missing. The parsers are
tested with fake text only. Running the Windows and macOS probes (and the Linux
one on real Wi-Fi) is UNVERIFIED. Hotspot detection is a hint from well known
tethering gateway addresses, not proof.
"""

import os
import subprocess
from collections import namedtuple

from .platforms import is_srt_url

KIND_RTMP = "rtmp"
KIND_SRT = "srt"
KIND_UDP = "udp"
LINK_WIFI = "wifi"
LINK_ETHERNET = "ethernet"
LINK_UNKNOWN = "n/a"

BACKPRESSURE_BELOW_SPEED = 0.95
CPU_BUSY_PERCENT = 90            # at or above this, slow speed is blamed on the CPU
LOW_BITRATE_RATIO = 0.6          # recent bitrate under this share of target
DUP_RATE_WARNING = 0.05          # dup frames per frame sent
SPEED_JITTER_WARNING = 0.08      # stdev of ffmpeg speed that suggests an unstable link
UNSTABLE_RECONNECTS = 2
HOTSPOT_GATEWAYS = ("192.168.43.1", "172.20.10.1", "192.168.137.1")  # Android, iOS, Windows ICS

Congestion = namedtuple("Congestion", "kind message")
LinkInfo = namedtuple("LinkInfo", "kind hotspot_hint note")


def output_kind(url):
    """rtmp, srt or udp for an ingest URL (rtmps counts as rtmp)."""
    url = (url or "").lower()
    if is_srt_url(url):
        return KIND_SRT
    if url.startswith("udp://"):
        return KIND_UDP
    return KIND_RTMP


def packet_loss_reportable(kind):
    """True only for transports that count lost packets."""
    return kind in (KIND_SRT, KIND_UDP)


def detect_congestion(summary, target_kbps, kind=KIND_RTMP, cpu_percent=None):
    """List of Congestion findings from a HealthTracker.summary() dict.

    Backpressure needs low speed while the CPU is not saturated, otherwise slow
    speed is blamed on the encoder. Returns [] when speed is unknown.
    """
    found = []
    speed = summary.get("recent_speed")
    bitrate = summary.get("recent_bitrate_kbps")
    if speed is None:
        return found
    cpu_busy = cpu_percent is not None and cpu_percent >= CPU_BUSY_PERCENT
    if speed < BACKPRESSURE_BELOW_SPEED and not cpu_busy:
        if kind == KIND_RTMP:
            found.append(Congestion(
                "backpressure",
                "ffmpeg runs at %.2fx while the CPU is not full: the server or "
                "uplink is not accepting data fast enough (RTMP shows this as "
                "backpressure, not as packet loss)." % speed))
        else:
            found.append(Congestion(
                "slow_output", "ffmpeg runs at %.2fx while the CPU is not full; "
                "the link may be congested." % speed))
    if (target_kbps and bitrate is not None and speed >= BACKPRESSURE_BELOW_SPEED
            and bitrate < target_kbps * LOW_BITRATE_RATIO):
        found.append(Congestion(
            "bitrate_below_target",
            "Output bitrate (%.0f kbps) is well under the %d kbps target while "
            "encoding keeps up. The picture may simply be simple, or the network "
            "limits it." % (bitrate, target_kbps)))
    frames = max(summary.get("samples") or 0, 1) * max(summary.get("recent_fps") or 0, 1)
    if summary.get("dup_frames") and summary["dup_frames"] / frames > DUP_RATE_WARNING:
        found.append(Congestion(
            "duplicated_frames", "ffmpeg repeated frames to keep the frame rate, "
            "which means input or output stalled."))
    if packet_loss_reportable(kind):
        found.append(Congestion(
            "loss_not_read", "%s can report packet loss but LightStream does not "
            "read it yet (Roadmap)." % kind.upper()))
    return found


def speed_jitter(speeds):
    """Population standard deviation of ffmpeg speed readings (0.0 if < 2)."""
    if len(speeds) < 2:
        return 0.0
    mean = sum(speeds) / len(speeds)
    return (sum((v - mean) ** 2 for v in speeds) / len(speeds)) ** 0.5


def link_advice(link, speeds, reconnects):
    """Advice lines. Wi-Fi instability needs a Wi-Fi link and a real signal:
    jittery speed or repeated reconnects."""
    lines = []
    jitter = speed_jitter(speeds)
    unstable = jitter >= SPEED_JITTER_WARNING or reconnects >= UNSTABLE_RECONNECTS
    if link.kind == LINK_WIFI and unstable:
        lines.append("The stream is unstable on Wi-Fi (speed jitter %.2f, %d "
                     "reconnects). A network cable is the usual fix; otherwise move "
                     "closer to the router or lower the bitrate." % (jitter, reconnects))
    if link.hotspot_hint:
        lines.append("This looks like a phone hotspot (%s). Hotspots often have a "
                     "weak, changing signal: try --weak-connection or a lower "
                     "bitrate." % link.note)
    return lines


# ---- link probes -------------------------------------------------------

def default_route_interface(route_text):
    """Interface of the default route from /proc/net/route text, or None."""
    for line in route_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 8 and fields[1] == "00000000":
            return fields[0]
    return None


def default_gateway(route_text):
    """Default gateway IPv4 string from /proc/net/route text, or None."""
    for line in route_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "00000000":
            try:
                raw = int(fields[2], 16)
            except ValueError:
                return None
            return ".".join(str((raw >> shift) & 255) for shift in (0, 8, 16, 24))
    return None


def probe_linux(read=None, exists=os.path.exists):
    """LinkInfo from /proc/net/route and /sys/class/net/<iface>/wireless."""
    def default_read(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    read = read or default_read
    try:
        route = read("/proc/net/route")
    except OSError:
        return LinkInfo(LINK_UNKNOWN, False, "no route table")
    iface = default_route_interface(route)
    if not iface:
        return LinkInfo(LINK_UNKNOWN, False, "no default route")
    gateway = default_gateway(route)
    wireless = exists("/sys/class/net/%s/wireless" % iface)
    kind = LINK_WIFI if wireless else LINK_ETHERNET
    hotspot = wireless and gateway in HOTSPOT_GATEWAYS
    return LinkInfo(kind, hotspot, "gateway %s" % gateway if hotspot else iface)


def parse_netsh_wlan(text):
    """LinkInfo from `netsh wlan show interfaces` text (Windows)."""
    state = None
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "state":
            state = value.strip().lower()
    if state == "connected":
        return LinkInfo(LINK_WIFI, False, "netsh: connected")
    return LinkInfo(LINK_UNKNOWN, False, "netsh: no Wi-Fi connection")


def parse_networksetup(text):
    """LinkInfo from `networksetup -getairportnetwork en0` text (macOS)."""
    if "current wi-fi network:" in text.lower():
        return LinkInfo(LINK_WIFI, False, "networksetup: connected")
    return LinkInfo(LINK_UNKNOWN, False, "networksetup: no Wi-Fi network")


def detect_link(os_name, run=subprocess.run, read=None, exists=os.path.exists):
    """Best effort link kind. Never raises; n/a on any failure."""
    try:
        if os_name == "linux":
            return probe_linux(read, exists)
        if os_name == "windows":
            result = run(["netsh", "wlan", "show", "interfaces"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, universal_newlines=True, timeout=5)
            return parse_netsh_wlan(result.stdout or "")
        if os_name == "macos":
            result = run(["networksetup", "-getairportnetwork", "en0"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         universal_newlines=True, timeout=5)
            return parse_networksetup(result.stdout or "")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return LinkInfo(LINK_UNKNOWN, False, "probe failed")
