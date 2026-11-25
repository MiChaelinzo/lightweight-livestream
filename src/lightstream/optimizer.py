"""Explainable optimizer: turns health, telemetry and network signals into Insights.

Pure and deterministic: the same inputs always give the same Insights, in the
same order. Nothing here changes a setting. It builds on AdaptiveAdvisor and
reuses its thresholds (adaptive.SLOW_SPEED_BELOW and friends) instead of
defining its own. The thresholds added here (CPU_HIGH_PERCENT, GPU_HIGH_PERCENT,
CPU_TEMP_HOT_C, GPU_TEMP_HOT_C, STABILITY_LOW_BELOW) are plain heuristics, not
vendor limits. How well the advice fits real machines is UNVERIFIED; the rules
are checked by unit tests.

Bottleneck classes
    thermal  encoding is slow and a temperature is at or above the hot level
    cpu      encoding is slow and system CPU is high (or unknown, software encoder)
    gpu      encoding is slow, a hardware encoder is used and GPU load is high
    encoder  encoding is slow but CPU and GPU have room
    network  encoding keeps up, but bitrate stays under target, the stability
             score is low, or the connection dropped repeatedly
    unknown  frames drop and none of the above explains it

Confidence (0..1) is a deterministic function of how much evidence there is
and how far past its threshold the signal sits:

    sample_factor = min(1, samples / CONFIDENCE_FULL_SAMPLES)
    margin        = abs(value - threshold) / threshold
    margin_factor = CONFIDENCE_MARGIN_FLOOR
                    + (1 - CONFIDENCE_MARGIN_FLOOR) * min(1, margin / CONFIDENCE_FULL_MARGIN)
    confidence    = sample_factor * margin_factor + history_bonus   (capped at 1)

It never decreases when samples or margin grow. history_bonus is
HISTORY_BONUS_PER_SESSION for each earlier opt-in session that had the same
bottleneck, up to HISTORY_BONUS_MAX (see analytics.load_history).
"""

from collections import namedtuple

from .adaptive import (BITRATE_REDUCTION_FACTOR, DROPPED_FRAMES_THRESHOLD,
                       KIND_BANDWIDTH_PROFILE, KIND_BITRATE_REDUCTION,
                       KIND_PRESET_DOWNGRADE, MIN_SUGGESTED_KBPS,
                       RECONNECT_THRESHOLD, SLOW_SPEED_BELOW,
                       SLOW_SUSTAINED_SECONDS)
from .encoders import SOFTWARE_ENCODER
from .health import LOW_BITRATE_RATIO

# area: what to change. action: short machine-readable name. value: the
# suggested preset, kbps, fps or encoder (None when there is no number).
# explanation: why, with the observed numbers. plain_text: for non-technical users.
Insight = namedtuple("Insight", "area action value confidence explanation plain_text")

# What is currently configured; any field may be None when unknown.
OptimizerContext = namedtuple(
    "OptimizerContext", "preset_name video_kbps fps encoder noise",
    defaults=(None, None, None, None, None))

AREA_BOTTLENECK = "bottleneck"
AREA_BITRATE = "bitrate"
AREA_RESOLUTION = "resolution"
AREA_FPS = "fps"
AREA_ENCODER = "encoder"
AREA_AUDIO = "audio"
AREA_NETWORK = "network"

BOTTLENECK_CPU = "cpu"
BOTTLENECK_ENCODER = "encoder"
BOTTLENECK_NETWORK = "network"
BOTTLENECK_GPU = "gpu"
BOTTLENECK_THERMAL = "thermal"
BOTTLENECK_UNKNOWN = "unknown"

CONFIDENCE_FULL_SAMPLES = 60
CONFIDENCE_MARGIN_FLOOR = 0.5
CONFIDENCE_FULL_MARGIN = 0.5
HISTORY_BONUS_PER_SESSION = 0.05
HISTORY_BONUS_MAX = 0.2

CPU_HIGH_PERCENT = 85.0
GPU_HIGH_PERCENT = 90.0
CPU_TEMP_HOT_C = 90.0
GPU_TEMP_HOT_C = 85.0
STABILITY_LOW_BELOW = 70
CONGESTION_CONFIDENCE = 0.5      # inference from ffmpeg speed, not a measurement
RECENT_SAMPLES = 15              # about 30 seconds of telemetry at the 2 s interval
LOWER_FPS_TARGET = 30
LIGHT_NOISE = "light"
AI_NOISE = "ai"

