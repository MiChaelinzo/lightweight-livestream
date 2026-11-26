"""Quality presets. Pure data, no side effects."""

from collections import namedtuple

Preset = namedtuple(
    "Preset", "name width height fps video_kbps audio_kbps x264_preset description"
)

PRESETS = {
    p.name: p
    for p in (
        Preset("potato", 640, 360, 24, 700, 64, "ultrafast",
               "Oldest PCs, weak Wi-Fi, mobile emulators. Lowest CPU use."),
        Preset("light", 854, 480, 30, 1000, 96, "ultrafast",
               "Old laptops. Good default for Arknights / Limbus Company."),
        Preset("balanced", 1280, 720, 30, 2500, 128, "veryfast",
               "Decent PCs or any PC with a hardware encoder."),
        Preset("potato_2000", 640, 360, 15, 2000, 64, "ultrafast",
               "Potato Stream 2000k: 15 fps, 360p, ultrafast. Built from the "
               "measured CPU levers (frame rate and size)."),
        Preset("potato_4000", 854, 480, 15, 4000, 96, "ultrafast",
               "Potato Stream 4000k: 15 fps, 480p, ultrafast."),
        Preset("720p60", 1280, 720, 60, 4000, 128, "veryfast",
               "Fast action games. Needs a hardware encoder or a good CPU."),
        # One-click profile presets (design choices, UNVERIFIED on real PCs).
        # 30 or 60 fps only: 40 fps judders on 60 Hz displays and platforms
        # expect 30 or 60. Bitrates fit inside every platform cap they are
        # meant for (see bandwidth.PLATFORM_VIDEO_CAP_KBPS).
        Preset("office_laptop", 1600, 900, 30, 3500, 128, "veryfast",
               "Office laptop: 900p30 at 3500k. 30 fps, not 40, because 40 fps "
               "judders on 60 Hz screens."),
        Preset("budget_gaming", 1920, 1080, 60, 6000, 128, "veryfast",
               "Budget gaming PC: 1080p60 at 6000k (the Twitch cap). Needs a "
               "hardware encoder such as NVENC."),
    )
}

# Presets chosen only by name (--profile, --preset). Automatic upload-speed
# recommendations skip them so a fast connection never picks 1080p60 for a
# PC that cannot encode it.
PROFILE_ONLY_PRESETS = frozenset(("office_laptop", "budget_gaming"))

DEFAULT_PRESET = "light"


def get_preset(name):
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(
            "Unknown preset %r. Choose one of: %s" % (name, ", ".join(PRESETS))
        )


def parse_resolution(text):
    """'1280x720' -> (1280, 720). Dimensions must be positive and even."""
    try:
        w, h = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise ValueError("Resolution must look like 1280x720, got %r" % text)
    if w <= 0 or h <= 0 or w % 2 or h % 2:
        raise ValueError("Resolution must be positive and even, got %r" % text)
    return w, h
