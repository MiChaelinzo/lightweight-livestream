"""Evidence spikes for v0.12: measure with the local ffmpeg before building.

    python3 tools/spikes.py --all --ffmpeg /path/to/ffmpeg
    python3 tools/spikes.py --spike a --spike c --repeats 3 --out spikes.json

Spikes (all traffic stays on 127.0.0.1; no network beyond loopback):

    a  split publisher: encoder -> MPEG-TS over UDP -> long-lived `-c copy`
       publisher -> RTMP loopback listener; encoder killed and restarted
    b  tee onfail=ignore with the RTMP server killed; recording containers
       after kill -9; numbered recording files across a reconnect
    c  potato filters and x264 CBR: CPU seconds and bitrate
    d  SRT loopback and the options libsrt exposes in this build
    e  audio chains: CPU seconds of every audio profile chain (light and full)
       on a synthetic sine plus noise input, against a no-filter baseline
    f  runtime bitrate change: which filters can carry commands (sendcmd, zmq),
       what they can target, and whether any encoder in this build changes its
       bitrate mid-stream when commanded (output bitrate before and after)
    g  overlay cost at 720p30: per-frame drawtext clock vs a pre-rendered PNG
       input (-loop 1 -framerate 1) vs a 30 fps changing overlay, and
       mpdecimate on moving and static pictures

Only JSON goes to stdout. The pure helpers at the top (framecrc parsing,
packet analysis, /proc parsing, summaries) are unit tested in
tests/test_spikes.py; the process orchestration below them is exercised only by
running this tool, and its numbers are described in docs/BENCHMARKS.md.

CPU is user plus system time from os.wait4 for each ffmpeg child. psutil is not
used. Memory is the child's peak RSS from the same call.
"""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lightstream.audio import AUDIO_CHAINS, AUDIO_PROFILES, audio_profile_chain  # noqa: E402
from lightstream.command import build_command, numbered_recording_path  # noqa: E402

LOOPBACK = "127.0.0.1"
SPIKE_NAMES = ("a", "b", "c", "d", "e", "f", "g")


# ---------------------------------------------------------------- pure helpers

def parse_framecrc(text):
    """Parse `-f framecrc` output.

    Returns (timebases, packets). timebases maps stream index to (num, den).
    packets is a list of dicts: stream, dts, pts, duration, size. Lines that do
    not match (comments, blanks) are skipped; "NOPTS" becomes None.
    """
    timebases = {}
    packets = []
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r"#tb\s+(\d+):\s*(\d+)/(\d+)", line)
        if match:
            timebases[int(match.group(1))] = (int(match.group(2)),
                                              int(match.group(3)))
            continue
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            packets.append({
                "stream": int(parts[0]),
                "dts": None if parts[1] == "NOPTS" else int(parts[1]),
                "pts": None if parts[2] == "NOPTS" else int(parts[2]),
                "duration": int(parts[3]),
                "size": int(parts[4]),
            })
        except ValueError:
            continue
    return timebases, packets


def analyze_packets(packets, timebase, stream=0, gap_ms=500):
    """Timestamp continuity of one stream.

    non_monotonic counts packets whose dts is not greater than the previous
    one. forward_gaps lists jumps of at least gap_ms (milliseconds, in the
    stream's timebase). span_ms is last dts minus first dts.
    """
    num, den = timebase
    to_ms = 1000.0 * num / den
    dts = [p["dts"] for p in packets
           if p["stream"] == stream and p["dts"] is not None]
    result = {"packets": len(dts), "non_monotonic": 0, "forward_gaps_ms": [],
              "backward_jumps_ms": [], "span_ms": 0.0, "first_dts_ms": None}
    if not dts:
        return result
    result["first_dts_ms"] = round(dts[0] * to_ms, 1)
    result["span_ms"] = round((dts[-1] - dts[0]) * to_ms, 1)
    for prev, cur in zip(dts, dts[1:]):
        delta_ms = (cur - prev) * to_ms
        if cur <= prev:
            result["non_monotonic"] += 1
            if delta_ms < 0:
                result["backward_jumps_ms"].append(round(delta_ms, 1))
        elif delta_ms >= gap_ms:
            result["forward_gaps_ms"].append(round(delta_ms, 1))
    return result


def frame_size_histogram(packets, stream=0):
    """Count decoded raw frames per byte size (rawvideo framecrc). Different
    sizes mean different resolutions reached the decoder output."""
    counts = {}
    for p in packets:
        if p["stream"] == stream:
            counts[p["size"]] = counts.get(p["size"], 0) + 1
    return counts


def yuv420_dimensions(size_bytes, candidates):
    """Pick the (w, h) from candidates whose yuv420p frame has size_bytes."""
    for w, h in candidates:
        if w * h * 3 // 2 == size_bytes:
            return (w, h)
    return None


def tcp_listening_ports(proc_net_tcp_text):
    """Ports in LISTEN state from the text of /proc/net/tcp."""
    ports = set()
    for line in proc_net_tcp_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) > 3 and fields[3] == "0A":
            try:
                ports.add(int(fields[1].split(":")[1], 16))
            except (IndexError, ValueError):
                continue
    return ports


def count_matches(text, patterns):
    """Case-insensitive count of lines containing any of the patterns."""
    lowered = [p.lower() for p in patterns]
    total = 0
    for line in text.splitlines():
        low = line.lower()
        if any(p in low for p in lowered):
            total += 1
    return total


def parse_protocol_options(help_text):
    """Option names from `ffmpeg -h protocol=NAME` (lines like `  -latency  <int64> ...`)."""
    names = []
    for line in help_text.splitlines():
        match = re.match(r"\s+-([a-z_0-9]+)\s+<", line)
        if match:
            names.append(match.group(1))
    return names


def summarize(values):
    """median, min, max, n of a list of numbers; None values are skipped."""
    nums = sorted(v for v in values if v is not None)
    if not nums:
        return {"n": 0, "median": None, "min": None, "max": None}
    mid = len(nums) // 2
    median = nums[mid] if len(nums) % 2 else (nums[mid - 1] + nums[mid]) / 2.0
    return {"n": len(nums), "median": round(median, 3),
            "min": round(nums[0], 3), "max": round(nums[-1], 3)}


def parse_filter_names(filters_text):
    """Filter names from `ffmpeg -filters` (rows like ` T.. name  V->V  text`)."""
    names = set()
    for line in filters_text.splitlines():
        match = re.match(r"^\s([TSC.]{3})\s+(\S+)\s+\S+->\S+\s", line)
        if match:
            names.add(match.group(2))
    return names


