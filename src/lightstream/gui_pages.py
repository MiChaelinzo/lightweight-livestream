"""State and logic for the sidebar GUI pages. No tkinter, so it is unit tested.

gui.py only turns these values into ttk widgets. Nothing here changes a
setting unless the person clicks Apply (apply_recommendation returns a new
prefs dict; the caller decides to keep it). No stream key is handled here.
"""

from collections import namedtuple

from . import scene_collections
from .adaptive import (KIND_BITRATE_REDUCTION, KIND_PRESET_DOWNGRADE,
                       Recommendation)
from .filtergraph import (CORNERS, DEFAULT_FONT_SIZE, MAX_PERCENT, MIN_PERCENT,
                          OVERLAY_MARGIN)
from .hardware import PROFILES
from .overlays import (CLOCK_FORMATS, DEFAULT_IMAGE_PERCENT, KIND_CLOCK, KIND_IMAGE,
                       KIND_TEXT, MAX_FONT_SIZE, MAX_OVERLAYS, MIN_FONT_SIZE,
                       OVERLAY_KINDS, drawtext_stage, image_stage,
                       parse_overlay)
from .audio import AUDIO_PROFILES
from .perf_profiles import PERF_PROFILES
from .presets import PRESETS

# (page id, sidebar label). Pages are built lazily by gui.py on first visit.
PAGES = (
    ("dashboard", "Dashboard"),
    ("setup", "Setup wizard"),
    ("scenes", "Scenes"),
    ("overlays", "Overlays"),
    ("recording", "Recording"),
    ("advanced", "Advanced"),
)
DEFAULT_PAGE = "dashboard"

AUTO_HARDWARE_LABEL = "Detect automatically"
PREVIEW_INPUT_LABEL = "in"
PREVIEW_OUTPUT_LABEL = "out"
PREVIEW_FRAME_WIDTH = 1280
PREVIEW_PLACEHOLDER = "No overlay selected."
MISSING_VALUE = "-"

HealthCard = namedtuple("HealthCard", "title value")


def page_ids():
    return [page_id for page_id, _ in PAGES]


def page_label(page_id):
    for known, label in PAGES:
        if known == page_id:
            return label
    raise ValueError("Unknown page %r" % page_id)


def resolve_page(page_id):
    """Known page id, or the dashboard for anything else."""
    return page_id if page_id in page_ids() else DEFAULT_PAGE


def hardware_choices():
    """Dropdown labels for the hardware profile, automatic first."""
    return [AUTO_HARDWARE_LABEL] + list(PROFILES)


def hardware_pref(label):
    """Saved value for a dropdown label ('' means detect automatically)."""
    return "" if label == AUTO_HARDWARE_LABEL else label


def hardware_label(pref):
    return pref if pref in PROFILES else AUTO_HARDWARE_LABEL


AUTO_PROFILE_LABEL = "Automatic (use Strength above)"
NO_AUDIO_PROFILE_LABEL = "None"


def profile_choices():
    """Dropdown labels for the performance profile, 'automatic' first."""
    return [AUTO_PROFILE_LABEL] + list(PERF_PROFILES)


def profile_pref(label):
    """Saved value for a profile label ('' means none chosen)."""
    return label if label in PERF_PROFILES else ""


def profile_label(pref):
    return pref if pref in PERF_PROFILES else AUTO_PROFILE_LABEL


def audio_profile_choices():
    return [NO_AUDIO_PROFILE_LABEL] + list(AUDIO_PROFILES)


def audio_profile_pref(label):
    return label if label in AUDIO_PROFILES else ""


def audio_profile_label(pref):
    return pref if pref in AUDIO_PROFILES else NO_AUDIO_PROFILE_LABEL


# -- dashboard ---------------------------------------------------------------
def _number(value, template):
    return MISSING_VALUE if value is None else template % value


def health_cards(summary):
    """Cards for the dashboard from HealthTracker.summary()."""
    return [
        HealthCard("Speed", _number(summary.get("recent_speed"), "%.2fx")),
        HealthCard("Frames per second", _number(summary.get("recent_fps"), "%.0f")),
        HealthCard("Bitrate", _number(summary.get("recent_bitrate_kbps"), "%.0f kbps")),
        HealthCard("Dropped frames", str(summary.get("dropped_frames", 0))),
        HealthCard("Reconnects", str(summary.get("reconnects", 0))),
    ]


UNKNOWN_TEXT = "n/a"


def _telemetry_text(value, template):
    return UNKNOWN_TEXT if value is None else template % value


def telemetry_cards(sample):
    """Cards for the telemetry row from a telemetry.Sample ('n/a' when unknown)."""
    return [
        HealthCard("CPU", _telemetry_text(sample.cpu_percent, "%.0f%%")),
        HealthCard("RAM", _telemetry_text(sample.ram_percent, "%.0f%%")),
        HealthCard("CPU temp", _telemetry_text(sample.cpu_temp_c, "%.0f C")),
        HealthCard("GPU", _telemetry_text(sample.gpu_percent, "%.0f%%")),
        HealthCard("GPU temp", _telemetry_text(sample.gpu_temp_c, "%.0f C")),
        HealthCard("ffmpeg memory", _telemetry_text(sample.process_rss_mb, "%.0f MB")),
    ]


