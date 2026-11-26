"""Bounded session timeline and spike attribution (shown at the end of a session).

Events (guardian steps, survival enter/exit, reconnects, emergency, config
changes) and telemetry samples are kept in memory only, bounded, with
injected time. Nothing is written to disk, so there is no persisted session
data and no `lightstream timeline` command: the timeline is printed at the end
of a session, and only when the Guardian, auto-survival or auto-scale was on.

attribute_spikes lists load spikes and the events that happened around them.
It is correlation by time, never a claim of cause, and the wording says so.
"""

import time
from collections import deque, namedtuple

from .guardian import (CPU_STRESS_PERCENT, CPU_TEMP_STRESS_C, GPU_STRESS_PERCENT,
                       RAM_STRESS_PERCENT)

EVENT_LIMIT = 200
SAMPLE_LIMIT = 600
SPIKE_WINDOW_SECONDS = 30.0
MAX_LINES = 20

STEP = "guardian step"
SURVIVAL_ENTER = "survival enter"
SURVIVAL_EXIT = "survival exit"
RECONNECT = "reconnect"
EMERGENCY = "emergency"
CONFIG = "config change"

TimelineEvent = namedtuple("TimelineEvent", "seconds kind text")
SpikeEntry = namedtuple("SpikeEntry", "seconds metric peak events text")

_SPIKE_METRICS = (
    ("cpu_percent", "CPU", CPU_STRESS_PERCENT, "%"),
    ("ram_percent", "RAM", RAM_STRESS_PERCENT, "%"),
    ("cpu_temp_c", "CPU temperature", CPU_TEMP_STRESS_C, " C"),
    ("gpu_percent", "GPU", GPU_STRESS_PERCENT, "%"),
)


class Timeline:
    """Seconds are measured from the first call to the injected clock."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._start = clock()
        self.events = deque(maxlen=EVENT_LIMIT)
        self.samples = deque(maxlen=SAMPLE_LIMIT)

    def now(self):
        return self._clock() - self._start

    def record(self, kind, text):
        self.events.append(TimelineEvent(self.now(), kind, text))

    def note_sample(self, sample):
        """Keep a telemetry Sample once (the sampler reuses the same object)."""
        if sample is None or (self.samples and self.samples[-1][1] is sample):
            return
        self.samples.append((self.now(), sample))

    def report_lines(self):
        """End-of-session lines, empty when there is nothing to report."""
        if not self.events:
            return []
        lines = ["Session timeline (this session only, not saved):"]
        for event in list(self.events)[-MAX_LINES:]:
            lines.append("  %ds  %s: %s" % (event.seconds, event.kind, event.text))
        spikes = attribute_spikes(self.samples, self.events)
        for spike in spikes[:MAX_LINES]:
            lines.append("  " + spike.text)
        if spikes:
            lines.append("  These show what happened around the same time. They do not "
                         "show what caused what.")
        return lines


def attribute_spikes(samples, events, window=SPIKE_WINDOW_SECONDS):
    """SpikeEntry list from (seconds, Sample) pairs and TimelineEvents.

    A spike is a run of consecutive samples at or above the stress level of a
    metric. Events within window seconds before the run starts or after it
    ends are listed as happening around it. Unknown (None) values break a run.
    """
    entries = []
    pairs = list(samples)
    for field, label, limit, unit in _SPIKE_METRICS:
        run = []
        for seconds, sample in pairs + [(None, None)]:
            value = getattr(sample, field, None)
            if value is not None and value >= limit:
                run.append((seconds, value))
                continue
            if run:
                entries.append(_spike(label, unit, run, events, window))
                run = []
    return sorted(entries, key=lambda e: e.seconds)


def _spike(label, unit, run, events, window):
    start, end = run[0][0], run[-1][0]
    peak = max(v for _, v in run)
    around = tuple(e for e in events if start - window <= e.seconds <= end + window)
    text = "%s peaked at %.0f%s around %ds." % (label, peak, unit, start)
    if around:
        text += " Happened around then: " + "; ".join(
            "%s at %ds" % (e.kind, e.seconds) for e in around) + "."
    else:
        text += " No recorded event happened around then."
    return SpikeEntry(start, label, peak, around, text)