def parse_video_encoder_names(encoders_text):
    """Video encoder names from `ffmpeg -encoders` (rows like ` V....D libx264  text`)."""
    names = []
    for line in encoders_text.splitlines():
        match = re.match(r"^\s(V[.FSXBD]{5})\s+(\S+)\s", line)
        if match:
            names.append(match.group(2))
    return names


def half_bitrates(packets, timebase, split_ms, stream=0):
    """Bitrate in kbit/s of the packets before and after `split_ms` (by pts).

    Each half uses the span from its first to the end of its last packet's
    window, so a short stream still gives a rate. A half with no packets is None.
    """
    num, den = timebase
    to_ms = 1000.0 * num / den
    halves = ([], [])
    for packet in packets:
        if packet["stream"] != stream or packet["pts"] is None:
            continue
        halves[0 if packet["pts"] * to_ms < split_ms else 1].append(packet)
    rates = []
    for index, half in enumerate(halves):
        if not half:
            rates.append(None)
            continue
        start = split_ms if index else 0.0
        end = max((p["pts"] + p["duration"]) * to_ms for p in half)
        rates.append(bitrate_kbps(sum(p["size"] for p in half), (end - start) / 1000.0))
    return tuple(rates)


def bitrate_kbps(size_bytes, seconds):
    if seconds <= 0:
        return None
    return round(size_bytes * 8 / 1000.0 / seconds, 1)


def cpu_seconds(rusage):
    return rusage.ru_utime + rusage.ru_stime


# ----------------------------------------------------------- process plumbing

def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind((LOOPBACK, 0))
        return s.getsockname()[1]


def wait_tcp_listening(port, timeout=5.0, read=None):
    """Poll /proc/net/tcp until port is in LISTEN state (no connect, so the
    one-shot ffmpeg listener is not consumed)."""
    def default_read():
        with open("/proc/net/tcp", encoding="utf-8") as f:
            return f.read()
    read = read or default_read
    end = time.time() + timeout
    while time.time() < end:
        if port in tcp_listening_ports(read()):
            return True
        time.sleep(0.05)
    return False


