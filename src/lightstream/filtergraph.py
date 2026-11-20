"""Small helpers that build FFmpeg filter text. Pure functions."""

import re

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
OVERLAY_MARGIN = 10
MIN_PERCENT, MAX_PERCENT = 5, 35   # a small overlay keeps scaling work low
IMAGE_FPS = 2
DEFAULT_FONT_SIZE = 24

# Characters that would end or split a filter option; refused instead of
# escaped, so no two-level FFmpeg escaping rules are needed.
_UNSAFE_PATH_CHARS = set("',;[]|")
_SAFE_TEXT = re.compile(r"^[\w .!?#@()+\-/&]+$")


def letterbox_filter(width, height):
    """Keep the source aspect ratio; letterbox the rest instead of stretching."""
    return ("scale=%d:%d:flags=fast_bilinear:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (width, height, width, height))


def filter_path(path, what="path"):
    """Path made safe for a filter option value (forward slashes, escaped colon)."""
    if not path:
        raise ValueError("%s must not be empty" % what)
    bad = sorted(set(path) & _UNSAFE_PATH_CHARS)
    if bad:
        raise ValueError("%s %r contains unsupported characters %s"
                         % (what, path, " ".join(bad)))
    return path.replace("\\", "/").replace(":", "\\:")


def filter_text(text):
    """On-screen text restricted to a safe character set (see _SAFE_TEXT)."""
    if not text or not _SAFE_TEXT.match(text):
        raise ValueError(
            "Text %r may only use letters, digits, spaces and . ! ? # @ ( ) + - / &"
            % (text,))
    return text


def overlay_position(corner, margin_x=OVERLAY_MARGIN, margin_y=OVERLAY_MARGIN):
    """x, y expressions for the overlay filter (W/H main size, w/h overlay size)."""
    x = str(margin_x) if corner.endswith("left") else "W-w-%d" % margin_x
    y = str(margin_y) if corner.startswith("top") else "H-h-%d" % margin_y
    return x, y


def text_position(corner, margin_x=OVERLAY_MARGIN, margin_y=OVERLAY_MARGIN):
    """x, y expressions for drawtext (w/h frame size, tw/th text size)."""
    x = str(margin_x) if corner.endswith("left") else "w-tw-%d" % margin_x
    y = str(margin_y) if corner.startswith("top") else "h-th-%d" % margin_y
    return x, y
