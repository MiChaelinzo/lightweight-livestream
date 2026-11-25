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
from .hardware import LEAN_BUFSIZE_SECONDS, cap_preset_name, classify_gpus, parse_gpu_names
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
LOW_RAM_MB = 4096            # at or below this, never start above the 'light' preset
POTATO_RAM_MB = 2048         # at or below this the 360p15 potato_2000 profile
WEAK_CPU_THREADS = 2         # at or below this the PC is treated as weak
CAPABLE_CPU_THREADS = 4      # office_laptop and budget_gaming need at least this many
CAPABLE_RAM_MB = 8192        # ... and at least this much memory
# Hardware profiles with no usable hardware encoder, or an old one: stay at 480p.
INTEL_HD_PROFILES = ("intel_hd", "intel_hd_optimized")

PERF_PROFILES = {
    p.name: p
    for p in (
        PerfProfile("potato", "potato", DEFAULT_X264_TUNE, POTATO_THREAD_CAP,
                    True, 1, None, DEFAULT_KEYINT_SECONDS, None,
                    "Lowest CPU use: smallest preset, two encoder threads, one core "
                    "left free, no audio filters."),
        PerfProfile("potato_2000", "potato_2000", DEFAULT_X264_TUNE, 1,
                    True, 1, None, DEFAULT_KEYINT_SECONDS, LEAN_BUFSIZE_SECONDS,
                    "Potato Stream 2000k for about 512 MB and a weak CPU: 360p15, "
                    "one encoder thread, lean buffer, no audio filters."),
        PerfProfile("potato_4000", "potato_4000", DEFAULT_X264_TUNE, 2,
                    True, 1, None, DEFAULT_KEYINT_SECONDS, LEAN_BUFSIZE_SECONDS,
                    "Potato Stream 4000k: 480p15, two encoder threads, lean buffer, "
                    "no audio filters."),
        # One-click profiles. The numbers are design choices, UNVERIFIED on real
        # PCs. Why not 720p at 600 to 1000 kbps for a weak PC: x264 at 720p needs
        # more bits per pixel than that to avoid blocks in motion, and a smaller
        # frame costs less CPU than a thinner bitrate, so potato_pc uses 480p30
        # at 1000 kbps (the light preset). Why not 40 fps for an office laptop:
        # 40 fps judders on 60 Hz displays and platforms expect 30 or 60.
        PerfProfile("potato_pc", "light", DEFAULT_X264_TUNE, POTATO_THREAD_CAP,
                    True, 1, None, DEFAULT_KEYINT_SECONDS, LEAN_BUFSIZE_SECONDS,
                    "Potato PC: 480p30 at 1000k, two encoder threads, one core left "
                    "free, lean buffer, no audio filters."),
        PerfProfile("office_laptop", "office_laptop", DEFAULT_X264_TUNE, None,
                    True, 1, "commentary", DEFAULT_KEYINT_SECONDS, None,
                    "Office laptop: 900p30 at 3500k (fits every platform cap, 30 fps "
                    "because 40 fps judders on 60 Hz screens), one core left free."),
        PerfProfile("budget_gaming", "budget_gaming", DEFAULT_X264_TUNE, None,
                    True, 1, "gaming", DEFAULT_KEYINT_SECONDS, None,
                    "Budget gaming PC (for example GTX 1650): 1080p60 at 6000k. "
                    "Needs a hardware encoder (NVENC); x264 on the CPU will not keep up."),
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
        StreamPreset("facebook_live", "facebook", "balanced", "commentary",
                     "Facebook Live: balanced video capped at 4000 kbps (conservative, not from Facebook docs)."),
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


def recommend_profile(cpu_count, ram_mb, gpu_name=None, hardware_profile=None):
    """Name of the one-click profile that suits this PC. Pure, deterministic.

    Unknown cpu_count or ram_mb (None) is never treated as weak. Rules, first
    match wins (design reasoning, UNVERIFIED on real PCs):
      1. two or fewer CPU threads, or at most LOW_RAM_MB: potato_2000 at
         POTATO_RAM_MB or less, else potato_pc.
      2. Intel HD graphics: potato_pc (the hardware profile caps presets at 480p).
      3. an NVIDIA GPU with NVENC (hardware profile "nvidia") and a capable
         CPU and RAM: budget_gaming.
      4. a capable CPU and RAM otherwise: office_laptop.
      5. anything else: balanced.
    gpu_name is a GPU name or lspci/wmic text; hardware_profile overrides it.
    """
    if hardware_profile is None:
        hardware_profile = classify_gpus(parse_gpu_names(gpu_name or ""))
    if ram_mb is not None and ram_mb <= POTATO_RAM_MB:
        return "potato_2000"
    if (cpu_count is not None and 0 < cpu_count <= WEAK_CPU_THREADS) or \
            (ram_mb is not None and ram_mb <= LOW_RAM_MB):
        return "potato_pc"
    if hardware_profile in INTEL_HD_PROFILES:
        return "potato_pc"
    capable = (cpu_count is not None and cpu_count >= CAPABLE_CPU_THREADS
               and ram_mb is not None and ram_mb >= CAPABLE_RAM_MB)
    if capable and hardware_profile == "nvidia":
        return "budget_gaming"
    if capable:
        return "office_laptop"
    return "balanced"


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