class Proc(object):
    """One ffmpeg child with its stderr in a temp file and rusage on exit."""

    def __init__(self, argv, workdir, name):
        self.name = name
        self.log_path = os.path.join(workdir, "%s.log" % name)
        self._log = open(self.log_path, "wb")
        self.popen = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                      stdout=subprocess.DEVNULL,
                                      stderr=self._log)
        self.started = time.time()
        self.rusage = None
        self.status = None
        self.ended = None

    def alive(self):
        return self.status is None and self.popen.poll() is None and \
            self._poll() is None

    def _poll(self):
        if self.status is not None:
            return self.status
        try:
            pid, status, ru = os.wait4(self.popen.pid, os.WNOHANG)
        except ChildProcessError:
            self.status = -1
            self.ended = time.time()
            return self.status
        if pid:
            self._finish(status, ru)
            return self.status
        return None

    def _finish(self, status, ru):
        self.status = os.waitstatus_to_exitcode(status)
        self.rusage = ru
        self.ended = time.time()
        self._log.close()

    def wait(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if self._poll() is not None:
                return True
            time.sleep(0.05)
        return False

    def stop(self, timeout=5.0):
        """Graceful: 'q' on stdin, then SIGKILL if it does not exit."""
        if self.status is None:
            try:
                self.popen.stdin.write(b"q")
                self.popen.stdin.flush()
            except (OSError, ValueError):
                pass
            if not self.wait(timeout):
                self.kill()
        self._close_stdin()

    def kill(self):
        """SIGKILL, as a crash or `kill -9` would."""
        if self.status is None:
            try:
                self.popen.send_signal(signal.SIGKILL)
            except OSError:
                pass
            self.wait(5.0)
        self._close_stdin()

    def _close_stdin(self):
        try:
            self.popen.stdin.close()
        except (OSError, ValueError):
            pass

    def log_text(self):
        try:
            with open(self.log_path, "r", encoding="utf-8",
                      errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def cpu(self):
        return None if self.rusage is None else round(cpu_seconds(self.rusage), 3)

    def rss_mb(self):
        return None if self.rusage is None else round(self.rusage.ru_maxrss / 1024.0, 1)


def run_to_end(argv, timeout=120):
    """Run a short ffmpeg to completion. Returns (returncode, stdout, stderr)."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out.decode("utf-8", "replace"), \
        err.decode("utf-8", "replace")


def timed_run(argv, timeout=180):
    """Run to completion and return (returncode, wall_s, cpu_s, rss_mb, stderr)."""
    with tempfile.TemporaryFile() as err:
        start = time.time()
        popen = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=err)
        deadline = start + timeout
        while True:
            pid, status, ru = os.wait4(popen.pid, os.WNOHANG)
            if pid:
                break
            if time.time() > deadline:
                popen.kill()
                pid, status, ru = os.wait4(popen.pid, 0)
                break
            time.sleep(0.02)
        wall = time.time() - start
        err.seek(0)
        text = err.read().decode("utf-8", "replace")
    return (os.waitstatus_to_exitcode(status), round(wall, 2),
            round(cpu_seconds(ru), 3), round(ru.ru_maxrss / 1024.0, 1), text)


def source_args(width, height, fps, kind="testsrc2", paced=True):
    args = []
    if paced:
        args += ["-re"]
    args += ["-f", "lavfi", "-i", "%s=size=%dx%d:rate=%d" % (kind, width, height, fps)]
    return args


def x264_args(bitrate_k, fps, threads=2):
    return ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-threads", str(threads), "-g", str(fps), "-bf", "0",
            "-b:v", "%dk" % bitrate_k, "-maxrate", "%dk" % bitrate_k,
            "-bufsize", "%dk" % bitrate_k, "-pix_fmt", "yuv420p", "-an"]


def framecrc_of(ffmpeg, path, extra_out=None):
    """(ok, timebases, packets, stderr) for a file read with -c copy -f framecrc."""
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "error", "-i", path] + \
        (extra_out or ["-c", "copy"]) + ["-f", "framecrc", "-"]
    code, out, err = run_to_end(argv)
    timebases, packets = parse_framecrc(out)
    return code == 0 and bool(packets), timebases, packets, err


def decode_check(ffmpeg, path):
    """Decode every frame. Returns {decoded_frames, error_lines, ok}."""
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "error", "-i", path, "-an",
            "-f", "framecrc", "-"]
    code, out, err = run_to_end(argv)
    _, packets = parse_framecrc(out)
    errors = [l for l in err.splitlines() if l.strip()]
    return {"ok": code == 0 and bool(packets), "decoded_frames": len(packets),
            "error_lines": len(errors),
            "first_error": errors[0][:160] if errors else None}


def ffmpeg_version(ffmpeg):
    code, out, err = run_to_end([ffmpeg, "-hide_banner", "-version"])
    return out.splitlines()[0] if out else None


# ------------------------------------------------------------------- spike A

def _rtmp_receiver(ffmpeg, workdir, name, port, framecrc_path, ts_path=None):
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning", "-listen", "1", "-i",
            "rtmp://%s:%d/live/app" % (LOOPBACK, port),
            "-map", "0:v", "-c", "copy", "-f", "framecrc", framecrc_path]
    if ts_path:
        argv += ["-map", "0:v", "-c", "copy", "-f", "mpegts", ts_path]
    proc = Proc(argv, workdir, name)
    if not wait_tcp_listening(port):
        proc.kill()
        raise RuntimeError("RTMP receiver did not start listening: %s"
                           % proc.log_text()[-300:])
    return proc


def _publisher(ffmpeg, workdir, name, udp_port, rtmp_port):
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning"]
    argv += ["-fflags", "+genpts+nobuffer", "-analyzeduration", "1000000",
             "-probesize", "200000", "-f", "mpegts", "-i",
             "udp://%s:%d?fifo_size=1000000&overrun_nonfatal=1" % (LOOPBACK, udp_port),
             "-c", "copy", "-f", "flv",
             "rtmp://%s:%d/live/app" % (LOOPBACK, rtmp_port)]
    return Proc(argv, workdir, name)


def _mpegts_encoder(ffmpeg, workdir, name, udp_port, width, height, bitrate_k,
                    fps=30):
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning"] + \
        source_args(width, height, fps) + \
        x264_args(bitrate_k, fps) + \
        ["-f", "mpegts", "-pkt_size", "1316",
         "udp://%s:%d?pkt_size=1316" % (LOOPBACK, udp_port)]
    return Proc(argv, workdir, name)


def _decoded_sizes(ffmpeg, ts_path, candidates):
    """Decode the receiver's copy and count frames per resolution (no autoscale)."""
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "error", "-i", ts_path, "-an",
            "-noautoscale", "-pix_fmt", "yuv420p", "-c:v", "rawvideo",
            "-f", "framecrc", "-"]
    code, out, err = run_to_end(argv)
    _, packets = parse_framecrc(out)
    counts = {}
    for size, n in frame_size_histogram(packets).items():
        dims = yuv420_dimensions(size, candidates)
        counts["%dx%d" % dims if dims else "size%d" % size] = n
    errors = [l for l in err.splitlines() if l.strip()]
    return {"frames_by_resolution": counts, "decode_error_lines": len(errors),
            "first_decode_error": errors[0][:160] if errors else None}


def _log_head(text, lines=4):
    """First few non-empty log lines, shortened, for the JSON report."""
    out = [l.strip()[:200] for l in text.splitlines() if l.strip()]
    return out[:lines]


def run_split_scenario(ffmpeg, workdir, label, first, second,
                       seg_seconds=5.0, gap_seconds=1.0):
    """encoder (first) 5 s, kill -9, gap, encoder (second) 5 s, then stop.

    first and second are (width, height, bitrate_k).
    """
    rtmp_port = free_port()
    udp_port = free_port(socket.SOCK_DGRAM)
    crc_path = os.path.join(workdir, "%s.crc" % label)
    ts_path = os.path.join(workdir, "%s.ts" % label)
    receiver = _rtmp_receiver(ffmpeg, workdir, label + "-recv", rtmp_port,
                              crc_path, ts_path)
    publisher = _publisher(ffmpeg, workdir, label + "-pub", udp_port, rtmp_port)
    time.sleep(0.5)
    enc1 = _mpegts_encoder(ffmpeg, workdir, label + "-enc1", udp_port,
                           first[0], first[1], first[2])
    time.sleep(seg_seconds)
    enc1.kill()
    kill_time = time.time()
    time.sleep(gap_seconds)
    publisher_alive_after_kill = publisher.alive()
    receiver_alive_after_kill = receiver.alive()
    enc2 = _mpegts_encoder(ffmpeg, workdir, label + "-enc2", udp_port,
                           second[0], second[1], second[2])
    restart_time = time.time()
    time.sleep(seg_seconds)
    publisher_alive_at_end = publisher.alive()
    receiver_alive_at_end = receiver.alive()
    enc2.kill()
    time.sleep(0.5)
    publisher.stop()
    receiver.wait(5.0)
    receiver.stop()
    wall = time.time() - enc1.started
    with open(crc_path, encoding="utf-8") as f:
        timebases, packets = parse_framecrc(f.read())
    pub_log = publisher.log_text()
    analysis = analyze_packets(packets, timebases.get(0, (1, 1000)))
    return {
        "label": label,
        "first_encoder": {"width": first[0], "height": first[1], "kbps": first[2]},
        "second_encoder": {"width": second[0], "height": second[1], "kbps": second[2]},
        "frames_sent_approx": int(round(2 * seg_seconds * 30)),
        "wall_seconds": round(wall, 1),
        "encoder_gap_seconds": round(restart_time - kill_time, 2),
        "publisher_alive_after_encoder_kill": publisher_alive_after_kill,
        "rtmp_session_alive_after_encoder_kill": receiver_alive_after_kill,
        "publisher_alive_at_end": publisher_alive_at_end,
        "rtmp_session_alive_at_end": receiver_alive_at_end,
        "received": analysis,
        "publisher_log_non_monotonic_lines": count_matches(
            pub_log, ["non monotonic", "non-monotonic"]),
        "publisher_log_discontinuity_lines": count_matches(pub_log, ["discontinuity"]),
        "publisher_log_head": _log_head(pub_log),
        "encoder2_log_head": _log_head(enc2.log_text()),
        "receiver_log_head": _log_head(receiver.log_text()),
        "publisher_cpu_seconds": publisher.cpu(),
        "publisher_peak_rss_mb": publisher.rss_mb(),
        "decoded": _decoded_sizes(ffmpeg, ts_path, [
            (first[0], first[1]), (second[0], second[1])]),
    }


def run_overhead_once(ffmpeg, workdir, split, seconds=10.0):
    """One 10 s stream, direct (encoder -> RTMP) or split (encoder -> TS -> publisher -> RTMP).
    Returns encoder cpu/rss and, for split, publisher cpu/rss."""
    rtmp_port = free_port()
    crc_path = os.path.join(workdir, "ovh.crc")
    receiver = _rtmp_receiver(ffmpeg, workdir, "ovh-recv", rtmp_port, crc_path)
    result = {}
    base = [ffmpeg, "-hide_banner", "-y", "-v", "warning"] + \
        source_args(1280, 720, 30) + x264_args(2000, 30) + ["-t", str(seconds)]
    if split:
        udp_port = free_port(socket.SOCK_DGRAM)
        publisher = _publisher(ffmpeg, workdir, "ovh-pub", udp_port, rtmp_port)
        time.sleep(0.5)
        encoder = Proc(base + ["-f", "mpegts", "-pkt_size", "1316",
                               "udp://%s:%d?pkt_size=1316" % (LOOPBACK, udp_port)],
                       workdir, "ovh-enc")
        encoder.wait(seconds + 10)
        time.sleep(1.0)
        publisher.stop()
        result["publisher_cpu_seconds"] = publisher.cpu()
        result["publisher_peak_rss_mb"] = publisher.rss_mb()
    else:
        encoder = Proc(base + ["-f", "flv",
                               "rtmp://%s:%d/live/app" % (LOOPBACK, rtmp_port)],
                       workdir, "ovh-enc")
        encoder.wait(seconds + 10)
    receiver.wait(5.0)
    receiver.stop()
    result["encoder_cpu_seconds"] = encoder.cpu()
    result["encoder_peak_rss_mb"] = encoder.rss_mb()
    return result


def spike_a(ffmpeg, workdir, repeats=3):
    scenarios = [
        run_split_scenario(ffmpeg, workdir, "a1-same-res-gap-1s",
                           (640, 360, 1000), (640, 360, 1000)),
        run_split_scenario(ffmpeg, workdir, "a2-same-res-gap-5s",
                           (640, 360, 1000), (640, 360, 1000), gap_seconds=5.0),
        run_split_scenario(ffmpeg, workdir, "a3-changed-res-and-bitrate-gap-1s",
                           (640, 360, 1000), (960, 540, 1500)),
    ]
    direct = [run_overhead_once(ffmpeg, workdir, False) for _ in range(repeats)]
    split = [run_overhead_once(ffmpeg, workdir, True) for _ in range(repeats)]
    return {
        "scenarios": scenarios,
        "overhead": {
            "stream": "testsrc2 1280x720@30, x264 ultrafast zerolatency 2000k, 10 s paced with -re",
            "repeats": repeats,
            "direct_encoder_cpu_s": summarize([r["encoder_cpu_seconds"] for r in direct]),
            "direct_encoder_rss_mb": summarize([r["encoder_peak_rss_mb"] for r in direct]),
            "split_encoder_cpu_s": summarize([r["encoder_cpu_seconds"] for r in split]),
            "split_encoder_rss_mb": summarize([r["encoder_peak_rss_mb"] for r in split]),
            "split_publisher_cpu_s": summarize([r["publisher_cpu_seconds"] for r in split]),
            "split_publisher_rss_mb": summarize([r["publisher_peak_rss_mb"] for r in split]),
        },
    }


# ------------------------------------------------------------------- spike B

def _tee_encoder(ffmpeg, workdir, name, tee_spec, seconds, global_header=True):
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning"] + \
        source_args(640, 360, 30) + x264_args(1000, 30) + \
        ["-t", str(seconds), "-map", "0:v", "-flush_packets", "1"] + \
        (["-flags", "+global_header"] if global_header else []) + \
        ["-f", "tee", tee_spec]
    return Proc(argv, workdir, name)


def _recording_report(ffmpeg, path, expected_seconds):
    if not os.path.exists(path):
        return {"exists": False}
    ok, timebases, packets, err = framecrc_of(ffmpeg, path)
    report = {"exists": True, "size_bytes": os.path.getsize(path),
              "container_readable": ok,
              "container_error": (err.splitlines()[0][:160] if err.strip() else None)}
    if ok:
        analysis = analyze_packets(packets, timebases.get(0, (1, 1000)))
        report["packets"] = analysis["packets"]
        report["span_s"] = round(analysis["span_ms"] / 1000.0, 2)
        report["expected_seconds"] = expected_seconds
        report["decode"] = decode_check(ffmpeg, path)
    return report


TEE_MODES = {
    # label: (flv slot options, matroska slot options)
    "flv onfail=ignore": (":onfail=ignore", ""),
    "flv onfail=abort": (":onfail=abort", ""),
    "no onfail anywhere": ("", ""),
    "lightstream today (matroska onfail=ignore only)": ("", ":onfail=ignore"),
}


def tee_server_kill(ffmpeg, workdir, mode, index, seconds=10, kill_at=4.0):
    flv_opts, mkv_opts = TEE_MODES[mode]
    port = free_port()
    rec = os.path.join(workdir, "b-tee-%d.mkv" % index)
    receiver = _rtmp_receiver(ffmpeg, workdir, "b-tee%d-recv" % index, port,
                              os.path.join(workdir, "b-tee%d.crc" % index))
    spec = "[f=flv%s]rtmp://%s:%d/live/app|[f=matroska%s]%s" % (
        flv_opts, LOOPBACK, port, mkv_opts, rec)
    encoder = _tee_encoder(ffmpeg, workdir, "b-tee%d-enc" % index, spec, seconds)
    time.sleep(kill_at)
    receiver.kill()
    killed_at = time.time()
    encoder.wait(seconds + 10)
    ended = encoder.ended
    if encoder.status is None:
        encoder.stop()
    log = encoder.log_text()
    return {
        "mode": mode,
        "log_slave_lines": count_matches(log, ["slave"]),
        "log_first_slave_line": next(
            (l.strip()[:200] for l in log.splitlines() if "slave" in l.lower()), None),
        "encoder_exit_code": encoder.status,
        "seconds_from_server_kill_to_encoder_exit": (
            round(ended - killed_at, 2) if ended else None),
        "encoder_outlived_server_by_over_3s": bool(ended and ended - killed_at > 3),
        "recording": _recording_report(ffmpeg, rec, seconds),
    }


def tee_global_header_check(ffmpeg, workdir):
    """Does the matroska slave of a tee get written without -flags +global_header?
    Local files only (no server), 2 s of video."""
    out = {}
    for label, flags in (("without_global_header", []),
                         ("with_global_header", ["-flags", "+global_header"])):
        rec = os.path.join(workdir, "b-gh-%s.mkv" % label)
        argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning"] + \
            source_args(320, 180, 30, paced=False) + x264_args(500, 30) + \
            ["-t", "2", "-map", "0:v"] + flags + \
            ["-f", "tee", "[f=flv]%s|[f=matroska:onfail=ignore]%s" % (
                os.path.join(workdir, "b-gh-%s.flv" % label), rec)]
        code, out_text, err = run_to_end(argv)
        out[label] = {
            "ffmpeg_exit_code": code,
            "recording_size_bytes": os.path.getsize(rec) if os.path.exists(rec) else None,
            "stderr_first_line": (err.strip().splitlines() or [""])[0][:160],
        }
    return out


