"""Opt-in auto-scaling of stream quality, one ladder step at a time.

OFF by default. Passing --auto-scale (or ticking the GUI checkbox) is the
person's approval and, only then, supersedes the v0.7 rule that the advisor is
suggestion-only. With it off, nothing here runs and nothing changes.

How a step is applied
    ffmpeg cannot change encoder bitrate, frame rate or output size while it
    runs. An applied step therefore changes the settings and asks the runner to
    relaunch ffmpeg through its normal reconnect path (run_with_reconnect's
    restart event). Viewers see a brief interruption. A recording continues in
    the next numbered file (name-2.mkv). The stream key never leaves the runner
    and never appears in any message produced here.

Alternatives evaluated (see docs/ARCHITECTURE-NOTES.md)
    sendcmd/zmq filter commands can change a scale filter live but not the
    encoder bitrate or fps. x264 parameters cannot change live. A two process
    relay (capture to local relay, relay to RTMP) could switch without
    dropping the connection, at the cost of a second process (CPU and RAM),
    which defeats the low-end goal.

Hysteresis
    Step down after stress lasted DOWNSCALE_AFTER_SECONDS. Step up one step
    only after health lasted UPSCALE_AFTER_SECONDS (longer). Any change starts
    a COOLDOWN_SECONDS pause and resets both timers (the restart changes what
    is measured). At most MAX_CHANGES_PER_HOUR changes. A neutral reading
    (unknown speed, recent reconnects) resets both timers, so oscillating
    input cannot cause flapping. Never below the ladder floor or above the
    top step the person chose. The numbers are design choices, UNVERIFIED on
    real streams; the state machine is tested with a fake clock.
"""

import time
from collections import namedtuple

from .presets import PRESETS

LadderStep = namedtuple("LadderStep", "width height fps kbps")
ScaleSignal = namedtuple("ScaleSignal", "state reason")
ScaleDecision = namedtuple("ScaleDecision", "direction from_index to_index step reason")

STRESSED = "stressed"
HEALTHY = "healthy"
NEUTRAL = "neutral"
DOWN = "down"
UP = "up"

DOWNSCALE_AFTER_SECONDS = 20.0
UPSCALE_AFTER_SECONDS = 120.0   # must stay longer than DOWNSCALE_AFTER_SECONDS
COOLDOWN_SECONDS = 60.0
MAX_CHANGES_PER_HOUR = 6
HOUR_SECONDS = 3600.0
GAMING_CPU_STEP_DOWN_PERCENT = 90.0   # system CPU that makes Gaming First step down

BITRATE_STEP_FACTOR = 0.8
BITRATE_STEPS = 2               # bitrate steps before fps and resolution change
MIN_LADDER_KBPS = 300
FPS_STEPS = (60, 30, 24)
DEFAULT_FLOOR_PRESET = "potato"

assert UPSCALE_AFTER_SECONDS > DOWNSCALE_AFTER_SECONDS


def build_ladder(top, floor_preset=DEFAULT_FLOOR_PRESET):
    """Ordered LadderSteps, index 0 = top (what the person chose).

    Order of lowering: bitrate first (BITRATE_STEPS of BITRATE_STEP_FACTOR),
    then fps (down FPS_STEPS), then resolution, using the sizes and bitrates
    of the existing presets down to floor_preset. top is a LadderStep.
    """
    steps = [top]

    def add(step):
        if step != steps[-1]:
            steps.append(step)

    current = top
    for _ in range(BITRATE_STEPS):
        kbps = max(MIN_LADDER_KBPS, int(current.kbps * BITRATE_STEP_FACTOR))
        current = current._replace(kbps=min(kbps, current.kbps))
        add(current)
    for fps in FPS_STEPS:
        if fps < current.fps:
            current = current._replace(fps=fps)
            add(current)
    floor = PRESETS[floor_preset]
    heights = sorted({p.height for p in PRESETS.values()
                      if floor.height <= p.height < current.height}, reverse=True)
    for height in heights:
        preset = max((p for p in PRESETS.values() if p.height == height),
                     key=lambda p: p.video_kbps)
        current = LadderStep(preset.width, preset.height,
                             min(current.fps, preset.fps),
                             min(current.kbps, preset.video_kbps))
        add(current)
    return steps


def apply_step(settings, step):
    """StreamSettings with the ladder step's size, fps and bitrate."""
    return settings._replace(width=step.width, height=step.height,
                             fps=step.fps, video_kbps=step.kbps)