_BOTTLENECK_TEXT = {
    BOTTLENECK_THERMAL: "Your computer is very hot and is slowing itself down.",
    BOTTLENECK_CPU: "Your processor is too busy to keep up with the stream.",
    BOTTLENECK_GPU: "Your graphics card is busy, so the hardware encoder waits.",
    BOTTLENECK_ENCODER: "The video encoder cannot keep up, even though the "
                        "processor has room.",
    BOTTLENECK_NETWORK: "Your internet connection looks like the limit.",
    BOTTLENECK_UNKNOWN: "Frames are being dropped and I cannot tell why yet.",
}


def confidence(samples, value, threshold, history_bonus=0.0):
    """Confidence 0..1 from sample count and margin over threshold (module docstring)."""
    sample_factor = min(1.0, max(0, samples) / CONFIDENCE_FULL_SAMPLES)
    margin = abs(value - threshold) / threshold if threshold else 0.0
    margin_factor = (CONFIDENCE_MARGIN_FLOOR + (1 - CONFIDENCE_MARGIN_FLOOR)
                     * min(1.0, margin / CONFIDENCE_FULL_MARGIN))
    return round(min(1.0, sample_factor * margin_factor + history_bonus), 3)


def history_bonus(history, bottleneck):
    """Extra confidence from earlier sessions that had the same bottleneck."""
    matches = sum(1 for entry in history or ()
                  if isinstance(entry, dict) and entry.get("bottleneck") == bottleneck)
    return min(HISTORY_BONUS_MAX, matches * HISTORY_BONUS_PER_SESSION)


def _recent_mean(samples, field):
    values = [getattr(s, field) for s in list(samples)[-RECENT_SAMPLES:]
              if getattr(s, field) is not None]
    return sum(values) / len(values) if values else None


def _is_hardware_encoder(encoder):
    return bool(encoder) and encoder != SOFTWARE_ENCODER


Bottleneck = namedtuple("Bottleneck", "kind value threshold")


def classify_bottleneck(advisor, summary, samples, stability, context):
    """Bottleneck(kind, value, threshold) or None when nothing is wrong.

    value and threshold are the signal that decided it, used for confidence.
    """
    cpu = _recent_mean(samples, "cpu_percent")
    gpu = _recent_mean(samples, "gpu_percent")
    cpu_temp = _recent_mean(samples, "cpu_temp_c")
    gpu_temp = _recent_mean(samples, "gpu_temp_c")
    if advisor.is_slow():
        speed = advisor.last_speed()
        if cpu_temp is not None and cpu_temp >= CPU_TEMP_HOT_C:
            return Bottleneck(BOTTLENECK_THERMAL, cpu_temp, CPU_TEMP_HOT_C)
        if gpu_temp is not None and gpu_temp >= GPU_TEMP_HOT_C:
            return Bottleneck(BOTTLENECK_THERMAL, gpu_temp, GPU_TEMP_HOT_C)
        if cpu is not None and cpu >= CPU_HIGH_PERCENT:
            return Bottleneck(BOTTLENECK_CPU, cpu, CPU_HIGH_PERCENT)
        if (_is_hardware_encoder(context.encoder) and gpu is not None
                and gpu >= GPU_HIGH_PERCENT):
            return Bottleneck(BOTTLENECK_GPU, gpu, GPU_HIGH_PERCENT)
        if cpu is None and not _is_hardware_encoder(context.encoder):
            # CPU load unknown: with a software encoder, slow speed is the
            # advisor's own proxy for CPU pressure.
            return Bottleneck(BOTTLENECK_CPU, speed, SLOW_SPEED_BELOW)
        return Bottleneck(BOTTLENECK_ENCODER, speed, SLOW_SPEED_BELOW)
    bitrate = summary.get("recent_bitrate_kbps")
    target = context.video_kbps
    if target and bitrate is not None and bitrate < target * LOW_BITRATE_RATIO:
        return Bottleneck(BOTTLENECK_NETWORK, bitrate, target * LOW_BITRATE_RATIO)
    if stability is not None and stability.score < STABILITY_LOW_BELOW:
        return Bottleneck(BOTTLENECK_NETWORK, stability.score, STABILITY_LOW_BELOW)
    if advisor.reconnect_pressure():
        return Bottleneck(BOTTLENECK_NETWORK, advisor.reconnects_in_window(),
                          RECONNECT_THRESHOLD)
    if advisor.dropped_pressure():
        return Bottleneck(BOTTLENECK_UNKNOWN, advisor.dropped_in_window(),
                          DROPPED_FRAMES_THRESHOLD)
    return None


def _explain(found):
    return "Signal %.2f against threshold %.2f." % (found.value, found.threshold)