def tee_without_map_check(ffmpeg, workdir):
    """Does tee accept an output with no -map at all (as build_command does
    when it appends `-f tee`)? 1 s of video plus silent audio, local files."""
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning"] + \
        source_args(320, 180, 30, paced=False) + \
        ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
         "-flags", "+global_header", "-f", "tee",
         "[f=flv]%s|[f=matroska]%s" % (os.path.join(workdir, "b-nomap.flv"),
                                       os.path.join(workdir, "b-nomap.mkv"))]
    code, out_text, err = run_to_end(argv)
    return {"ffmpeg_exit_code": code,
            "stderr_first_line": (err.strip().splitlines() or [""])[0][:160]}


def container_after_kill9(ffmpeg, workdir, label, fmt_args, ext, flush=False,
                          run_seconds=8, kill_at=5.0):
    label = label + ("+flush_packets" if flush else "")
    path = os.path.join(workdir, "b-%s.%s" % (label, ext))
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "warning"] + \
        source_args(640, 360, 30) + x264_args(1000, 30) + \
        ["-t", str(run_seconds)] + (["-flush_packets", "1"] if flush else []) + \
        fmt_args + [path]
    encoder = Proc(argv, workdir, "b-%s" % label)
    time.sleep(kill_at)
    encoder.kill()
    report = _recording_report(ffmpeg, path, kill_at)
    report["label"] = label
    return report