class AutoScaler:
    """Hysteresis state machine. disabled (the default) never changes anything."""

    def __init__(self, ladder, clock=time.monotonic, enabled=False):
        self.ladder = list(ladder)
        self.enabled = enabled
        self.index = 0
        self._clock = clock
        self._stress_since = None
        self._healthy_since = None
        self._last_change = None
        self._changes = []

    @property
    def step(self):
        return self.ladder[self.index]

    def update(self, signal):
        """Feed one ScaleSignal. Returns a ScaleDecision when a step is taken."""
        if not self.enabled:
            return None
        now = self._clock()
        if signal.state == STRESSED:
            self._healthy_since = None
            if self._stress_since is None:
                self._stress_since = now
        elif signal.state == HEALTHY:
            self._stress_since = None
            if self._healthy_since is None:
                self._healthy_since = now
        else:
            self._stress_since = self._healthy_since = None
        if self._last_change is not None and now - self._last_change < COOLDOWN_SECONDS:
            return None
        self._changes = [t for t in self._changes if now - t < HOUR_SECONDS]
        if len(self._changes) >= MAX_CHANGES_PER_HOUR:
            return None
        if (self._stress_since is not None
                and now - self._stress_since >= DOWNSCALE_AFTER_SECONDS
                and self.index < len(self.ladder) - 1):
            return self._move(DOWN, 1, now, signal.reason)
        if (self._healthy_since is not None
                and now - self._healthy_since >= UPSCALE_AFTER_SECONDS
                and self.index > 0):
            return self._move(UP, -1, now,
                              "Stream stayed healthy for %d seconds."
                              % int(now - self._healthy_since))
        return None

    def _move(self, direction, delta, now, reason):
        before = self.index
        self.index += delta
        self._last_change = now
        self._changes.append(now)
        self._stress_since = self._healthy_since = None
        return ScaleDecision(direction, before, self.index, self.step, reason)


def assess(advisor, sample=None, gaming_first=False):
    """ScaleSignal from the advisor (and a telemetry Sample) right now.

    Gaming First: when system CPU is at or above GAMING_CPU_STEP_DOWN_PERCENT
    while ffmpeg speed is fine, step down anyway to protect the game, and say so.
    Reconnect pressure is NEUTRAL: it blocks stepping up but does not step down.
    """
    if advisor.is_slow():
        return ScaleSignal(STRESSED, "Encoding speed is %.2fx, below real time."
                           % advisor.last_speed())
    if advisor.dropped_pressure():
        return ScaleSignal(STRESSED, "%d frames were dropped in the last minute."
                           % advisor.dropped_in_window())
    cpu = getattr(sample, "cpu_percent", None)
    if gaming_first and cpu is not None and cpu >= GAMING_CPU_STEP_DOWN_PERCENT:
        return ScaleSignal(STRESSED, "Gaming First: system CPU is at %.0f%% while the "
                           "stream is fine, so the stream steps down to protect your "
                           "game." % cpu)
    if advisor.last_speed() is None or advisor.reconnect_pressure():
        return ScaleSignal(NEUTRAL, "")
    return ScaleSignal(HEALTHY, "")


class AutoScaleSession:
    """Glue shared by the CLI and the GUI controller.

    Feed it runner statuses with on_status. When the scaler takes a step it
    updates current_settings and sets restart (a threading.Event the runner
    watches). The runner thread both calls on_status and reads
    current_settings, so no lock is needed. write(text) receives plain
    messages that never contain the stream key.
    """

    def __init__(self, settings, advisor, scaler, restart, write,
                 sampler=None, gaming_first=False):
        self.current_settings = settings
        self.advisor = advisor
        self.scaler = scaler
        self.restart = restart
        self.write = write
        self.sampler = sampler
        self.gaming_first = gaming_first
        self.decisions = []

    def on_status(self, state, detail=None):
        if not self.scaler.enabled or state != "live":
            return
        if self.sampler is not None:
            self.sampler.tick_if_due()
        sample = self.sampler.latest if self.sampler is not None else None
        decision = self.scaler.update(assess(self.advisor, sample, self.gaming_first))
        if decision is None:
            return
        self.decisions.append(decision)
        self.current_settings = apply_step(self.current_settings, decision.step)
        step = decision.step
        self.write("Auto-scale %s: %dx%d at %d fps, %d kbps. %s Restarting ffmpeg "
                   "(a brief interruption).\n"
                   % (decision.direction, step.width, step.height, step.fps,
                      step.kbps, decision.reason))
        self.restart.set()


def top_step(settings):
    return LadderStep(settings.width, settings.height, settings.fps, settings.video_kbps)
