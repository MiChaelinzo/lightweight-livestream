"""Performance Guardian and auto-survival (both opt-in, OFF by default).

One engine: the Guardian only produces extra ScaleSignals for the existing
AutoScaler (autoscale.assess(extra=...)). It adds two things to what the
advisor already sees:

  * telemetry pressure: CPU, RAM, CPU temperature and GPU load from a
    telemetry Sample. Unknown fields (None) are ignored; with no known field
    nothing is reported ("n/a").
  * the bandwidth trend from predictor.TrendPredictor, as a STRESSED reason
    when it says "degrading".

Every step still restarts the encoder (ffmpeg cannot change bitrate, fps or
size while running; the 0.16 spikes measured that libx264, x265, vpx and aom
ignore runtime bitrate commands). --persistent-ingest keeps the connection
alive across that restart; about 10% of frames were lost near a restart on
loopback (measured on loopback only).

Auto-survival (--auto-survival): when CPU >= SURVIVAL_CPU_PERCENT or RAM >=
SURVIVAL_RAM_PERCENT for SURVIVAL_HOLD_SECONDS, switch to the constant-size
emergency settings (same picture size, audio untouched, lower fps and
bitrate, no overlays). Leave it only after CPU and RAM were both under
SURVIVAL_EXIT_PERCENT for SURVIVAL_EXIT_HOLD_SECONDS. Entering is limited by a
cooldown and SURVIVAL_MAX_ENTRIES_PER_HOUR so it cannot flap. The numbers are
design choices, UNVERIFIED on real machines; the state machines are tested
with a fake clock.
"""

import time
from collections import namedtuple

from .autoscale import HEALTHY, NEUTRAL, STRESSED, ScaleSignal
from .predictor import DEGRADING, TrendPredictor

# Pressure thresholds for the Guardian: (stressed at or above, healthy below).
CPU_STRESS_PERCENT = 90.0
CPU_HEALTHY_PERCENT = 75.0
RAM_STRESS_PERCENT = 90.0
RAM_HEALTHY_PERCENT = 80.0
CPU_TEMP_STRESS_C = 85.0
CPU_TEMP_HEALTHY_C = 80.0
GPU_STRESS_PERCENT = 95.0
GPU_HEALTHY_PERCENT = 90.0

SURVIVAL_CPU_PERCENT = 95.0
SURVIVAL_RAM_PERCENT = 90.0
SURVIVAL_HOLD_SECONDS = 10.0
SURVIVAL_EXIT_PERCENT = 80.0
SURVIVAL_EXIT_HOLD_SECONDS = 60.0
SURVIVAL_COOLDOWN_SECONDS = 60.0
SURVIVAL_MAX_ENTRIES_PER_HOUR = 4
HOUR_SECONDS = 3600.0

ENTER = "enter"
EXIT = "exit"
SurvivalEvent = namedtuple("SurvivalEvent", "kind reason")

# (field, label, stress at or above, healthy below, unit)
_PRESSURE_RULES = (
    ("cpu_percent", "System CPU", CPU_STRESS_PERCENT, CPU_HEALTHY_PERCENT, "%"),
    ("ram_percent", "System RAM", RAM_STRESS_PERCENT, RAM_HEALTHY_PERCENT, "%"),
    ("cpu_temp_c", "CPU temperature", CPU_TEMP_STRESS_C, CPU_TEMP_HEALTHY_C, " C"),
    ("gpu_percent", "GPU load", GPU_STRESS_PERCENT, GPU_HEALTHY_PERCENT, "%"),
)


