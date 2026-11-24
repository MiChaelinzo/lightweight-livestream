"""Pure UI logic for the window: design tokens, contrast math, keyboard
shortcut table, sparkline ring buffer and the saved look preferences.

Nothing here imports tkinter, so all of it is tested without a display.
How the tokens look on a real screen is UNVERIFIED (see gui.py).
"""

import json
import os
from collections import deque

from .fileio import write_private_text

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_LIGHT, THEME_DARK)
UI_PREFS_FILENAME = "ui.json"
AA_TEXT_RATIO = 4.5  # WCAG 2.1 AA for normal text

# Colors. Each palette has the same keys. Text pairs are listed in TEXT_PAIRS.
PALETTES = {
    THEME_LIGHT: {
        "background": "#F5F6F8", "foreground": "#1A1A1A",
        "surface": "#FFFFFF", "muted": "#4A4A4A",
        "focus": "#0B57D0", "graph_line": "#0B57D0", "graph_back": "#FFFFFF",
        "graph_grid": "#E1E4EA",
        "start_bg": "#1B7F3B", "stop_bg": "#B00020", "emergency_bg": "#8F4600",
        "button_fg": "#FFFFFF",
        # Disabled big buttons: a pale tint of the same hue with dark text,
        # so "not now" is clear and still readable.
        "start_off_bg": "#DDEBE1", "stop_off_bg": "#F0DDE0",
        "emergency_off_bg": "#F0E3D4", "off_fg": "#4A4A4A",
        "card": "#FFFFFF", "card_border": "#B5B5B5",
        "accent": "#0B57D0", "accent_hover": "#0A47A8", "accent_fg": "#FFFFFF",
        "button_bg": "#E6E9F0", "button_hover": "#D6DBE6",
        "sidebar": "#E9ECF2", "nav_hover": "#D8DDE8",
        "banner_grey": "#555555", "banner_orange": "#A64F00",
        "banner_green": "#1B7F3B", "banner_red": "#B00020", "banner_fg": "#FFFFFF",
    },
    THEME_DARK: {
        "background": "#1E1F22", "foreground": "#EDEDED",
        "surface": "#2B2D31", "muted": "#C0C0C0",
        "focus": "#8AB4F8", "graph_line": "#8AB4F8", "graph_back": "#2B2D31",
        "graph_grid": "#3C3F45",
        "start_bg": "#1B7F3B", "stop_bg": "#B00020", "emergency_bg": "#8F4600",
        "button_fg": "#FFFFFF",
        "start_off_bg": "#2C3A31", "stop_off_bg": "#3E2D31",
        "emergency_off_bg": "#3D342A", "off_fg": "#C0C0C0",
        "card": "#33353A", "card_border": "#5A5D63",
        "accent": "#8AB4F8", "accent_hover": "#A8C7FA", "accent_fg": "#0F1F3D",
        "button_bg": "#3A3D44", "button_hover": "#4A4E57",
        "sidebar": "#26272B", "nav_hover": "#383B42",
        "banner_grey": "#555555", "banner_orange": "#A64F00",
        "banner_green": "#1B7F3B", "banner_red": "#B00020", "banner_fg": "#FFFFFF",
    },
}

# (foreground key, background key): every pair must reach AA_TEXT_RATIO.
TEXT_PAIRS = (
    ("foreground", "background"), ("foreground", "surface"),
    ("muted", "background"), ("muted", "surface"),
    ("button_fg", "start_bg"), ("button_fg", "stop_bg"),
    ("button_fg", "emergency_bg"),
    ("off_fg", "start_off_bg"), ("off_fg", "stop_off_bg"),
    ("off_fg", "emergency_off_bg"),
    ("focus", "background"), ("graph_line", "graph_back"),
    ("muted", "graph_back"),
    ("foreground", "card"), ("muted", "card"),
    ("accent_fg", "accent"), ("accent_fg", "accent_hover"),
    ("foreground", "button_bg"), ("foreground", "button_hover"),
    ("foreground", "sidebar"), ("muted", "sidebar"),
    ("foreground", "nav_hover"),
    ("banner_fg", "banner_grey"), ("banner_fg", "banner_orange"),
    ("banner_fg", "banner_green"), ("banner_fg", "banner_red"),
)

