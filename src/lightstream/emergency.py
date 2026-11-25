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

Neither mode runs by itself. The CLI flags and the GUI Emergency button are
the person's opt-in. What each mode does is a mechanism; the effect on real
connections and games is UNVERIFIED.
"""

from .autoscale import DEFAULT_FLOOR_PRESET, MIN_LADDER_KBPS
from .bandwidth import PLATFORM_VIDEO_CAP_KBPS, recommend
from .hardware import LEAN_BUFSIZE_SECONDS
from .perf_profiles import POTATO_THREAD_CAP
from .presets import PRESETS

WEAK_BITRATE_FACTOR = 0.6        # share of the chosen video bitrate kept
WEAK_KEYINT_SECONDS = 1          # keyframe every second: faster recovery
WEAK_BUFSIZE_SECONDS = 2.0       # rate-control buffer in seconds of video


def emergency_settings(settings):
    """StreamSettings with the safest known values. Never raises a value."""
    floor = PRESETS[DEFAULT_FLOOR_PRESET]
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