def assess_pressure(sample):
    """ScaleSignal from a telemetry Sample.

    STRESSED when any known field is at or above its limit (cpu_bound is set
    for CPU, so a step down is not undone while the lower load looks healthy).
    HEALTHY when every known field is under its healthy level. NEUTRAL with
    an empty reason when no field is known (n/a), NEUTRAL with a reason when a
    field sits between the two levels.
    """
    known = 0
    between = []
    for field, label, stress, healthy, unit in _PRESSURE_RULES:
        value = getattr(sample, field, None)
        if value is None:
            continue
        known += 1
        if value >= stress:
            return ScaleSignal(
                STRESSED, "%s is at %.0f%s (limit %.0f%s)."
                % (label, value, unit, stress, unit),
                cpu_bound=field == "cpu_percent")
        if value >= healthy:
            between.append("%s is at %.0f%s" % (label, value, unit))
    if not known:
        return ScaleSignal(NEUTRAL, "")
    if between:
        return ScaleSignal(NEUTRAL, "; ".join(between) + ".")
    return ScaleSignal(HEALTHY, "")


class Guardian:
    """Feeds telemetry pressure and the bandwidth trend to the AutoScaler.

    Use as a monitor (retarget) and call observe() on every live status.
    """

    def __init__(self, target_kbps=None, clock=time.monotonic, predictor=None):
        self.predictor = predictor or TrendPredictor(target_kbps, clock)
        self.last_trend = None

    def retarget(self, video_kbps=None, fps=None):
        self.predictor.retarget(video_kbps, fps)

    def observe(self, health, sample=None):
        """Extra ScaleSignals (only informative ones) for assess(extra=...)."""
        if health:
            self.predictor.add(health)
        signals = []
        pressure = assess_pressure(sample)
        if pressure.state == STRESSED or (pressure.state == NEUTRAL and pressure.reason):
            signals.append(pressure)
        self.last_trend = self.predictor.predict()
        if self.last_trend.state == DEGRADING:
            signals.append(ScaleSignal(
                STRESSED, "Predicted trend (extrapolated %d seconds ahead): %s"
                % (int(self.last_trend.horizon_seconds),
                   " ".join(self.last_trend.reasons))))
        return signals


class SurvivalMonitor:
    """Hysteresis state machine for auto-survival. disabled never acts."""

    def __init__(self, clock=time.monotonic, enabled=False):
        self.enabled = enabled
        self.active = False
        self._clock = clock
        self._high_since = None
        self._calm_since = None
        self._last_change = None
        self._entries = []

    def update(self, sample):
        """Feed one telemetry Sample. Returns a SurvivalEvent on a change."""
        if not self.enabled:
            return None
        now = self._clock()
        cpu = getattr(sample, "cpu_percent", None)
        ram = getattr(sample, "ram_percent", None)
        high = ((cpu is not None and cpu >= SURVIVAL_CPU_PERCENT)
                or (ram is not None and ram >= SURVIVAL_RAM_PERCENT))
        known = cpu is not None or ram is not None
        calm = known and not high and all(
            v is None or v < SURVIVAL_EXIT_PERCENT for v in (cpu, ram))
        self._high_since = (self._high_since or now) if high else None
        self._calm_since = (self._calm_since or now) if calm else None
        if (self._last_change is not None
                and now - self._last_change < SURVIVAL_COOLDOWN_SECONDS):
            return None
        if self.active:
            if (self._calm_since is not None
                    and now - self._calm_since >= SURVIVAL_EXIT_HOLD_SECONDS):
                return self._change(EXIT, now, "CPU and RAM stayed under %d%% for "
                                    "%d seconds." % (SURVIVAL_EXIT_PERCENT,
                                                     SURVIVAL_EXIT_HOLD_SECONDS))
            return None
        self._entries = [t for t in self._entries if now - t < HOUR_SECONDS]
        if (self._high_since is not None
                and now - self._high_since >= SURVIVAL_HOLD_SECONDS
                and len(self._entries) < SURVIVAL_MAX_ENTRIES_PER_HOUR):
            reason = ("CPU is at %.0f%%" % cpu if cpu is not None
                      and cpu >= SURVIVAL_CPU_PERCENT else "RAM is at %.0f%%" % ram)
            self._entries.append(now)
            return self._change(ENTER, now, "%s, held for %d seconds."
                                % (reason, SURVIVAL_HOLD_SECONDS))
        return None

    def _change(self, kind, now, reason):
        self.active = kind == ENTER
        self._last_change = now
        self._high_since = self._calm_since = None
        return SurvivalEvent(kind, reason)