def build_insights(advisor, summary, samples=(), stability=None, context=None,
                   history=(), congestion=()):
    """Insights, most confident first. Pure read; empty when nothing is wrong.

    congestion is a list of network.Congestion findings. Each becomes a
    network Insight with a fixed confidence (CONGESTION_CONFIDENCE) because a
    congestion finding is an inference, not a measurement. Never auto-applied.
    """
    context = context or OptimizerContext()
    found = classify_bottleneck(advisor, summary, samples, stability, context)
    seen = advisor.observations
    insights = []
    bonus = 0.0
    if found:
        bonus = history_bonus(history, found.kind)
        score = confidence(seen, found.value, found.threshold, bonus)
        insights.append(Insight(
            AREA_BOTTLENECK, found.kind, None, score,
            "Classified as %s. %s%s" % (found.kind, _explain(found), _history_note(bonus)),
            _BOTTLENECK_TEXT[found.kind]))
        insights.extend(_followups(found, context, advisor, seen, score))
    insights.extend(_advisor_insights(advisor, seen, context, bonus,
                                      {i.area for i in insights}))
    for finding in congestion:
        insights.append(Insight(AREA_NETWORK, "congestion_" + finding.kind, None,
                                CONGESTION_CONFIDENCE, finding.message,
                                "Your connection may be congested. A wired "
                                "connection or a lower video speed usually helps."))
    return sorted(insights, key=lambda i: -i.confidence)


def _history_note(bonus):
    return " Earlier sessions showed the same problem." if bonus else ""


def _followups(found, context, advisor, seen, score):
    """Concrete suggestions that follow from the bottleneck class."""
    kind = found.kind
    out = []
    if kind in (BOTTLENECK_CPU, BOTTLENECK_ENCODER, BOTTLENECK_GPU, BOTTLENECK_THERMAL):
        if context.fps and context.fps > LOWER_FPS_TARGET:
            out.append(Insight(
                AREA_FPS, "lower_fps", LOWER_FPS_TARGET, score,
                "Encoding is below %.2fx at %d fps." % (SLOW_SPEED_BELOW, context.fps),
                "Streaming at %d frames per second makes the encoder's job easier."
                % LOWER_FPS_TARGET))
        if context.noise == AI_NOISE:
            out.append(Insight(
                AREA_AUDIO, "lighter_noise_filter", LIGHT_NOISE, score,
                "The AI noise filter costs CPU and encoding is slow.",
                "Switch noise suppression to 'light' to save some processor time."))
    if kind == BOTTLENECK_CPU and not _is_hardware_encoder(context.encoder):
        out.append(Insight(
            AREA_ENCODER, "try_hardware_encoder", None, score,
            "Software encoding (%s) is slow and the CPU is the limit." % SOFTWARE_ENCODER,
            "If your PC has Quick Sync, NVENC or AMF, let the app use it. "
            "It moves the work off the processor."))
    if kind == BOTTLENECK_GPU:
        out.append(Insight(
            AREA_ENCODER, "use_software_encoder", SOFTWARE_ENCODER, score,
            "GPU load is high while the hardware encoder is slow.",
            "Try the software encoder so the graphics card has room for the game."))
    if kind == BOTTLENECK_NETWORK and context.video_kbps:
        lower = max(MIN_SUGGESTED_KBPS, int(context.video_kbps * BITRATE_REDUCTION_FACTOR))
        out.append(Insight(
            AREA_BITRATE, "lower_bitrate", lower, score,
            "Network looks limiting; %d kbps is %d%% of the current %d kbps."
            % (lower, int(BITRATE_REDUCTION_FACTOR * 100), context.video_kbps),
            "Lowering the video speed to %d kbps should make the stream steadier."
            % lower))
    return out


def _advisor_insights(advisor, seen, context, bonus, have_areas):
    """The advisor's own Recommendations as Insights (same rules, same numbers)."""
    out = []
    for rec in advisor.recommendations():
        if rec.kind == KIND_PRESET_DOWNGRADE:
            score = confidence(seen, advisor.slow_seconds(), SLOW_SUSTAINED_SECONDS, bonus)
            out.append(Insight(AREA_RESOLUTION, "lower_preset", rec.value, score,
                               rec.message, _plain_preset(rec)))
        elif rec.kind == KIND_BITRATE_REDUCTION and AREA_BITRATE not in have_areas:
            score = confidence(seen, advisor.dropped_in_window(),
                               DROPPED_FRAMES_THRESHOLD, bonus)
            out.append(Insight(AREA_BITRATE, "lower_bitrate", rec.value, score,
                               rec.message,
                               "Many frames were lost. A lower video speed helps."))
        elif rec.kind == KIND_BANDWIDTH_PROFILE:
            score = confidence(seen, advisor.reconnects_in_window(),
                               RECONNECT_THRESHOLD, bonus)
            out.append(Insight(AREA_NETWORK, "check_connection", None, score,
                               rec.message,
                               "Your connection dropped several times. A network "
                               "cable or a lower video speed usually helps."))
    return out