BIG_BUTTON_KINDS = ("start", "stop", "emergency")
BANNER_COLOR_NAMES = ("grey", "orange", "green", "red")


def big_button_colors(theme, kind, enabled):
    """(background, foreground) of the START / STOP / EMERGENCY buttons."""
    if kind not in BIG_BUTTON_KINDS:
        raise ValueError("unknown big button %r" % (kind,))
    colors = palette(theme)
    if enabled:
        return colors[kind + "_bg"], colors["button_fg"]
    return colors[kind + "_off_bg"], colors["off_fg"]


def banner_colors(theme, name):
    """(background, foreground) for a gui_controller banner color name."""
    if name not in BANNER_COLOR_NAMES:
        raise ValueError("unknown banner color %r" % (name,))
    colors = palette(theme)
    return colors["banner_" + name], colors["banner_fg"]


# Layered cards. ttk cannot blur or make anything translucent, so this is NOT
# glassmorphism: it is a native equivalent made of a lighter card color, a soft
# border and a thicker bottom edge for a hint of elevation. True glass exists
# only on the web page (web/style.css). How it looks on screen is UNVERIFIED.
ELEVATION_BORDER_WIDTH = {0: 0, 1: 1, 2: 2}


def card_style(theme, level=1):
    """Tk option values for a card at elevation 0 (flat), 1 or 2 (raised)."""
    if level not in ELEVATION_BORDER_WIDTH:
        raise ValueError("elevation must be one of %s, got %r"
                         % (sorted(ELEVATION_BORDER_WIDTH), level))
    colors = palette(theme)
    return {"background": colors["card"], "bordercolor": colors["card_border"],
            "borderwidth": ELEVATION_BORDER_WIDTH[level],
            "relief": "flat" if level == 0 else "solid"}

SPACING = {"small": 4, "medium": 8, "large": 16}
FONT_FAMILY = "Segoe UI"  # first choice; see pick_font_family for the others
FONT_PREFERENCE = ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu",
                   "Cantarell", "DejaVu Sans")
MONO_PREFERENCE = ("Consolas", "Menlo", "DejaVu Sans Mono", "Ubuntu Mono",
                   "Courier New")
FALLBACK_FONT = "TkDefaultFont"
FALLBACK_MONO_FONT = "TkFixedFont"
FONT_SIZES = {"title": 18, "step": 12, "text": 11, "button": 20, "log": 10,
              "value": 16, "caption": 10, "nav": 11}
COMPACT_FONT_SIZES = {"title": 14, "step": 10, "text": 9, "button": 14, "log": 9,
                      "value": 12, "caption": 8, "nav": 9}

# First window size wanted, the space kept free for the taskbar / title bar,
# and the smallest the window may be resized to.
PREFERRED_WINDOW = (960, 700)
SCREEN_MARGIN = (40, 90)
MIN_WINDOW = (720, 480)


def pick_font_family(available, preferred=FONT_PREFERENCE, fallback=FALLBACK_FONT):
    """First preferred family that exists (case-insensitive), else `fallback`.

    `available` is tkinter.font.families(); the preferred spelling is returned."""
    lookup = {name.lower() for name in available}
    for family in preferred:
        if family.lower() in lookup:
            return family
    return fallback


def fit_window(screen_width, screen_height):
    """((width, height), (min width, min height)) that fits the screen.

    A 1366x768 or 1280x720 laptop gets a window that is fully on screen; the
    page area scrolls when the content is taller."""
    width = min(PREFERRED_WINDOW[0], max(1, screen_width - SCREEN_MARGIN[0]))
    height = min(PREFERRED_WINDOW[1], max(1, screen_height - SCREEN_MARGIN[1]))
    return (width, height), (min(MIN_WINDOW[0], width), min(MIN_WINDOW[1], height))


WHEEL_NOTCH = 120  # Windows reports wheel movement in multiples of 120