def numbered_reconnect(ffmpeg, workdir):
    """Attempt 1 is ended by kill -9 (the reconnect loop restarts ffmpeg when it
    exits). Attempt 2 uses the file name lightstream would pick
    (numbered_recording_path) and runs to its end."""
    base = os.path.join(workdir, "b-reconnect.mkv")
    names = [numbered_recording_path(base, attempt) for attempt in (0, 1)]
    reports = []
    for attempt in (0, 1):
        port = free_port()
        receiver = _rtmp_receiver(ffmpeg, workdir, "b-rc%d-recv" % attempt, port,
                                  os.path.join(workdir, "b-rc%d.crc" % attempt))
        spec = "[f=flv]rtmp://%s:%d/live/app|[f=matroska:onfail=ignore]%s" % (
            LOOPBACK, port, names[attempt])
        encoder = _tee_encoder(ffmpeg, workdir, "b-rc%d-enc" % attempt, spec, 4)
        if attempt == 0:
            time.sleep(3.0)
            encoder.kill()
            receiver.kill()
        else:
            encoder.wait(10)
            receiver.wait(5.0)
            receiver.stop()
        reports.append(_recording_report(ffmpeg, names[attempt],
                                         3 if attempt == 0 else 4))
    return {"file_names": [os.path.basename(n) for n in names],
            "attempt_1_killed_at_3s": reports[0], "attempt_2_full_4s": reports[1],
            "first_file_kept_after_attempt_2": os.path.exists(names[0])}


def swap_capture_inputs(argv, replacement):
    """Replace every `... -i X` capture input (with the options before it,
    from the first input option up to the last -i value) by replacement.
    Everything after the last input (filters, encoder, muxer) is kept."""
    last_i = max(i for i, a in enumerate(argv) if a == "-i")
    first = next(i for i, a in enumerate(argv)
                 if a in ("-fflags", "-thread_queue_size", "-f", "-framerate", "-i"))
    return argv[:first] + replacement + argv[last_i + 2:]


def lightstream_record_argv_check(ffmpeg, workdir, seconds=4):
    """Run the argv build_command makes for a stream with record_to, with only
    the screen and microphone inputs swapped for lavfi test sources. The
    placeholder key never leaves this machine (loopback listener)."""
    from lightstream.cli import resolve_settings
    port = free_port()
    rec = os.path.join(workdir, "b-lightstream.mkv")
    settings = resolve_settings({}, {})._replace(
        record_to=rec, platform="custom",
        custom_url="rtmp://%s:%d/live" % (LOOPBACK, port))
    argv = build_command(settings, "spikekey", "linux", "libx264", ffmpeg=ffmpeg)
    argv = swap_capture_inputs(argv, [
        "-re", "-t", str(seconds), "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
        "-re", "-t", str(seconds), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
    receiver = _rtmp_receiver(ffmpeg, workdir, "b-ls-recv", port,
                              os.path.join(workdir, "b-ls.crc"))
    encoder = Proc(argv, workdir, "b-ls-enc")
    encoder.wait(seconds + 15)
    if encoder.status is None:
        encoder.stop()
    receiver.wait(5.0)
    receiver.stop()
    packets = []
    crc = os.path.join(workdir, "b-ls.crc")
    if os.path.exists(crc):  # the listener creates it only after a connection
        with open(crc, encoding="utf-8") as f:
            _, packets = parse_framecrc(f.read())
    log = encoder.log_text()
    return {"argv_source": "command.build_command (record_to set), capture inputs swapped for lavfi",
            "encoder_exit_code": encoder.status,
            "rtmp_video_packets_received": len(packets),
            "recording": _recording_report(ffmpeg, rec, seconds),
            "log_head": _log_head(log.replace("spikekey", "<key>"))}


def spike_b(ffmpeg, workdir, repeats=1):
    del repeats
    return {
        "tee_server_killed": [tee_server_kill(ffmpeg, workdir, mode, i)
                              for i, mode in enumerate(TEE_MODES)],
        "tee_global_header": tee_global_header_check(ffmpeg, workdir),
        "tee_without_map": tee_without_map_check(ffmpeg, workdir),
        "lightstream_record_argv": lightstream_record_argv_check(ffmpeg, workdir),
        "containers_after_kill9": [
            container_after_kill9(ffmpeg, workdir, name, args, ext, flush)
            for flush in (False, True)
            for name, args, ext in (
                ("mkv", ["-f", "matroska"], "mkv"),
                ("mp4", ["-f", "mp4"], "mp4"),
                ("fragmented-mp4",
                 ["-f", "mp4", "-movflags", "frag_keyframe+empty_moov"], "mp4"))],
        "numbered_files_across_reconnect": numbered_reconnect(ffmpeg, workdir),
    }


# ------------------------------------------------------------------- spike C

POTATO_CONFIGS = [
    ("baseline crf28", [], ["-crf", "28"]),
    ("format=gray (yuv400)", ["-vf", "format=gray"], ["-crf", "28"]),
    ("format=gray,format=yuv420p", ["-vf", "format=gray,format=yuv420p"], ["-crf", "28"]),
    ("fps=15", ["-vf", "fps=15"], ["-crf", "28"]),
    ("fps=10", ["-vf", "fps=10"], ["-crf", "28"]),
    ("mpdecimate", ["-vf", "mpdecimate", "-fps_mode", "vfr"], ["-crf", "28"]),
    ("scale 640x360", ["-vf", "scale=640:360"], ["-crf", "28"]),
    ("scale 480x270", ["-vf", "scale=480:270"], ["-crf", "28"]),
    ("scale 640x360 + fps=15", ["-vf", "scale=640:360,fps=15"], ["-crf", "28"]),
    ("scale 480x270 + fps=10 + gray->420", ["-vf", "scale=480:270,fps=10,format=gray,format=yuv420p"],
     ["-crf", "28"]),
    ("threads 1", [], ["-crf", "28", "-threads", "1"]),
    ("threads 2", [], ["-crf", "28", "-threads", "2"]),
    ("threads 4", [], ["-crf", "28", "-threads", "4"]),
    ("CBR 2000k", [], ["-b:v", "2000k", "-minrate", "2000k", "-maxrate", "2000k",
                       "-bufsize", "2000k", "-x264-params", "nal-hrd=cbr"]),
    ("CBR 4000k", [], ["-b:v", "4000k", "-minrate", "4000k", "-maxrate", "4000k",
                       "-bufsize", "4000k", "-x264-params", "nal-hrd=cbr"]),
]
FILTER_SOURCES = [("testsrc2", "moving synthetic"),
                  ("smptebars", "static synthetic")]


def potato_argv(ffmpeg, source, seconds, filter_args, encode_args, out):
    # -t before -i bounds the source, so a filter that drops every frame
    # (mpdecimate on a static picture) still ends.
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "error", "-t", str(seconds)] + \
        source_args(1280, 720, 30, kind=source, paced=False) + \
        filter_args + \
        ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
         "-bf", "0", "-g", "30", "-an"]
    if "-threads" not in encode_args:
        argv += ["-threads", "4"]
    return argv + encode_args + ["-f", "mpegts", out]


