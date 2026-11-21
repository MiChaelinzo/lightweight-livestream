"""Adaptive performance advisor: suggestions only, never changes settings.

Fed the same progress dicts as HealthTracker (runner.parse_progress). It
returns Recommendation tuples that a person reads and approves; nothing here
touches StreamSettings, the config file or a running ffmpeg. The thresholds
are plain named constants. How well the advice works on real hardware is
UNVERIFIED; the rules themselves are checked by unit tests with a fake clock.
"""

from collections import deque, namedtuple
import time

from .presets import PRESETS
from .runner import (STATUS_LIVE, STATUS_RECONNECTING)

SLOW_SPEED_BELOW = 0.90          # encode speed under 0.90x cannot keep up with real time
SLOW_SUSTAINED_SECONDS = 30.0    # ...for this long without a recovery
LOW_FPS_RATIO = 0.90             # fps under 90% of target counts as CPU pressure
DROPPED_FRAMES_THRESHOLD = 30    # dropped frames inside the window
DROPPED_WINDOW_SECONDS = 60.0
BITRATE_REDUCTION_FACTOR = 0.8   # suggest 20% less video bitrate
MIN_SUGGESTED_KBPS = 300
RECONNECT_THRESHOLD = 2          # reconnects inside the window
RECONNECT_WINDOW_SECONDS = 600.0

KIND_PRESET_DOWNGRADE = "preset_downgrade"
KIND_BITRATE_REDUCTION = "bitrate_reduction"
KIND_BANDWIDTH_PROFILE = "bandwidth_profile"

# kind: what the suggestion is. value: suggested preset name or video kbps
# (None when there is no concrete number). message: plain words for the GUI/CLI.
Recommendation = namedtuple("Recommendation", "kind value message")


class AdaptiveAdvisor:
    """Tracks pressure signals and reports recommendations on demand."""

    def retarget(self, video_kbps=None, fps=None):
        """Judge later readings against a new target (after an auto-scale step)."""
        if video_kbps:
            self.video_kbps = video_kbps
        if fps:
            self.target_fps = fps

    def __init__(self, preset_name=None, video_kbps=None, target_fps=None,
                 clock=time.monotonic):
        self.preset_name = preset_name
        self.video_kbps = video_kbps
        self.target_fps = target_fps
        self._clock = clock
        self._slow_since = None
        self._last_seen = None
        self._last_speed = None
        self._last_fps = None
        self._dropped = deque()      # (time, running dropped total)
        self._reconnects = deque()   # times
        self.reconnects_total = 0
        self.observations = 0        # progress readings seen (confidence input)

    # -- inputs ------------------------------------------------------------
    def observe(self, health):
        """Record one parse_progress dict."""
        if not health:
            return
        now = self._clock()
        self._last_seen = now
        self.observations += 1
        if "fps" in health:
            self._last_fps = health["fps"]
        if "dropped" in health:
            self._dropped.append((now, int(health["dropped"])))
        if "speed" in health:
            self._last_speed = health["speed"]
            if health["speed"] < SLOW_SPEED_BELOW:
                if self._slow_since is None:
                    self._slow_since = now
            else:
                self._slow_since = None
        self._forget_old(now)

    def note_reconnect(self):
        now = self._clock()
        self._reconnects.append(now)
        self.reconnects_total += 1
        self._slow_since = None  # a new connection restarts the speed clock
        self._forget_old(now)

    def on_status(self, state, detail=None):
        """Same signature as HealthTracker.on_status, so callbacks can chain."""
        if state == STATUS_LIVE:
            self.observe(detail)
        elif state == STATUS_RECONNECTING:
            self.note_reconnect()

    def _forget_old(self, now):
        while self._dropped and now - self._dropped[0][0] > DROPPED_WINDOW_SECONDS:
            self._dropped.popleft()
        while self._reconnects and now - self._reconnects[0] > RECONNECT_WINDOW_SECONDS:
            self._reconnects.popleft()

    # -- indicators ----------------------------------------------------------
    def slow_seconds(self):
        """How long encoding has been below SLOW_SPEED_BELOW without recovering."""
        if self._slow_since is None or self._last_seen is None:
            return 0.0
        return self._last_seen - self._slow_since

    def dropped_in_window(self):
        if len(self._dropped) < 2:
            return 0
        return max(0, self._dropped[-1][1] - self._dropped[0][1])

    def is_slow(self):
        """True when the latest speed reading is under SLOW_SPEED_BELOW."""
        return self._last_speed is not None and self._last_speed < SLOW_SPEED_BELOW

    def last_speed(self):
        return self._last_speed

    def reconnects_in_window(self):
        return len(self._reconnects)

    def reconnect_pressure(self):
        """True at RECONNECT_THRESHOLD reconnects inside the window."""
        return len(self._reconnects) >= RECONNECT_THRESHOLD

    def dropped_pressure(self):
        return self.dropped_in_window() > DROPPED_FRAMES_THRESHOLD

    def cpu_pressure(self):
        """True when encoding is slow and fps is under target (when known).
        A proxy for CPU pressure: this module does not read CPU load."""
        if self._last_speed is None or self._last_speed >= SLOW_SPEED_BELOW:
            return False
        if self.target_fps and self._last_fps is not None:
            return self._last_fps < self.target_fps * LOW_FPS_RATIO
        return True

    # -- output --------------------------------------------------------------
    def recommendations(self):
        """Current suggestions, most important first. Pure read: no side effects."""
        found = []
        if self.slow_seconds() >= SLOW_SUSTAINED_SECONDS:
            found.append(self._preset_downgrade())
        if self.dropped_in_window() > DROPPED_FRAMES_THRESHOLD:
            found.append(self._bitrate_reduction())
        if len(self._reconnects) >= RECONNECT_THRESHOLD:
            found.append(Recommendation(
                KIND_BANDWIDTH_PROFILE, None,
                "The connection dropped %d times recently. Run 'lightstream bandwidth' "
                "to pick a bitrate that fits your upload speed, or use a network cable."
                % len(self._reconnects)))
        return found

    def _preset_downgrade(self):
        order = list(PRESETS)
        if self.preset_name in order and order.index(self.preset_name) > 0:
            lighter = order[order.index(self.preset_name) - 1]
            return Recommendation(
                KIND_PRESET_DOWNGRADE, lighter,
                "Encoding has run below %.2fx for %d seconds. Consider the lighter "
                "preset '%s' next time you start." % (
                    SLOW_SPEED_BELOW, int(self.slow_seconds()), lighter))
        return Recommendation(
            KIND_PRESET_DOWNGRADE, None,
            "Encoding has run below %.2fx for %d seconds. Try a hardware encoder "
            "(Quick Sync or NVENC) or close other programs."
            % (SLOW_SPEED_BELOW, int(self.slow_seconds())))

    def _bitrate_reduction(self):
        dropped = self.dropped_in_window()
        if self.video_kbps:
            lower = max(MIN_SUGGESTED_KBPS, int(self.video_kbps * BITRATE_REDUCTION_FACTOR))
            return Recommendation(
                KIND_BITRATE_REDUCTION, lower,
                "%d frames were dropped in the last minute. Consider lowering the "
                "bitrate to %d kbps." % (dropped, lower))
        return Recommendation(
            KIND_BITRATE_REDUCTION, None,
            "%d frames were dropped in the last minute. Consider a lower bitrate."
            % dropped)

    def messages(self):
        """Recommendation texts for display."""
        return [r.message for r in self.recommendations()]
