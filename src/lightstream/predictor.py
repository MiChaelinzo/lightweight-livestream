"""Bandwidth and encoder trend predictor (opt-in, part of --guardian).

Looks at a rolling window of two readings from ffmpeg's progress lines:
encoding speed and the bitrate-vs-target ratio. For each series it keeps an
EWMA (smoothed level) and a least-squares slope per second. It reports
"degrading" only when the slope is negative and statistically clear (the
slope is more than SLOPE_SIGNIFICANCE standard errors below zero) and the
level extrapolated HORIZON_SECONDS ahead falls under the limit. Otherwise it
reports "stable", or "unknown" while the window is too short.

The output queue is not available: ffmpeg progress lines and network.py have
no queue length, so queue growth is not used.

Results on SYNTHETIC traces only (steady, noisy steady, ramp down, step) are
in tests/test_predictor.py and docs/BENCHMARKS.md. No real stream was used,
so accuracy and lead time on real connections are UNVERIFIED. The ffmpeg
bitrate reading is an average since the start, which smooths real dips.
"""

import math
import time
from collections import deque, namedtuple

from .health import LOW_BITRATE_RATIO
from .runner import LAGGING_BELOW_SPEED

STABLE = "stable"
DEGRADING = "degrading"
UNKNOWN = "unknown"

HORIZON_SECONDS = 30.0        # how far ahead the level is extrapolated
WINDOW_SAMPLES = 40           # about 40 seconds of one-per-second readings
MIN_SAMPLES = 15              # below this the answer is unknown
EWMA_ALPHA = 0.2
SLOPE_SIGNIFICANCE = 5.0      # slope must be this many standard errors below 0
PERSIST_PREDICTIONS = 5       # consecutive degrading readings before it is reported
MIN_SPAN_SECONDS = 10.0       # readings must cover at least this much time

PredictedTrend = namedtuple("PredictedTrend", "state horizon_seconds reasons")
UNKNOWN_TREND = PredictedTrend(UNKNOWN, HORIZON_SECONDS, ())


def ewma(values, alpha=EWMA_ALPHA):
    """Exponentially weighted level of values (oldest first), None if empty."""
    level = None
    for value in values:
        level = value if level is None else alpha * value + (1 - alpha) * level
    return level


def slope(points):
    """(slope per second, standard error) of a least-squares line through
    (time, value) points. (None, None) when it cannot be computed."""
    n = len(points)
    if n < 3:
        return None, None
    mean_t = sum(t for t, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    sxx = sum((t - mean_t) ** 2 for t, _ in points)
    if sxx <= 0:
        return None, None
    sxy = sum((t - mean_t) * (v - mean_v) for t, v in points)
    rate = sxy / sxx
    residual = sum((v - (mean_v + rate * (t - mean_t))) ** 2 for t, v in points)
    error = math.sqrt(residual / (n - 2) / sxx)
    return rate, error


class TrendPredictor:
    """Rolling window of (time, speed, bitrate ratio). Injected clock."""

    def __init__(self, target_kbps=None, clock=time.monotonic,
                 window=WINDOW_SAMPLES, horizon=HORIZON_SECONDS):
        self.target_kbps = target_kbps
        self.horizon = horizon
        self._clock = clock
        self._speed = deque(maxlen=window)
        self._ratio = deque(maxlen=window)
        self._streak = 0

    def retarget(self, video_kbps=None, fps=None):
        """After a restart the readings describe different settings: start over."""
        if video_kbps:
            self.target_kbps = video_kbps
        self._speed.clear()
        self._ratio.clear()
        self._streak = 0

    def add(self, health):
        """One parse_progress dict (speed and bitrate_kbps keys are optional)."""
        now = self._clock()
        if "speed" in health:
            self._speed.append((now, health["speed"]))
        if "bitrate_kbps" in health and self.target_kbps:
            self._ratio.append((now, health["bitrate_kbps"] / self.target_kbps))

    def predict(self):
        """PredictedTrend. Call once per reading: degrading is reported only
        after PERSIST_PREDICTIONS degrading readings in a row, which keeps a
        single noisy stretch from raising it."""
        trend = self._predict_now()
        self._streak = self._streak + 1 if trend.state == DEGRADING else 0
        if trend.state == DEGRADING and self._streak < PERSIST_PREDICTIONS:
            return PredictedTrend(STABLE, trend.horizon_seconds, ())
        return trend

    def _predict_now(self):
        reasons = []
        known = False
        for name, series, limit, label in (
                ("speed", self._speed, LAGGING_BELOW_SPEED, "Encoding speed"),
                ("ratio", self._ratio, LOW_BITRATE_RATIO, "Sent bitrate")):
            points = list(series)
            if (len(points) < MIN_SAMPLES
                    or points[-1][0] - points[0][0] < MIN_SPAN_SECONDS):
                continue
            known = True
            rate, error = slope(points)
            if rate is None or rate >= 0:
                continue
            if error > 0 and -rate < SLOPE_SIGNIFICANCE * error:
                continue    # a downward drift that noise could explain
            level = ewma(v for _, v in points)
            ahead = level + rate * self.horizon
            if ahead < limit:
                reasons.append(
                    "%s is trending down (about %.2f now, about %.2f in %d "
                    "seconds at this pace, below %.2f)."
                    % (label, level, ahead, int(self.horizon), limit))
        if reasons:
            return PredictedTrend(DEGRADING, self.horizon, tuple(reasons))
        return PredictedTrend(STABLE if known else UNKNOWN, self.horizon, ())