def _plain_preset(rec):
    if rec.value:
        return "Your PC is struggling. Use the lighter strength '%s'." % rec.value
    return "Your PC is struggling. Close other programs or use a hardware encoder."


def insight_line(insight):
    """One line for the CLI report: plain text plus confidence as a percent."""
    return "%s (confidence %d%%)" % (insight.plain_text, round(insight.confidence * 100))


def bottleneck_of(insights):
    """Bottleneck class named by a list of Insights, or None."""
    for insight in insights:
        if insight.area == AREA_BOTTLENECK:
            return insight.action
    return None


# -- performance health score ------------------------------------------------
# One 0..100 number from six signals. Each signal becomes a 0..100 sub-score by
# a straight line between a "full marks" and a "zero" value, then the weighted
# mean is taken over the signals that are KNOWN (unknown ones are left out and
# the weights renormalised, so a missing GPU reading does not hurt the score).
# Weights and lines are heuristics chosen for this project, not a standard.
HEALTH_WEIGHTS = (("cpu", 20), ("gpu", 10), ("ram", 10), ("network", 25),
                  ("encode_speed", 20), ("dropped_frames", 15))
# name: (value giving 100, value giving 0)
HEALTH_LINES = {
    "cpu": (60.0, 100.0),            # system CPU percent
    "gpu": (70.0, 100.0),            # GPU percent
    "ram": (70.0, 100.0),            # RAM used percent
    "network": (100.0, 0.0),         # NetworkStability score as is
    "encode_speed": (1.0, 0.5),      # ffmpeg speed (x real time)
    "dropped_frames": (0.0, 5.0),    # dropped frames as percent of frames
}
# (minimum score, band), checked in order
HEALTH_BANDS = ((90, "Excellent"), (75, "Good"), (55, "Fair"), (35, "Poor"),
                (0, "Critical"))
HealthScore = namedtuple("HealthScore", "score band parts skipped")


def _line_score(name, value):
    full, zero = HEALTH_LINES[name]
    fraction = (value - zero) / (full - zero)
    return 100.0 * min(1.0, max(0.0, fraction))


def performance_health(cpu=None, gpu=None, ram=None, network=None,
                       encode_speed=None, dropped_percent=None):
    """HealthScore from the six signals (None = unknown). Pure, deterministic.

    score is None and band is None when every signal is unknown.
    parts maps each known signal to its 0..100 sub-score.
    """
    values = {"cpu": cpu, "gpu": gpu, "ram": ram, "network": network,
              "encode_speed": encode_speed, "dropped_frames": dropped_percent}
    parts = {}
    weighted = 0.0
    total = 0
    for name, weight in HEALTH_WEIGHTS:
        if values[name] is None:
            continue
        parts[name] = _line_score(name, values[name])
        weighted += weight * parts[name]
        total += weight
    skipped = [name for name, _ in HEALTH_WEIGHTS if values[name] is None]
    if not total:
        return HealthScore(None, None, parts, skipped)
    score = round(weighted / total)
    band = next(label for minimum, label in HEALTH_BANDS if score >= minimum)
    return HealthScore(score, band, parts, skipped)


def session_health(summary, sample=None, stability=None):
    """HealthScore from live objects: HealthTracker.summary(), a telemetry
    Sample (or None) and NetworkStability (or None). Dropped-frame percent is
    left unknown on purpose: the summary has a count, not a frame total."""
    speed = summary.get("recent_speed")
    if speed is None:
        speed = summary.get("avg_speed")
    return performance_health(
        cpu=getattr(sample, "cpu_percent", None),
        gpu=getattr(sample, "gpu_percent", None),
        ram=getattr(sample, "ram_percent", None),
        network=None if stability is None else stability.score,
        encode_speed=speed)


def health_line(health, tier=None):
    """One plain line for the GUI and the end of a CLI session."""
    text = ("Health: not enough readings yet" if health.score is None
            else "Health: %d/100 (%s)" % (health.score, health.band))
    return text if not tier else "%s. PC tier: %s" % (text, tier)