def spike_c(ffmpeg, workdir, repeats=3, seconds=10):
    out_path = os.path.join(workdir, "c-out.ts")
    results = []
    for source, source_note in FILTER_SOURCES:
        for label, filter_args, encode_args in POTATO_CONFIGS:
            cpus, walls, kbps, rss = [], [], [], []
            error = None
            for _ in range(repeats):
                code, wall, cpu, mb, err = timed_run(
                    potato_argv(ffmpeg, source, seconds, filter_args,
                                encode_args, out_path))
                if code != 0:
                    error = (err.strip().splitlines() or ["failed"])[-1][:160]
                    break
                cpus.append(cpu)
                walls.append(wall)
                rss.append(mb)
                kbps.append(bitrate_kbps(os.path.getsize(out_path), seconds))
            results.append({"source": source, "source_kind": source_note,
                            "config": label, "error": error,
                            "cpu_s": summarize(cpus), "wall_s": summarize(walls),
                            "peak_rss_mb": summarize(rss),
                            "container_kbps": summarize(kbps)})
    return {"stream_seconds": seconds, "repeats": repeats,
            "input": "1280x720@30 lavfi, not paced, no audio, libx264 ultrafast zerolatency, default 4 threads unless a row sets threads",
            "results": results}


# ------------------------------------------------------------------- spike D

def _srt_transfer(ffmpeg, workdir, label, latency_us, seconds=6):
    port = free_port(socket.SOCK_DGRAM)
    out = os.path.join(workdir, "d-%s.crc" % label)
    listener = Proc([ffmpeg, "-hide_banner", "-y", "-v", "warning", "-i",
                     "srt://%s:%d?mode=listener&latency=%d" % (LOOPBACK, port, latency_us),
                     "-map", "0:v", "-c", "copy", "-f", "framecrc", out],
                    workdir, "d-%s-recv" % label)
    time.sleep(1.0)
    started = time.time()
    sender = Proc([ffmpeg, "-hide_banner", "-y", "-v", "warning"] +
                  source_args(640, 360, 30) + x264_args(1000, 30) +
                  ["-t", str(seconds), "-f", "mpegts",
                   "srt://%s:%d?mode=caller&latency=%d" % (LOOPBACK, port, latency_us)],
                  workdir, "d-%s-send" % label)
    sender.wait(seconds + 10)
    listener.wait(8.0)
    listener.stop()
    with open(out, encoding="utf-8") as f:
        timebases, packets = parse_framecrc(f.read())
    analysis = analyze_packets(packets, timebases.get(0, (1, 90000)))
    return {"label": label, "latency_us": latency_us,
            "sender_exit_code": sender.status,
            "sender_seconds": round((sender.ended or time.time()) - started, 1),
            "sender_cpu_s": sender.cpu(),
            "received_packets": analysis["packets"],
            "non_monotonic": analysis["non_monotonic"],
            "span_s": round(analysis["span_ms"] / 1000.0, 2),
            "expected_packets_approx": seconds * 30}


def srt_refused_connect(ffmpeg, workdir):
    port = free_port(socket.SOCK_DGRAM)
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=10", "-t", "1", "-c:v", "libx264",
            "-f", "mpegts", "srt://%s:%d?mode=caller" % (LOOPBACK, port)]
    code, wall, cpu, mb, err = timed_run(argv, timeout=30)
    return {"exit_code": code, "seconds_to_fail": wall,
            "message": (err.strip().splitlines() or [""])[-1][:160]}


def spike_d(ffmpeg, workdir, repeats=1):
    del repeats
    code, out, err = run_to_end([ffmpeg, "-hide_banner", "-h", "protocol=srt"])
    options = parse_protocol_options(out + err)
    return {
        "srt_options_in_this_build": options,
        "transfers": [_srt_transfer(ffmpeg, workdir, "latency-120ms", 120000),
                      _srt_transfer(ffmpeg, workdir, "latency-500ms", 500000)],
        "caller_with_no_listener": srt_refused_connect(ffmpeg, workdir),
        "not_measured": ["packet loss and ARQ behavior (no tc/netem on loopback here)",
                         "ingest by Twitch, YouTube or any real platform"],
    }


# ------------------------------------------------------------------- spike E

AUDIO_SPIKE_SECONDS = 120
AUDIO_SPIKE_RATE = 48000
AUDIO_SPIKE_INPUT = (
    "sine=f=440:r=%d:d=%d[tone];anoisesrc=a=0.05:r=%d:d=%d[noise];"
    "[tone][noise]amix=inputs=2:duration=first"
    % (AUDIO_SPIKE_RATE, AUDIO_SPIKE_SECONDS, AUDIO_SPIKE_RATE, AUDIO_SPIKE_SECONDS))


