"""Stream health analytics fed by runner.parse_progress dicts.

Memory stays bounded: only the last WINDOW_SAMPLES readings are kept, plus a
few running counters. Advice describes mechanisms; no speed or CPU numbers are
promised. Real-stream behavior is UNVERIFIED until tried on real hardware.
"""

from collections import deque
import time

from .runner import (LAGGING_BELOW_SPEED, STATUS_FALLBACK, STATUS_LIVE,
                     STATUS_RECONNECTING)

WINDOW_SAMPLES = 120          # about two minutes at ffmpeg's one line per second
LOW_BITRATE_RATIO = 0.6       # sustained bitrate under 60% of target => network
MIN_SAMPLES_FOR_ADVICE = 5    # avoid advice from the first noisy seconds
DROP_RATE_WARNING = 0.01      # more than 1% dropped frames


class HealthTracker:
    """Collects progress readings. Use on_status as the runner's on_status."""

    def __init__(self, target_kbps=None, window=WINDOW_SAMPLES, clock=time.monotonic):
        self.target_kbps = target_kbps
        self._clock = clock
        self._speeds = deque(maxlen=window)
        self._bitrates = deque(maxlen=window)
        self._fps = deque(maxlen=window)
        self.samples = 0
        self.dropped_frames = 0
        self.dup_frames = 0
        self.reconnects = 0
        self.fallbacks = 0
        self.longest_lag_seconds = 0.0
        self._lag_started = None
        self._min_speed = None
        self._speed_total = 0.0
        self._speed_count = 0
        self._bitrate_total = 0.0
        self._bitrate_count = 0

    def update(self, health):
        """Record one parse_progress dict."""
        if not health:
            return
        self.samples += 1
        if "fps" in health:
            self._fps.append(health["fps"])
        if "bitrate_kbps" in health:
            self._bitrates.append(health["bitrate_kbps"])
            self._bitrate_total += health["bitrate_kbps"]
            self._bitrate_count += 1
        if "dropped" in health:  # ffmpeg reports a running total
            self.dropped_frames = int(health["dropped"])
        if "dup" in health:
            self.dup_frames = int(health["dup"])
        if "speed" in health:
            speed = health["speed"]
            self._speeds.append(speed)
            self._speed_total += speed
            self._speed_count += 1
            self._min_speed = speed if self._min_speed is None else min(self._min_speed, speed)
            self._track_lag(speed < LAGGING_BELOW_SPEED)

    def _track_lag(self, lagging):
        now = self._clock()
        if lagging and self._lag_started is None:
            self._lag_started = now
        if self._lag_started is not None:
            self.longest_lag_seconds = max(self.longest_lag_seconds,
                                           now - self._lag_started)
            if not lagging:
                self._lag_started = None

    def note_reconnect(self):
        self.reconnects += 1
        self._lag_started = None

    def on_status(self, state, detail=None):
        """Runner callback. Safe to call from the runner thread."""
        if state == STATUS_LIVE:
            self.update(detail)
        elif state == STATUS_RECONNECTING:
            self.note_reconnect()
        elif state == STATUS_FALLBACK:
            self.fallbacks += 1

    def summary(self):
        recent_bitrate = _mean(self._bitrates)
        return {
            "samples": self.samples,
            "avg_speed": (self._speed_total / self._speed_count
                          if self._speed_count else None),
            "min_speed": self._min_speed,
            "recent_speed": _mean(self._speeds),
            "avg_bitrate_kbps": (self._bitrate_total / self._bitrate_count
                                 if self._bitrate_count else None),
            "recent_bitrate_kbps": recent_bitrate,
            "recent_fps": _mean(self._fps),
            "dropped_frames": self.dropped_frames,
            "dup_frames": self.dup_frames,
            "reconnects": self.reconnects,
            "fallbacks": self.fallbacks,
            "longest_lag_seconds": self.longest_lag_seconds,
        }

    def diagnose(self):
        """Plain-language advice list. Empty when nothing looks wrong."""
        if self.samples < MIN_SAMPLES_FOR_ADVICE and not self.reconnects:
            return []
        info = self.summary()
        advice = []
        speed = info["recent_speed"]
        if speed is not None and speed < LAGGING_BELOW_SPEED:
            advice.append(
                "Your PC cannot encode fast enough (CPU-bound). Use a lighter "
                "preset such as potato, or a hardware encoder (Quick Sync or NVENC).")
        bitrate = info["recent_bitrate_kbps"]
        if (self.target_kbps and bitrate is not None
                and bitrate < self.target_kbps * LOW_BITRATE_RATIO
                and not (speed is not None and speed < LAGGING_BELOW_SPEED)):
            advice.append(
                "Output bitrate is well below target while encoding keeps up, "
                "so the network may be the limit. Run 'lightstream bandwidth' "
                "to pick a bitrate that fits your upload speed.")
        frames = max(self.samples, 1)
        if info["dropped_frames"] and info["recent_fps"]:
            if info["dropped_frames"] / (frames * info["recent_fps"]) > DROP_RATE_WARNING:
                advice.append(
                    "Many frames were dropped. Close other programs or lower the "
                    "frame rate.")
        if self.reconnects >= 2:
            advice.append(
                "The connection dropped %d times. Check Wi-Fi signal, or use a "
                "network cable and a lower bitrate." % self.reconnects)
        return advice

    def report_lines(self):
        """End-of-session text lines for the CLI."""
        info = self.summary()
        lines = ["Session health:"]
        if info["avg_speed"] is not None:
            lines.append("  speed: avg %.2fx, min %.2fx"
                         % (info["avg_speed"], info["min_speed"]))
        lines.append("  dropped frames: %d" % info["dropped_frames"])
        lines.append("  reconnects: %d" % info["reconnects"])
        lines.append("  longest lag: %.0fs" % info["longest_lag_seconds"])
        for item in self.diagnose():
            lines.append("  advice: " + item)
        return lines


def _mean(values):
    return sum(values) / len(values) if values else None
