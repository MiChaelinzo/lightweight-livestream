"""Overlay widgets drawn by FFmpeg itself: text, clock, FPS, REC dot, PNG logo.

No browser and no HTML engine. Each overlay becomes one filter stage:
drawtext for the text-like kinds, scale plus overlay for a PNG. All functions
are pure, so the same inputs give the same filter text. The generated filters
are checked as text by unit tests; whether a given FFmpeg build renders them
(drawtext needs a build with freetype, and on Windows usually a font_file) is
UNVERIFIED here.

Cost notes: drawtext runs once per frame on the already scaled picture, so
keep the count small (MAX_OVERLAYS). The FPS widget shows the average since the
stream started (frames divided by time), not an instant reading.
"""

import os
from collections import namedtuple

from .filtergraph import (CORNERS, DEFAULT_FONT_SIZE, IMAGE_FPS, MAX_PERCENT,
                          MIN_PERCENT, OVERLAY_MARGIN, filter_path, filter_text,
                          overlay_position, text_position)

KIND_TEXT, KIND_CLOCK, KIND_FPS, KIND_RECORDING, KIND_IMAGE = (
    "text", "clock", "fps", "recording", "image")
OVERLAY_KINDS = (KIND_TEXT, KIND_CLOCK, KIND_FPS, KIND_RECORDING, KIND_IMAGE)
CLOCK_FORMATS = {"24h": "%H\\:%M\\:%S", "short": "%H\\:%M"}
DEFAULT_CLOCK_FORMAT = "24h"
MAX_OVERLAYS = 6
MAX_MARGIN = 400
MIN_FONT_SIZE, MAX_FONT_SIZE = 8, 200
DEFAULT_IMAGE_PERCENT = 20
RECORDING_BLINK = "lt(mod(t,2),1)"   # visible during the first second of every two
RECORDING_TEXT = "REC"
RECORDING_COLOR = "red"
TEXT_COLOR = "white"

OverlaySpec = namedtuple(
    "OverlaySpec",
    "kind text corner margin_x margin_y size font_file path clock_format")


def _fail(scene_name, message):
    raise ValueError("Scene %r overlay: %s" % (scene_name, message))


def _whole(scene_name, raw, key, default, low, high):
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        _fail(scene_name, "%s must be a whole number from %d to %d, got %r"
              % (key, low, high, value))
    return value


def parse_overlay(scene_name, raw):
    """One overlay object from a scene's 'overlays' list -> OverlaySpec."""
    if not isinstance(raw, dict):
        _fail(scene_name, "each overlay must be an object")
    kind = raw.get("kind")
    if kind not in OVERLAY_KINDS:
        _fail(scene_name, "unknown kind %r (use %s)" % (kind, ", ".join(OVERLAY_KINDS)))
    corner = raw.get("corner", "top-left")
    if corner not in CORNERS:
        _fail(scene_name, "corner must be one of %s, got %r" % (", ".join(CORNERS), corner))
    margin_x = _whole(scene_name, raw, "margin_x", OVERLAY_MARGIN, 0, MAX_MARGIN)
    margin_y = _whole(scene_name, raw, "margin_y", OVERLAY_MARGIN, 0, MAX_MARGIN)
    text = path = font_file = None
    clock_format = DEFAULT_CLOCK_FORMAT
    if kind == KIND_IMAGE:
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            _fail(scene_name, "image overlay needs a non-empty 'path' to a PNG")
        try:
            filter_path(path, "path")
        except ValueError as exc:
            _fail(scene_name, str(exc))
        size = _whole(scene_name, raw, "size_percent", DEFAULT_IMAGE_PERCENT,
                      MIN_PERCENT, MAX_PERCENT)
    else:
        size = _whole(scene_name, raw, "font_size", DEFAULT_FONT_SIZE,
                      MIN_FONT_SIZE, MAX_FONT_SIZE)
        font_file = raw.get("font_file")
        if font_file is not None:
            try:
                filter_path(font_file, "font_file")
            except ValueError as exc:
                _fail(scene_name, str(exc))
        if kind == KIND_TEXT:
            try:
                text = filter_text(raw.get("text"))
            except ValueError as exc:
                _fail(scene_name, str(exc))
        if kind == KIND_CLOCK:
            clock_format = raw.get("format", DEFAULT_CLOCK_FORMAT)
            if clock_format not in CLOCK_FORMATS:
                _fail(scene_name, "format must be one of %s, got %r"
                      % (", ".join(CLOCK_FORMATS), clock_format))
    return OverlaySpec(kind, text, corner, margin_x, margin_y, size, font_file, path,
                       clock_format)


def parse_overlays(scene_name, raw_list):
    if raw_list is None:
        return ()
    if not isinstance(raw_list, list):
        _fail(scene_name, "'overlays' must be a list")
    if len(raw_list) > MAX_OVERLAYS:
        _fail(scene_name, "at most %d overlays per scene (keeps CPU low)" % MAX_OVERLAYS)
    return tuple(parse_overlay(scene_name, raw) for raw in raw_list)


def _drawtext_text(spec):
    if spec.kind == KIND_TEXT:
        return spec.text
    if spec.kind == KIND_CLOCK:
        return "%{localtime\\:" + CLOCK_FORMATS[spec.clock_format] + "}"
    if spec.kind == KIND_FPS:
        return "FPS %{eif\\:n/(t+0.001)\\:d}"
    return RECORDING_TEXT


def drawtext_stage(spec, in_label, out_label):
    """Filter text for one text-like overlay (text, clock, fps, recording)."""
    x, y = text_position(spec.corner, spec.margin_x, spec.margin_y)
    font = "fontfile=%s:" % filter_path(spec.font_file, "font_file") if spec.font_file else ""
    color = RECORDING_COLOR if spec.kind == KIND_RECORDING else TEXT_COLOR
    enable = ":enable='%s'" % RECORDING_BLINK if spec.kind == KIND_RECORDING else ""
    return "[%s]drawtext=%stext='%s':x=%s:y=%s:fontsize=%d:fontcolor=%s%s[%s]" % (
        in_label, font, _drawtext_text(spec), x, y, spec.size, color, enable, out_label)


def image_stage(spec, in_label, out_label, input_index, frame_width, even):
    """(input args, filter text) for a PNG overlay. even() rounds widths to even."""
    width = even(frame_width * spec.size // 100)
    x, y = overlay_position(spec.corner, spec.margin_x, spec.margin_y)
    input_args = ["-loop", "1", "-framerate", str(IMAGE_FPS), "-i", spec.path]
    graph = "[%d:v]scale=%d:-2[ovl%d];[%s][ovl%d]overlay=%s:%s[%s]" % (
        input_index, width, input_index, in_label, input_index, x, y, out_label)
    return input_args, graph


def missing_images(specs, exists=os.path.isfile):
    """PNG paths that do not exist; compile_scene skips those overlays."""
    return [s.path for s in specs if s.kind == KIND_IMAGE and not exists(s.path)]


def usable_overlays(specs, exists=os.path.isfile):
    """Overlays that can be drawn: a missing PNG is skipped instead of failing
    the whole stream. Callers should tell the user via missing_images()."""
    return tuple(s for s in specs if s.kind != KIND_IMAGE or exists(s.path))