class RecommendationInbox:
    """Recommendations shown on the dashboard, minus the dismissed ones.

    Dismissing hides a suggestion (matched by kind and value) for the rest of
    the session so a timer refresh does not bring it back."""

    def __init__(self):
        self._dismissed = set()

    @staticmethod
    def _key(rec):
        return (rec.kind, rec.value)

    def visible(self, recommendations):
        return [r for r in recommendations if self._key(r) not in self._dismissed]

    def dismiss(self, rec):
        self._dismissed.add(self._key(rec))


def can_apply(rec):
    """Only suggestions with a concrete value can be applied to the settings."""
    return rec.kind in (KIND_PRESET_DOWNGRADE, KIND_BITRATE_REDUCTION) \
        and rec.value is not None


def apply_recommendation(rec, prefs):
    """(new prefs, message). Called only from the Apply button; prefs is not
    modified in place. The change takes effect the next time a stream starts."""
    if not isinstance(rec, Recommendation) or not can_apply(rec):
        return dict(prefs), "This suggestion has no setting to change. %s" % rec.message
    updated = dict(prefs)
    if rec.kind == KIND_PRESET_DOWNGRADE:
        if rec.value not in PRESETS:
            raise ValueError("Unknown preset %r" % (rec.value,))
        updated["preset"] = rec.value
        updated["profile"] = ""  # a chosen profile would override the new strength
        return updated, "Strength set to %s. It applies the next time you press START." % rec.value
    updated["bitrate"] = str(rec.value)
    return updated, "Video speed set to %d kbps. It applies the next time you press START." % rec.value


# -- scenes ------------------------------------------------------------------
def _attempt(action):
    """(ok, message) so the GUI shows plain text instead of a traceback."""
    try:
        return True, action()
    except (ValueError, OSError) as exc:
        return False, str(exc)


def scene_names(scenes_file):
    try:
        return [r["name"] for r in scene_collections.read_raw_scenes(scenes_file)]
    except (ValueError, OSError):
        return []


def save_scene_action(scenes_file, name, overlay_drafts):
    """Save a screen scene with the drafted overlays under this name."""
    name = (name or "").strip()
    raw = {"name": name, "sources": [{"kind": "screen"}]}
    if overlay_drafts:
        raw["overlays"] = [draft.to_raw() for draft in overlay_drafts]
    return _attempt(lambda: "Saved scene %s." % scene_collections.save_scene(scenes_file, raw))


def duplicate_scene_action(scenes_file, name):
    return _attempt(lambda: "Created %s." % scene_collections.duplicate_scene(scenes_file, name))


def export_scene_action(scenes_file, name, dest_file, force=False):
    return _attempt(lambda: "Exported to %s." % scene_collections.export_scene(
        scenes_file, name, dest_file, force))


def import_scene_action(scenes_file, source, force=False):
    def run():
        added, replaced = scene_collections.import_scenes(scenes_file, source, force)
        return "Imported %d new, replaced %d." % (len(added), len(replaced))
    return _attempt(run)


# -- overlays ----------------------------------------------------------------
class OverlayDraft:
    """Editable overlay values behind the Overlays page controls."""

    def __init__(self, kind="text", text="", corner="top-left",
                 margin_x=OVERLAY_MARGIN, margin_y=OVERLAY_MARGIN,
                 size=None, path="", clock_format="24h"):
        self.kind = kind
        self.text = text
        self.corner = corner
        self.margin_x = margin_x
        self.margin_y = margin_y
        self.size = size
        self.path = path
        self.clock_format = clock_format

    def to_raw(self):
        """Scene JSON object for this overlay (same schema as scenes.json)."""
        raw = {"kind": self.kind, "corner": self.corner,
               "margin_x": self.margin_x, "margin_y": self.margin_y}
        if self.kind == KIND_IMAGE:
            raw["path"] = self.path
            raw["size_percent"] = (DEFAULT_IMAGE_PERCENT if self.size is None
                                   else self.size)
        else:
            raw["font_size"] = DEFAULT_FONT_SIZE if self.size is None else self.size
            if self.kind == KIND_TEXT:
                raw["text"] = self.text
            if self.kind == KIND_CLOCK:
                raw["format"] = self.clock_format
        return raw


def size_range(kind):
    """(low, high) for the scale control of this overlay kind."""
    return (MIN_PERCENT, MAX_PERCENT) if kind == KIND_IMAGE else (MIN_FONT_SIZE, MAX_FONT_SIZE)


def overlay_preview(draft):
    """Live preview configuration as FFmpeg filter text, or an error line.

    This is text only: no video is rendered and no browser is involved."""
    try:
        spec = parse_overlay("preview", draft.to_raw())
    except ValueError as exc:
        return "Not valid yet: %s" % exc
    if spec.kind == KIND_IMAGE:
        _, graph = image_stage(spec, PREVIEW_INPUT_LABEL, PREVIEW_OUTPUT_LABEL, 1,
                               PREVIEW_FRAME_WIDTH, lambda v: v - v % 2)
        return graph
    return drawtext_stage(spec, PREVIEW_INPUT_LABEL, PREVIEW_OUTPUT_LABEL)


class OverlayList:
    """The drafts being edited, capped like a scene file is."""

    def __init__(self):
        self.drafts = []

    def add(self, draft):
        if len(self.drafts) >= MAX_OVERLAYS:
            raise ValueError("At most %d overlays per scene (keeps CPU low)" % MAX_OVERLAYS)
        self.drafts.append(draft)
        return len(self.drafts) - 1

    def remove(self, index):
        del self.drafts[index]


OVERLAY_KIND_CHOICES = OVERLAY_KINDS
CORNER_CHOICES = CORNERS
CLOCK_FORMAT_CHOICES = tuple(CLOCK_FORMATS)
