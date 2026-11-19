"""OBS-style scenes: a scene is a screen capture plus light overlays.

"Browser source" means capturing a browser window (screen source with a
window title and optional crop). Background handling is chroma key or blur
only; no ML. Real FFmpeg behavior of these graphs is UNVERIFIED here, they
are checked by unit tests on the generated text only.
"""

import json
import os
import re
from collections import namedtuple

from .filtergraph import filter_path, filter_text, letterbox_filter

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
DEFAULT_WEBCAM_PERCENT = 20
MIN_PERCENT, MAX_PERCENT = 5, 35   # a small overlay keeps scaling work low
WEBCAM_MAX_FPS = 15
IMAGE_FPS = 2
OVERLAY_MARGIN = 10
DEFAULT_FONT_SIZE = 24
DEFAULT_SIMILARITY = 0.3
MAX_BLUR_RADIUS = 20
OUTPUT_LABEL = "vout"

ScreenSource = namedtuple("ScreenSource", "window crop")  # crop: (x, y, w, h) or None
WebcamSource = namedtuple(
    "WebcamSource", "device corner size_percent chromakey_color similarity blur")
ImageSource = namedtuple("ImageSource", "path corner size_percent")
TextSource = namedtuple("TextSource", "text corner font_file font_size")
Scene = namedtuple("Scene", "name sources")

DEFAULT_SCENE = Scene("default", (ScreenSource(None, None),))

_HEX_COLOR = re.compile(r"^[0-9a-fA-F]{6}$")


def _fail(scene_name, message):
    raise ValueError("Scene %r: %s" % (scene_name, message))


def _corner(scene_name, raw, default):
    corner = raw.get("corner", default)
    if corner not in CORNERS:
        _fail(scene_name, "corner must be one of %s, got %r" % (", ".join(CORNERS), corner))
    return corner


def _percent(scene_name, raw, default):
    value = raw.get("size_percent", default)
    if isinstance(value, bool) or not isinstance(value, int) \
            or not MIN_PERCENT <= value <= MAX_PERCENT:
        _fail(scene_name, "size_percent must be a whole number from %d to %d, got %r"
              % (MIN_PERCENT, MAX_PERCENT, value))
    return value


def _required_text(scene_name, raw, key):
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        _fail(scene_name, "%s source needs a non-empty %r" % (raw.get("kind"), key))
    return value


def _parse_crop(scene_name, raw):
    crop = raw.get("crop")
    if crop is None:
        return None
    try:
        values = tuple(crop[k] for k in ("x", "y", "w", "h"))
    except (TypeError, KeyError):
        _fail(scene_name, "crop needs x, y, w and h")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values) \
            or values[0] < 0 or values[1] < 0 or values[2] <= 0 or values[3] <= 0:
        _fail(scene_name, "crop x/y must be >= 0 and w/h > 0, whole numbers")
    return values


def _parse_webcam(name, raw):
    chroma = raw.get("chromakey")
    blur = raw.get("blur")
    if chroma is not None and blur is not None:
        _fail(name, "webcam can use chromakey or blur, not both")
    color = similarity = None
    if chroma is not None:
        color = str(chroma.get("color", "")) if isinstance(chroma, dict) else ""
        if not _HEX_COLOR.match(color):
            _fail(name, "chromakey.color must be 6 hex digits like 00ff00")
        similarity = chroma.get("similarity", DEFAULT_SIMILARITY)
        if isinstance(similarity, bool) or not isinstance(similarity, (int, float)) \
                or not 0.01 <= similarity <= 1.0:
            _fail(name, "chromakey.similarity must be between 0.01 and 1.0")
    if blur is not None and (isinstance(blur, bool) or not isinstance(blur, int)
                             or not 1 <= blur <= MAX_BLUR_RADIUS):
        _fail(name, "blur must be a whole number from 1 to %d" % MAX_BLUR_RADIUS)
    return WebcamSource(
        device=_required_text(name, raw, "device"),
        corner=_corner(name, raw, "bottom-right"),
        size_percent=_percent(name, raw, DEFAULT_WEBCAM_PERCENT),
        chromakey_color=color, similarity=similarity, blur=blur)