def scroll_steps(button_number=None, delta=0):
    """Rows to scroll for one wheel event: negative is up, 0 is nothing.

    X11 sends Button-4 (up) and Button-5 (down). Windows sends delta in
    multiples of 120 and macOS sends small deltas; positive delta is up."""
    if button_number == 4:
        return -1
    if button_number == 5:
        return 1
    if not delta:
        return 0
    if abs(delta) >= WHEEL_NOTCH:
        return -int(delta / WHEEL_NOTCH)
    return -1 if delta > 0 else 1


def needs_scrollbar(content_height, view_height):
    """True when the content is taller than the visible area."""
    return content_height > view_height


MIN_POINTS_FOR_LINE = 2
EMPTY_GRAPH_TEXT = "Waiting for data"


def graph_is_empty(values):
    """True when a series has too few readings to draw a line (show a placeholder)."""
    return sum(1 for v in values if v is not None) < MIN_POINTS_FOR_LINE


def graph_grid_ys(height, lines=3):
    """Y positions of faint horizontal guide lines, evenly spaced inside the box."""
    return [round(height * i / (lines + 1), 1) for i in range(1, lines + 1)]


def font_sizes(compact):
    return COMPACT_FONT_SIZES if compact else FONT_SIZES


def spacing(compact):
    scale = 0.5 if compact else 1
    return {name: max(1, int(value * scale)) for name, value in SPACING.items()}


def palette(theme):
    """Colors for a theme name; unknown names give the light palette."""
    return PALETTES.get(theme, PALETTES[THEME_LIGHT])


def toggle_theme(theme):
    return THEME_LIGHT if theme == THEME_DARK else THEME_DARK


def _channel(value):
    value /= 255.0
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color):
    """WCAG relative luminance of '#RRGGBB'."""
    if not (isinstance(color, str) and len(color) == 7 and color[0] == "#"):
        raise ValueError("color must look like #RRGGBB: %r" % (color,))
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(first, second):
    """WCAG contrast ratio between two colors, 1.0 to 21.0."""
    a, b = relative_luminance(first), relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def failing_pairs(theme):
    """Text pairs of a theme below AA, as (fg key, bg key, ratio). Empty is good."""
    colors = palette(theme)
    bad = []
    for fg, bg in TEXT_PAIRS:
        ratio = contrast_ratio(colors[fg], colors[bg])
        if ratio < AA_TEXT_RATIO:
            bad.append((fg, bg, round(ratio, 2)))
    return bad


# -- keyboard shortcuts --------------------------------------------------------
# (tk key sequence, action id, accelerator text shown in labels)
SHORTCUTS = (
    ("<Control-Return>", "start", "Ctrl+Enter"),
    ("<Control-period>", "stop", "Ctrl+."),
    ("<Control-Shift-E>", "emergency", "Ctrl+Shift+E"),
    ("<Control-Shift-D>", "theme", "Ctrl+Shift+D"),
    ("<Control-Shift-C>", "compact", "Ctrl+Shift+C"),
    ("<Control-Key-1>", "page:dashboard", "Ctrl+1"),
    ("<Control-Key-2>", "page:setup", "Ctrl+2"),
    ("<Control-Key-3>", "page:scenes", "Ctrl+3"),
    ("<Control-Key-4>", "page:overlays", "Ctrl+4"),
    ("<Control-Key-5>", "page:recording", "Ctrl+5"),
    ("<Control-Key-6>", "page:advanced", "Ctrl+6"),
)


def shortcut_for(action):
    """Accelerator text for an action id, or ''."""
    for _sequence, name, text in SHORTCUTS:
        if name == action:
            return text
    return ""


def with_accelerator(label, action):
    text = shortcut_for(action)
    return "%s (%s)" % (label, text) if text else label


# -- sparkline data ------------------------------------------------------------
class RingBuffer:
    """Fixed-size history of numbers. Memory never grows past `capacity`.

    None means "no reading" and is kept so gaps show up in the graph.
    """

    def __init__(self, capacity=60):
        if capacity < 2:
            raise ValueError("capacity must be at least 2")
        self.capacity = capacity
        self._items = deque(maxlen=capacity)

    def append(self, value):
        self._items.append(None if value is None else float(value))

    def values(self):
        return list(self._items)

    def __len__(self):
        return len(self._items)


