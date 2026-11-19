"""Small helpers that build FFmpeg filter text. Pure functions."""

import re

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