def audio_chain_argv(ffmpeg, chain):
    """Decode-free run of the synthetic input through a chain (None = baseline)."""
    argv = [ffmpeg, "-hide_banner", "-y", "-v", "error", "-f", "lavfi",
            "-i", AUDIO_SPIKE_INPUT]
    if chain:
        argv += ["-af", chain]
    return argv + ["-f", "null", "-"]


def spike_e(ffmpeg, workdir, repeats=3):
    del workdir
    configs = [("baseline (no filter)", None)]
    for name in AUDIO_PROFILES:
        for kind in AUDIO_CHAINS:
            configs.append(("%s/%s" % (name, kind), audio_profile_chain(name, kind)))
    results = []
    for label, chain in configs:
        cpus, walls = [], []
        error = None
        for _ in range(repeats):
            code, wall, cpu, _mb, err = timed_run(audio_chain_argv(ffmpeg, chain))
            if code != 0:
                error = (err.strip().splitlines() or ["failed"])[-1][:160]
                break
            cpus.append(cpu)
            walls.append(wall)
        results.append({"config": label, "chain": chain, "error": error,
                        "cpu_s": summarize(cpus), "wall_s": summarize(walls)})
    return {"audio_seconds": AUDIO_SPIKE_SECONDS, "repeats": repeats,
            "input": "synthetic: 440 Hz sine plus white noise (amplitude 0.05), "
                     "%d Hz, processed as fast as possible to the null muxer"
                     % AUDIO_SPIKE_RATE,
            "results": results}


# ------------------------------------------------------------------- spike F

F_SECONDS = 8
F_CHANGE_AT_S = 4
F_START_KBPS = 3000
F_NEW_KBPS = 500
# (encoder, extra output args). Only software encoders: no GPU in the sandbox.
F_ENCODERS = [
    ("libx264", ["-preset", "ultrafast", "-tune", "zerolatency", "-bf", "0"]),
    ("libx265", ["-preset", "ultrafast", "-x265-params", "log-level=error"]),
    ("libvpx", ["-deadline", "realtime", "-cpu-used", "8"]),
    ("libvpx-vp9", ["-deadline", "realtime", "-cpu-used", "8"]),
    ("libaom-av1", ["-cpu-used", "8", "-usage", "realtime"]),
]


def _f_argv(ffmpeg, encoder, extra, command, out, pre_filter=None):
    """Encode a synthetic 640x360@30 stream; `command` is a sendcmd line or None.

    `pre_filter` is an extra filter placed before format (the control run puts
    a `hue` there for sendcmd to reach). Output is Matroska so that VP8, VP9 and
    AV1 packets can be read back too.
    """
    vf = "format=yuv420p"
    if pre_filter:
        vf = pre_filter + "," + vf
    if command:
        vf = "sendcmd=c='%s'," % command + vf
    return [ffmpeg, "-hide_banner", "-y", "-v", "error", "-t", str(F_SECONDS),
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-vf", vf,
            "-c:v", encoder, "-b:v", "%dk" % F_START_KBPS, "-g", "30"] + extra + \
        ["-an", "-f", "matroska", out]


def _f_halves(ffmpeg, ts_path):
    code, out, _err = run_to_end([ffmpeg, "-hide_banner", "-v", "error", "-i", ts_path,
                                  "-c", "copy", "-f", "framecrc", "-"])
    if code != 0:
        return None, None
    timebases, packets = parse_framecrc(out)
    return half_bitrates(packets, timebases.get(0, (1, 1000)), F_CHANGE_AT_S * 1000)


def _f_probe(ffmpeg, encoder, extra, command, workdir, pre_filter=None):
    out = os.path.join(workdir, "f-out.mkv")
    code, _out, err = run_to_end(_f_argv(ffmpeg, encoder, extra, command, out,
                                         pre_filter))
    row = {"return_code": code,
           "stderr_last": (err.strip().splitlines() or [""])[-1][:200]}
    if code == 0 and os.path.exists(out):
        before, after = _f_halves(ffmpeg, out)
        row.update({"kbps_before": before, "kbps_after": after,
                    "after_over_before": None if not before or after is None
                    else round(after / before, 3)})
    return row


def spike_f(ffmpeg, workdir, repeats=1):
    del repeats
    _code, filters_out, _err = run_to_end([ffmpeg, "-hide_banner", "-filters"])
    filters = parse_filter_names(filters_out)
    _code, enc_out, _err = run_to_end([ffmpeg, "-hide_banner", "-encoders"])
    encoders = parse_video_encoder_names(enc_out)
    hardware = [e for e in encoders if re.search(
        r"nvenc|qsv|vaapi|amf|videotoolbox|v4l2m2m|mf$|omx|vulkan", e)]
    results = []
    for encoder, extra in F_ENCODERS:
        if encoder not in encoders:
            results.append({"encoder": encoder, "available": False})
            continue
        row = {"encoder": encoder, "available": True}
        row["no_command"] = _f_probe(ffmpeg, encoder, extra, None, workdir)
        # sendcmd targets a filter instance by name. The encoder is not one.
        for label, target in (("sendcmd_to_encoder_name", "%s b_v %d" % (encoder, F_NEW_KBPS * 1000)),
                              ("sendcmd_to_encoder_bitrate_option", "%s bit_rate %d" % (encoder, F_NEW_KBPS * 1000))):
            row[label] = _f_probe(
                ffmpeg, encoder, extra,
                "%d %s;" % (F_CHANGE_AT_S, target), workdir)
        results.append(row)
    # Controls: the same sendcmd mechanism does reach a filter. With a `hue`
    # instance in the graph, desaturating at the change time lowers the bitrate.
    control = _f_probe(ffmpeg, "libx264", F_ENCODERS[0][1],
                       "%d hue s 0;" % F_CHANGE_AT_S, workdir, pre_filter="hue=s=1")
    control_off = _f_probe(ffmpeg, "libx264", F_ENCODERS[0][1], None, workdir,
                           pre_filter="hue=s=1")
    return {"stream_seconds": F_SECONDS, "change_at_s": F_CHANGE_AT_S,
            "start_kbps": F_START_KBPS, "commanded_kbps": F_NEW_KBPS,
            "filters_present": {name: name in filters
                                for name in ("sendcmd", "asendcmd", "zmq", "azmq")},
            "hardware_encoders_listed": hardware,
            "note_control": "a `hue=s=1` filter is in the graph; sendcmd sets its "
                            "saturation to 0 at the change time. A bitrate drop shows the "
                            "command mechanism works on filters.",
            "control_sendcmd_to_filter": control,
            "control_no_command": control_off,
            "results": results}


# ------------------------------------------------------------------- spike G