def downsample(values, points):
    """Reduce values to at most `points` by averaging equal buckets.

    A bucket with no readings stays None. Short lists are returned unchanged.
    """
    if points < 1:
        raise ValueError("points must be at least 1")
    if len(values) <= points:
        return list(values)
    result = []
    for index in range(points):
        start = index * len(values) // points
        end = (index + 1) * len(values) // points
        bucket = [v for v in values[start:end] if v is not None]
        result.append(sum(bucket) / len(bucket) if bucket else None)
    return result


def sparkline_points(values, width, height, pad=2):
    """Canvas coordinates [x1, y1, x2, y2, ...] for the readings.

    Readings of None are skipped. A flat line is drawn mid-height.
    Returns [] when fewer than two readings exist.
    """
    pairs = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pairs) < 2:
        return []
    low = min(v for _, v in pairs)
    high = max(v for _, v in pairs)
    span = high - low
    steps = max(len(values) - 1, 1)
    inner_w, inner_h = width - 2 * pad, height - 2 * pad
    coords = []
    for index, value in pairs:
        x = pad + inner_w * index / steps
        fraction = 0.5 if span == 0 else (value - low) / span
        y = pad + inner_h * (1 - fraction)
        coords.extend((round(x, 1), round(y, 1)))
    return coords


# Performance panel series, in display order: (name, title).
SERIES = (("fps", "FPS"), ("bitrate", "Bitrate"), ("speed", "Speed"),
          ("drops", "Drops"), ("ram", "RAM %"), ("cpu", "CPU %"), ("gpu", "GPU %"))


class PerformanceBuffers:
    """One RingBuffer per series. record() takes HealthTracker.summary() and a
    telemetry.Sample (or None) and appends one reading to each.

    "drops" is dropped frames since the previous reading (not the running
    total), so the graph shows when drops happen. Unknown values stay None.
    """

    def __init__(self, capacity=60):
        self.buffers = {name: RingBuffer(capacity) for name, _ in SERIES}
        self._last_dropped = None

    def record(self, summary, sample=None):
        total = summary.get("dropped_frames")
        drops = None
        if total is not None:
            drops = 0 if self._last_dropped is None else max(0, total - self._last_dropped)
            self._last_dropped = total
        readings = {
            "fps": summary.get("recent_fps"),
            "bitrate": summary.get("recent_bitrate_kbps"),
            "speed": summary.get("recent_speed"),
            "drops": drops,
            "ram": getattr(sample, "ram_percent", None),
            "cpu": getattr(sample, "cpu_percent", None),
            "gpu": getattr(sample, "gpu_percent", None),
        }
        for name, value in readings.items():
            self.buffers[name].append(value)

    def values(self, name):
        return self.buffers[name].values()


class RedrawGate:
    """Allows a redraw at most once per `interval` seconds."""

    def __init__(self, interval=1.0):
        self.interval = interval
        self._last = None

    def ready(self, now):
        if self._last is None or now - self._last >= self.interval:
            self._last = now
            return True
        return False


# -- saved look preferences ----------------------------------------------------
def ui_prefs_path(prefs_file):
    return os.path.join(os.path.dirname(prefs_file), UI_PREFS_FILENAME)


def load_ui_prefs(path):
    """{'theme': ..., 'compact': ...}, with defaults for anything bad or missing."""
    prefs = {"theme": THEME_LIGHT, "compact": False}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return prefs
    if isinstance(data, dict):
        if data.get("theme") in THEMES:
            prefs["theme"] = data["theme"]
        if isinstance(data.get("compact"), bool):
            prefs["compact"] = data["compact"]
    return prefs


def save_ui_prefs(path, theme, compact):
    """Write only the theme name and the compact flag (no secrets), mode 0600."""
    if theme not in THEMES:
        raise ValueError("unknown theme: %r" % (theme,))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    write_private_text(path, json.dumps(
        {"theme": theme, "compact": bool(compact)}, indent=2) + "\n")