def _parse_source(name, raw):
    if not isinstance(raw, dict):
        _fail(name, "each source must be an object")
    kind = raw.get("kind")
    if kind in ("screen", "window", "browser"):
        window = raw.get("window")
        if window is not None and not isinstance(window, str):
            _fail(name, "window must be text")
        return ScreenSource(window, _parse_crop(name, raw))
    if kind == "webcam":
        return _parse_webcam(name, raw)
    if kind == "image":
        path = _required_text(name, raw, "path")
        return ImageSource(path, _corner(name, raw, "top-left"),
                           _percent(name, raw, DEFAULT_WEBCAM_PERCENT))
    if kind == "text":
        try:
            filter_text(raw.get("text"))
            if raw.get("font_file"):
                filter_path(raw["font_file"], "font_file")
        except ValueError as exc:
            _fail(name, str(exc))
        size = raw.get("font_size", DEFAULT_FONT_SIZE)
        if isinstance(size, bool) or not isinstance(size, int) or not 8 <= size <= 200:
            _fail(name, "font_size must be a whole number from 8 to 200")
        return TextSource(raw["text"], _corner(name, raw, "top-left"),
                          raw.get("font_file"), size)
    _fail(name, "unknown source kind %r (use screen, window, browser, webcam, "
                "image or text)" % (kind,))