G_SECONDS = 10
G_BASE = "testsrc2=size=1280x720:rate=30"
G_TEXT_FILTER = ("drawtext=text='%{localtime\\:%X}':x=20:y=20:fontsize=48:"
                 "fontcolor=white:box=1:boxcolor=black@0.5")


def _g_png(ffmpeg, workdir):
    """A 400x80 PNG made by ffmpeg itself (nothing is committed)."""
    path = os.path.join(workdir, "g-clock.png")
    code, _out, err = run_to_end([ffmpeg, "-hide_banner", "-y", "-v", "error", "-f", "lavfi",
                                  "-i", "color=c=black:size=400x80,format=yuv420p",
                                  "-frames:v", "1", path])
    if code != 0:
        raise RuntimeError("could not make the overlay PNG: %s" % err.strip()[-120:])
    return path


def _g_encode_tail(out):
    return ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-bf", "0", "-g", "30", "-threads", "4", "-an", "-f", "mpegts", out]


def g_configs(png, has_drawtext):
    """(label, note, input args, filter args). Overlay inputs are -i entries."""
    base = ["-t", str(G_SECONDS), "-f", "lavfi", "-i", G_BASE]
    still = ["-t", str(G_SECONDS), "-f", "lavfi", "-i",
             "smptebars=size=1280x720:rate=30"]
    configs = [("baseline", "no overlay, moving picture", base, [])]
    if has_drawtext:
        configs.append(("drawtext clock per frame", "text re-rendered for every frame",
                        base, ["-vf", G_TEXT_FILTER]))
    configs += [
        ("PNG overlay, -loop 1 -framerate 1",
         "pre-rendered picture, 1 input frame per second",
         base + ["-loop", "1", "-framerate", "1", "-t", str(G_SECONDS), "-i", png],
         ["-filter_complex", "[0:v][1:v]overlay=20:20:eof_action=repeat[v]", "-map", "[v]"]),
        ("changing overlay at 30 fps",
         "a 400x80 source that changes every frame; stands in for per-frame text",
         base + ["-f", "lavfi", "-i", "testsrc2=size=400x80:rate=30"],
         ["-filter_complex", "[0:v][1:v]overlay=20:20:shortest=1[v]", "-map", "[v]"]),
        ("mpdecimate, moving picture", "drops nothing on a moving picture",
         base, ["-vf", "mpdecimate"]),
        ("baseline, static picture", "SMPTE bars, no overlay", still, []),
        ("mpdecimate, static picture", "SMPTE bars; near duplicates dropped",
         still, ["-vf", "mpdecimate"]),
    ]
    return configs


def spike_g(ffmpeg, workdir, repeats=3):
    _code, filters_out, _err = run_to_end([ffmpeg, "-hide_banner", "-filters"])
    has_drawtext = "drawtext" in parse_filter_names(filters_out)
    png = _g_png(ffmpeg, workdir)
    out = os.path.join(workdir, "g-out.ts")
    results = []
    for label, note, inputs, filter_args in g_configs(png, has_drawtext):
        cpus, walls, kbps = [], [], []
        error = None
        for _ in range(repeats):
            argv = [ffmpeg, "-hide_banner", "-y", "-v", "error"] + inputs + \
                filter_args + _g_encode_tail(out)
            code, wall, cpu, _mb, err = timed_run(argv)
            if code != 0:
                error = (err.strip().splitlines() or ["failed"])[-1][:160]
                break
            cpus.append(cpu)
            walls.append(wall)
            kbps.append(bitrate_kbps(os.path.getsize(out), G_SECONDS))
        results.append({"config": label, "note": note, "error": error,
                        "cpu_s": summarize(cpus), "wall_s": summarize(walls),
                        "container_kbps": summarize(kbps)})
    if not has_drawtext:
        results.insert(1, {"config": "drawtext clock per frame",
                           "note": "UNMEASURED: this ffmpeg build has no drawtext filter",
                           "error": "Unknown filter 'drawtext'", "cpu_s": summarize([]),
                           "wall_s": summarize([]), "container_kbps": summarize([])})
    return {"stream_seconds": G_SECONDS, "repeats": repeats, "drawtext_available": has_drawtext,
            "input": "1280x720@30 lavfi, not paced, no audio, libx264 ultrafast zerolatency, 4 threads",
            "results": results}


# ----------------------------------------------------------------------- main

SPIKE_FUNCS = {"a": spike_a, "b": spike_b, "c": spike_c, "d": spike_d, "e": spike_e,
               "f": spike_f, "g": spike_g}


def host_summary(ffmpeg):
    return {"date": time.strftime("%Y-%m-%d"), "cpus": os.cpu_count(),
            "python": sys.version.split()[0], "ffmpeg": ffmpeg_version(ffmpeg)}


def parse_args(argv):
    opts = {"ffmpeg": os.environ.get("LIGHTSTREAM_TEST_FFMPEG", "ffmpeg"),
            "spikes": [], "repeats": 3, "out": None}
    it = iter(argv)
    for arg in it:
        if arg == "--all":
            opts["spikes"] = list(SPIKE_NAMES)
        elif arg == "--spike":
            name = next(it, "")
            if name not in SPIKE_NAMES:
                raise ValueError("--spike must be one of %s" % ", ".join(SPIKE_NAMES))
            opts["spikes"].append(name)
        elif arg == "--ffmpeg":
            opts["ffmpeg"] = next(it, "")
        elif arg == "--repeats":
            opts["repeats"] = int(next(it, "0"))
            if opts["repeats"] < 1:
                raise ValueError("--repeats must be at least 1")
        elif arg == "--out":
            opts["out"] = next(it, "")
        else:
            raise ValueError("unknown argument %s" % arg)
    if not opts["spikes"]:
        raise ValueError("choose --all or --spike a|b|c|d|e|f|g")
    return opts


def main(argv=None, funcs=None, stdout=None):
    stdout = stdout or sys.stdout
    funcs = funcs or SPIKE_FUNCS
    try:
        opts = parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        sys.stderr.write("spikes: %s\n" % exc)
        return 2
    report = {"host": host_summary(opts["ffmpeg"]), "spikes": {}}
    failed = False
    with tempfile.TemporaryDirectory(prefix="lightstream-spikes-") as workdir:
        for name in opts["spikes"]:
            try:
                report["spikes"][name] = funcs[name](
                    opts["ffmpeg"], workdir, opts["repeats"])
            except Exception as exc:  # report the failure in the JSON, exit 1
                failed = True
                report["spikes"][name] = {"error": "%s: %s" % (type(exc).__name__, exc)}
    text = json.dumps(report, indent=2)
    stdout.write(text + "\n")
    if opts["out"]:
        with open(opts["out"], "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
