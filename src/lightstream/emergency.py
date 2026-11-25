"""Emergency mode and weak connection mode. Pure functions over StreamSettings.

Emergency: the safest settings the app already knows. Size, frame rate,
bitrate and x264 preset come from the potato preset (the autoscale ladder
floor), the encoder thread count is capped like the potato profile, scene
overlays and webcam are dropped, AI audio is switched off and the rate-control
buffer is the small lean one. Values are never raised above what the person
had.

Weak connection: for a poor or unstable uplink. Lower bitrate (a fixed factor,
further limited by bandwidth.recommend when the upload speed is known), a
shorter keyframe interval so a viewer recovers sooner after packet loss, and
a longer rate-control buffer so short upload dips are absorbed.

Potato Stream: a CPU-first profile for very weak machines, built only on what
the 0.12 spikes measured to cut CPU: lower frame rate, smaller size, one or two
encoder threads and x264 ultrafast. Targets are 2000 and 4000 kbps. Grayscale
and skipping static frames are separate opt-ins, not CPU savers (grayscale
raised CPU in the measurements).

None of these modes runs by itself. The CLI flags and the GUI Emergency button are
the person's opt-in. What each mode does is a mechanism; the effect on real
connections and games is UNVERIFIED.
"""

from .autoscale import DEFAULT_FLOOR_PRESET, MIN_LADDER_KBPS
from .bandwidth import PLATFORM_VIDEO_CAP_KBPS, recommend
from .hardware import LEAN_BUFSIZE_SECONDS
from .perf_profiles import POTATO_THREAD_CAP, get_perf_profile
from .presets import PRESETS

POTATO_STREAM_PROFILES = {2000: "potato_2000", 4000: "potato_4000"}

WEAK_BITRATE_FACTOR = 0.6        # share of the chosen video bitrate kept
WEAK_KEYINT_SECONDS = 1          # keyframe every second: faster recovery
WEAK_BUFSIZE_SECONDS = 2.0       # rate-control buffer in seconds of video


def emergency_settings(settings, constant_size=False):
    """StreamSettings with the safest known values. Never raises a value.

    constant_size keeps the picture size and the whole audio chain (audio
    bitrate, noise suppression, audio filter: audio has priority over
    video) and cuts only frame rate, video bitrate, x264 preset, encoder
    threads, the lean buffer and the scene (overlays, webcam with chromakey and blur).
    Persistent ingest and auto-survival use it because the output size must
    not change inside a session.
    """
    floor = PRESETS[DEFAULT_FLOOR_PRESET]
    if constant_size:
        return settings._replace(
            fps=min(settings.fps, floor.fps),
            video_kbps=min(settings.video_kbps, floor.video_kbps),
            x264_preset=floor.x264_preset,
            threads=(POTATO_THREAD_CAP if not settings.threads
                     else min(settings.threads, POTATO_THREAD_CAP)),
            scene=None,
            bufsize_seconds=LEAN_BUFSIZE_SECONDS)
    if settings.width * settings.height > floor.width * floor.height:
        width, height = floor.width, floor.height
    else:
        width, height = settings.width, settings.height
    threads = (POTATO_THREAD_CAP if not settings.threads
               else min(settings.threads, POTATO_THREAD_CAP))
    return settings._replace(
        width=width, height=height,
        fps=min(settings.fps, floor.fps),
        video_kbps=min(settings.video_kbps, floor.video_kbps),
        audio_kbps=min(settings.audio_kbps, floor.audio_kbps),
        x264_preset=floor.x264_preset,
        threads=threads,
        scene=None,            # overlays and webcam need extra filters and inputs
        noise="off", noise_model=None, audio_filter=None,
        bufsize_seconds=LEAN_BUFSIZE_SECONDS)


def weak_connection_settings(settings, upload_kbps=None):
    """StreamSettings tuned for a poor uplink. upload_kbps (measured or typed)
    lowers the bitrate further when bandwidth.recommend says it must."""
    kbps = max(MIN_LADDER_KBPS, int(settings.video_kbps * WEAK_BITRATE_FACTOR))
    if upload_kbps:
        platform = (settings.platform if settings.platform in PLATFORM_VIDEO_CAP_KBPS
                    else "custom")
        kbps = min(kbps, recommend(upload_kbps, platform).video_kbps)
    return settings._replace(
        video_kbps=min(kbps, settings.video_kbps),
        keyint_seconds=WEAK_KEYINT_SECONDS,
        bufsize_seconds=WEAK_BUFSIZE_SECONDS)


def failover_settings(settings):
    """StreamSettings that send to the backup ingest (same stream key).
    The backup is a plain rtmp://host/app address like a custom primary."""
    if not settings.backup_url:
        raise ValueError("No backup ingest address is set")
    return settings._replace(platform="custom", custom_url=settings.backup_url)


def potato_stream_settings(settings, target_kbps, grayscale=False, skip_static=False):
    """StreamSettings for Potato Stream at 2000 or 4000 kbps.

    Size, fps and threads come from the potato_2000 / potato_4000 presets and profiles and are never raised
    above what the person had (a smaller size or lower fps is kept). The
    bitrate is the chosen target. Scenes are dropped (extra filters and
    inputs), audio filters off, lean buffer, ultrafast. grayscale and
    skip_static add filters (see StreamSettings); neither lowers CPU for sure.
    """
    if target_kbps not in POTATO_STREAM_PROFILES:
        raise ValueError("Potato Stream targets are %s kbps, got %r" % (
            " and ".join(str(k) for k in sorted(POTATO_STREAM_PROFILES)), target_kbps))
    profile = get_perf_profile(POTATO_STREAM_PROFILES[target_kbps])
    preset = PRESETS[profile.preset_name]
    width, height = preset.width, preset.height
    if settings.width * settings.height <= width * height:
        width, height = settings.width, settings.height
    return settings._replace(
        width=width, height=height, fps=min(settings.fps, preset.fps),
        video_kbps=target_kbps, audio_kbps=min(settings.audio_kbps, preset.audio_kbps),
        x264_preset=preset.x264_preset, threads=profile.thread_cap, scene=None,
        noise="off", noise_model=None, audio_filter=None,
        bufsize_seconds=LEAN_BUFSIZE_SECONDS,
        grayscale=bool(grayscale), skip_static=bool(skip_static))
