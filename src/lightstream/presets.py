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
        Preset("720p60", 1280, 720, 60, 4000, 128, "veryfast",
               "Fast action games. Needs a hardware encoder or a good CPU."),
    )
}

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