def parse_scene(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"]:
        raise ValueError("Each scene must be an object with a non-empty 'name'")
    name = raw["name"]
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        _fail(name, "needs a non-empty 'sources' list")
    sources = tuple(_parse_source(name, s) for s in raw_sources)
    if not isinstance(sources[0], ScreenSource):
        _fail(name, "the first source must be a screen, window or browser source")
    if sum(isinstance(s, ScreenSource) for s in sources) != 1:
        _fail(name, "use exactly one screen, window or browser source")
    if sum(isinstance(s, WebcamSource) for s in sources) > 1:
        _fail(name, "only one webcam per scene (keeps CPU and RAM low)")
    return Scene(name, sources)


def parse_scenes(data):
    """{'scenes': [...]} -> {name: Scene}. Raises ValueError in plain words."""
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise ValueError("Scenes file must be a JSON object with a 'scenes' list")
    scenes = {}
    for raw in data["scenes"]:
        scene = parse_scene(raw)
        if scene.name in scenes:
            raise ValueError("Duplicate scene name %r" % scene.name)
        scenes[scene.name] = scene
    return scenes


def load_scenes(path):
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except ValueError as exc:
            raise ValueError("Scenes file %s is not valid JSON: %s" % (path, exc))
    return parse_scenes(data)


def select_scene(scenes, name):
    try:
        return scenes[name]
    except KeyError:
        raise ValueError("Unknown scene %r. Available: %s"
                         % (name, ", ".join(sorted(scenes)) or "none"))


def _even(value):
    return max(2, value // 2 * 2)


def _overlay_xy(corner):
    m = OVERLAY_MARGIN
    x = str(m) if corner.endswith("left") else "W-w-%d" % m
    y = str(m) if corner.startswith("top") else "H-h-%d" % m
    return x, y


def _text_xy(corner):
    m = OVERLAY_MARGIN
    x = str(m) if corner.endswith("left") else "w-tw-%d" % m
    y = str(m) if corner.startswith("top") else "h-th-%d" % m
    return x, y


def _webcam_input(device, fps, os_name):
    if os_name == "windows":
        return ["-f", "dshow", "-framerate", str(fps), "-i", "video=" + device]
    if os_name == "linux":
        return ["-f", "v4l2", "-framerate", str(fps), "-i", device]
    if os_name == "macos":
        return ["-f", "avfoundation", "-framerate", str(fps), "-i", device + ":none"]
    raise ValueError("Unsupported OS %r" % os_name)


def scene_window(scene, fallback):
    """Window title for the main capture: the scene's own, else the setting."""
    return scene.sources[0].window or fallback


def compile_scene(scene, settings, os_name, first_input, tail=""):
    """-> (extra input args, filter_complex text, output map label).

    first_input is the index of the first input this function adds (after the
    screen/audio inputs). tail is an optional last filter such as the VAAPI
    upload. Deterministic: same arguments give the same text.
    """
    screen = scene.sources[0]
    overlays = scene.sources[1:]
    base = letterbox_filter(settings.width, settings.height)
    if screen.crop:
        x, y, w, h = screen.crop
        base = "crop=%d:%d:%d:%d,%s" % (w, h, x, y, base)

    input_args = []
    graph = []
    next_input = first_input
    steps = len(overlays) + (1 if tail else 0)

    def label(step):  # step 0 is the base; the last step is the output
        return OUTPUT_LABEL if step == steps else "v%d" % step

    graph.append("[0:v]%s[%s]" % (base, label(0)))
    for step, source in enumerate(overlays, start=1):
        prev, out = label(step - 1), label(step)
        if isinstance(source, TextSource):
            x, y = _text_xy(source.corner)
            font = ("fontfile=%s:" % filter_path(source.font_file, "font_file")
                    if source.font_file else "")
            graph.append("[%s]drawtext=%stext='%s':x=%s:y=%s:fontsize=%d:fontcolor=white[%s]"
                         % (prev, font, filter_text(source.text), x, y,
                            source.font_size, out))
            continue
        width = _even(settings.width * source.size_percent // 100)
        cam = "ov%d" % step
        if isinstance(source, WebcamSource):
            cam_fps = min(settings.fps, WEBCAM_MAX_FPS)
            input_args += _webcam_input(source.device, cam_fps, os_name)
            chain = "fps=%d,scale=%d:-2" % (cam_fps, width)
            if source.chromakey_color:
                chain += ",chromakey=color=0x%s:similarity=%s:blend=0.0" % (
                    source.chromakey_color.lower(), source.similarity)
            elif source.blur:
                chain += ",boxblur=%d:1" % source.blur
        else:
            input_args += ["-loop", "1", "-framerate", str(IMAGE_FPS), "-i", source.path]
            chain = "scale=%d:-2" % width
        graph.append("[%d:v]%s[%s]" % (next_input, chain, cam))
        next_input += 1
        x, y = _overlay_xy(source.corner)
        graph.append("[%s][%s]overlay=%s:%s[%s]" % (prev, cam, x, y, out))
    if tail:
        graph.append("[%s]%s[%s]" % (label(steps - 1), tail, OUTPUT_LABEL))
    return input_args, ";".join(graph), "[%s]" % OUTPUT_LABEL


EXAMPLE_SCENES = {
    "scenes": [
        {"name": "game-with-webcam",
         "sources": [
             {"kind": "screen"},
             {"kind": "webcam", "device": "Integrated Camera",
              "corner": "bottom-right", "size_percent": 20}]},
        {"name": "browser-source",
         "sources": [
             {"kind": "browser", "window": "My Overlay - Browser",
              "crop": {"x": 0, "y": 0, "w": 1280, "h": 720}},
             {"kind": "text", "text": "Thanks for watching", "corner": "top-left"}]},
        {"name": "webcam-green-screen",
         "sources": [
             {"kind": "screen"},
             {"kind": "webcam", "device": "Integrated Camera", "corner": "bottom-left",
              "size_percent": 25, "chromakey": {"color": "00ff00", "similarity": 0.3}}]},
    ]
}


def write_example_scenes(path):
    """Write the example scenes file. Never overwrites an existing file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:  # "x" fails if the file exists
        json.dump(EXAMPLE_SCENES, fh, indent=2)
        fh.write("\n")
