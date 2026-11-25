"""Performance profiles and stream presets. Pure data and resolvers.

A performance profile picks an existing quality preset (numbers stay in
presets.PRESETS) plus extra knobs: x264 tune, thread cap, Gaming First core
reservation, keyframe interval, rate-control buffer and a default audio
profile. A stream preset bundles a platform, a performance profile and an
audio profile. What each knob does is a mechanism (fewer encoder threads,
smaller buffer); no game FPS or CPU savings are claimed. Effects on real
games are UNVERIFIED.
"""

import os
from collections import namedtuple

from .audio import AUDIO_PROFILES
from .bandwidth import PLATFORM_VIDEO_CAP_KBPS
from .command import DEFAULT_KEYINT_SECONDS, DEFAULT_X264_TUNE
from .hardware import LEAN_BUFSIZE_SECONDS, cap_preset_name
from .presets import PRESETS

PerfProfile = namedtuple(
    "PerfProfile",
    "name preset_name x264_tune thread_cap gaming_first reserved_cores "
    "audio_profile keyint_seconds bufsize_seconds description")

PerfTuning = namedtuple("PerfTuning", "threads reserved_cores")

StreamPreset = namedtuple(
    "StreamPreset", "name platform perf_profile audio_profile description")

NO_TUNE = ""                 # StreamSettings.x264_tune value that omits -tune
POTATO_THREAD_CAP = 2        # same cap hardware.py uses for x264 on weak GPUs
LOW_LATENCY_KEYINT_SECONDS = 1

PERF_PROFILES = {
    p.name: p
    for p in (
        PerfProfile("potato", "potato", DEFAULT_X264_TUNE, POTATO_THREAD_CAP,
                    True, 1, None, DEFAULT_KEYINT_SECONDS, None,
                    "Lowest CPU use: smallest preset, two encoder threads, one core "
                    "left free, no audio filters."),
        PerfProfile("balanced", "balanced", DEFAULT_X264_TUNE, None,
                    True, 1, "gaming", DEFAULT_KEYINT_SECONDS, None,
                    "Everyday default: 720p30, one core left free for the game."),
        PerfProfile("quality", "720p60", NO_TUNE, None,
                    False, 0, "music", DEFAULT_KEYINT_SECONDS, None,
                    "Best picture the hardware profile allows: no -tune, all cores."),
        PerfProfile("competitive", "720p60", DEFAULT_X264_TUNE, None,
                    True, 2, "gaming", DEFAULT_KEYINT_SECONDS, None,
                    "Fast games: 720p60 with two cores left free for the game."),
        PerfProfile("low_latency", "balanced", DEFAULT_X264_TUNE, None,
                    True, 1, "gaming", LOW_LATENCY_KEYINT_SECONDS,
                    LEAN_BUFSIZE_SECONDS,
                    "Less delay: half-second rate-control buffer and a keyframe "
                    "every second."),
    )
}

STREAM_PRESETS = {
    p.name: p
    for p in (
        StreamPreset("youtube_gaming", "youtube", "quality", "gaming",
                     "YouTube game streams: quality profile (capped by your hardware)."),
        StreamPreset("twitch_gaming", "twitch", "competitive", "gaming",
                     "Twitch game streams: 720p60 with cores left for the game."),
        StreamPreset("kick", "custom", "balanced", "gaming",
                     "Kick: you supply the ingest address with --url (it is not built in)."),
        StreamPreset("podcast", "youtube", "potato", "podcast",
                     "Talk shows: tiny video, voice-focused audio."),
        StreamPreset("just_chatting", "twitch", "balanced", "commentary",
                     "Just Chatting: balanced video, clear voice."),
        StreamPreset("tutorial", "youtube", "balanced", "commentary",
                     "Tutorials: balanced video, clear voice over the screen."),
        StreamPreset("esports", "twitch", "low_latency", "gaming",
                     "Live competition: lowest delay settings."),
    )
}

for _profile in PERF_PROFILES.values():
    assert _profile.preset_name in PRESETS, _profile.name
    assert _profile.audio_profile is None or _profile.audio_profile in AUDIO_PROFILES
for _stream in STREAM_PRESETS.values():
    assert _stream.perf_profile in PERF_PROFILES, _stream.name
    assert _stream.audio_profile in AUDIO_PROFILES, _stream.name
    assert _stream.platform in PLATFORM_VIDEO_CAP_KBPS, _stream.name


def get_perf_profile(name):
    try:
        return PERF_PROFILES[name]
    except KeyError:
        raise ValueError("Unknown profile %r. Choose one of: %s"
                         % (name, ", ".join(PERF_PROFILES)))


def get_stream_preset(name):
    try:
        return STREAM_PRESETS[name]
    except KeyError:
        raise ValueError("Unknown stream preset %r. Choose one of: %s"
                         % (name, ", ".join(STREAM_PRESETS)))


def profile_preset_name(profile_name, hardware_profile=None):
    """Quality preset for a performance profile, capped by the hardware profile."""
    name = get_perf_profile(profile_name).preset_name
    return cap_preset_name(hardware_profile, name) if hardware_profile else name


def stream_preset_bitrate_cap(stream_name):
    """Platform video bitrate cap (kbps) for a stream preset."""
    return PLATFORM_VIDEO_CAP_KBPS[get_stream_preset(stream_name).platform]


def resolve_tuning(profile_name, cpu_count=None):
    """Threads and reserved cores for a profile on a machine with cpu_count cores.

    Gaming First: threads = max(1, cpu_count - reserved_cores), then the
    profile's thread cap. Without Gaming First only the cap applies.
    threads is None when ffmpeg should choose. cpu_count defaults to os.cpu_count().
    """
    profile = get_perf_profile(profile_name)
    cpus = cpu_count or os.cpu_count() or 1
    if profile.gaming_first:
        threads = max(1, cpus - profile.reserved_cores)
        reserved = min(profile.reserved_cores, cpus - 1)
    else:
        threads = cpus if profile.thread_cap else None
        reserved = 0
    if threads is not None and profile.thread_cap:
        threads = min(threads, profile.thread_cap)
    return PerfTuning(threads, reserved)


def affinity_cpus(cpu_count, reserved_cores):
    """CPU ids ffmpeg may use: every core except the first reserved_cores.

    Returns None when nothing is reserved (no affinity change)."""
    if not reserved_cores or reserved_cores <= 0 or cpu_count <= 1:
        return None
    reserved = min(reserved_cores, cpu_count - 1)
    return set(range(reserved, cpu_count))
