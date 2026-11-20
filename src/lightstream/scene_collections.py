"""Scene collections: share scenes as small human-readable JSON files.

A collection is a folder of one-scene files (gaming.json, just-chatting.json,
...). The working scenes file (scenes.json) stays the single place `start`
reads. Everything here works on plain dicts and files, with no tkinter, so
the CLI and the GUI use the same code. Every scene is checked with
scenes.parse_scene before it is written or imported. Never overwrites a file
or replaces a scene unless force is set.
"""

import json
import os

from .portable import is_portable, scenes_dir
import re

from .scenes import parse_scene, parse_scenes

COLLECTION_DIRNAME = "scenes"
COLLECTION_SUFFIX = ".json"
COPY_SUFFIX = "-copy"
_NOT_FILENAME_SAFE = re.compile(r"[^a-z0-9]+")

EXAMPLE_COLLECTION = {
    "gaming": {
        "name": "gaming",
        "sources": [
            {"kind": "screen"},
            {"kind": "webcam", "device": "Integrated Camera",
             "corner": "bottom-right", "size_percent": 20}],
        "overlays": [
            {"kind": "fps", "corner": "top-left"},
            {"kind": "recording", "corner": "top-right"}]},
    "just-chatting": {
        "name": "just-chatting",
        "sources": [
            {"kind": "screen"},
            {"kind": "webcam", "device": "Integrated Camera",
             "corner": "bottom-left", "size_percent": 35}],
        "overlays": [{"kind": "clock", "corner": "top-right", "format": "short"}]},
    "work": {
        "name": "work",
        "sources": [{"kind": "screen"}],
        "overlays": [{"kind": "clock", "corner": "bottom-right"}]},
    "retro": {
        "name": "retro",
        "sources": [
            {"kind": "screen"},
            {"kind": "webcam", "device": "Integrated Camera", "corner": "bottom-left",
             "size_percent": 25, "chromakey": {"color": "00ff00", "similarity": 0.3}}],
        "overlays": [
            {"kind": "text", "text": "Retro night", "corner": "top-left", "font_size": 32}]},
}


def scene_filename(name):
    """File name for a scene: letters and digits joined by '-', so a scene name
    can never point outside the target folder."""
    slug = _NOT_FILENAME_SAFE.sub("-", str(name).lower()).strip("-")
    if not slug:
        raise ValueError("Scene name %r cannot be used as a file name" % (name,))
    return slug + COLLECTION_SUFFIX


def collection_dir(scenes_file, root=None, environ=None):
    """Portable mode: scenes/ in the app folder. Otherwise scenes/ next to the working scenes file."""
    if is_portable(root, environ):
        return scenes_dir(root)
    return os.path.join(os.path.dirname(os.path.abspath(scenes_file)), COLLECTION_DIRNAME)


def read_raw_scenes(scenes_file):
    """Raw scene dicts from the working file; [] when the file does not exist."""
    if not os.path.exists(scenes_file):
        return []
    try:
        with open(scenes_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise ValueError("Scenes file %s is not valid JSON: %s" % (scenes_file, exc))
    parse_scenes(data)  # plain-words errors for a bad file
    return data["scenes"]


def _write_json(path, data, force):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    try:
        with open(path, "w" if force else "x", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
    except FileExistsError:
        raise ValueError("%s already exists. Use --force to replace it." % path)


def write_scenes_file(scenes_file, raw_scenes):
    """Validate, then write the working scenes file."""
    data = {"scenes": raw_scenes}
    parse_scenes(data)
    _write_json(scenes_file, data, force=True)


def _find(raw_scenes, name):
    for index, raw in enumerate(raw_scenes):
        if raw.get("name") == name:
            return index
    return None


def _require_scene(raw_scenes, name):
    index = _find(raw_scenes, name)
    if index is None:
        raise ValueError("Unknown scene %r. Available: %s" % (
            name, ", ".join(sorted(r["name"] for r in raw_scenes)) or "none"))
    return raw_scenes[index]


def export_scene(scenes_file, name, dest_file, force=False):
    """Write one scene as its own JSON file. Returns the path."""
    raw = _require_scene(read_raw_scenes(scenes_file), name)
    _write_json(dest_file, raw, force)
    return dest_file


def export_collection(scenes_file, dest_dir, force=False):
    """One <name>.json per scene in dest_dir. Returns the written paths."""
    raw_scenes = read_raw_scenes(scenes_file)
    if not raw_scenes:
        raise ValueError("No scenes to export in %s" % scenes_file)
    targets = [(os.path.join(dest_dir, scene_filename(r["name"])), r) for r in raw_scenes]
    if len({path for path, _ in targets}) != len(targets):
        raise ValueError("Two scene names map to the same file name; rename one first")
    if not force:
        existing = [path for path, _ in targets if os.path.exists(path)]
        if existing:  # check first so a collision does not leave a half-written folder
            raise ValueError("%s already exists. Use --force to replace it." % existing[0])
    for path, raw in targets:
        _write_json(path, raw, force)
    return [path for path, _ in targets]


def read_importable(source):
    """Raw scenes from a file (one scene or {'scenes': [...]}) or a folder of
    .json files. Every scene is validated."""
    if os.path.isdir(source):
        paths = sorted(os.path.join(source, n) for n in os.listdir(source)
                       if n.endswith(COLLECTION_SUFFIX))
        if not paths:
            raise ValueError("No .json scene files found in %s" % source)
    elif os.path.isfile(source):
        paths = [source]
    else:
        raise ValueError("Nothing to import at %s" % source)
    found = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except ValueError as exc:
            raise ValueError("%s is not valid JSON: %s" % (path, exc))
        except OSError as exc:
            raise ValueError("%s could not be read: %s" % (path, exc))
        raws = data["scenes"] if isinstance(data, dict) and "scenes" in data else [data]
        if not isinstance(raws, list):
            raise ValueError("%s: 'scenes' must be a list" % path)
        for raw in raws:
            parse_scene(raw)
            found.append(raw)
    names = [r["name"] for r in found]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError("The import contains scene %r more than once" % duplicates[0])
    return found


def import_scenes(scenes_file, source, force=False):
    """Merge scenes from source into the working file.
    Returns (added names, replaced names). A name that already exists is an
    error unless force is set."""
    incoming = read_importable(source)
    current = read_raw_scenes(scenes_file)
    clashes = [r["name"] for r in incoming if _find(current, r["name"]) is not None]
    if clashes and not force:
        raise ValueError("Scene %r already exists. Use --force to replace it." % clashes[0])
    added, replaced = [], []
    for raw in incoming:
        index = _find(current, raw["name"])
        if index is None:
            current.append(raw)
            added.append(raw["name"])
        else:
            current[index] = raw
            replaced.append(raw["name"])
    write_scenes_file(scenes_file, current)
    return added, replaced


def save_scene(scenes_file, raw_scene):
    """Add a scene, or replace the one with the same name (GUI "Save Scene")."""
    parse_scene(raw_scene)
    current = read_raw_scenes(scenes_file)
    index = _find(current, raw_scene["name"])
    if index is None:
        current.append(raw_scene)
    else:
        current[index] = raw_scene
    write_scenes_file(scenes_file, current)
    return raw_scene["name"]


def duplicate_scene(scenes_file, name, new_name=None):
    """Copy a scene under a new unique name ('<name>-copy', '-copy-2', ...)."""
    current = read_raw_scenes(scenes_file)
    source = _require_scene(current, name)
    if new_name is None:
        new_name = name + COPY_SUFFIX
        number = 2
        while _find(current, new_name) is not None:
            new_name = "%s%s-%d" % (name, COPY_SUFFIX, number)
            number += 1
    elif _find(current, new_name) is not None:
        raise ValueError("Scene %r already exists" % new_name)
    copy = json.loads(json.dumps(source))  # deep copy of plain JSON data
    copy["name"] = new_name
    current.append(copy)
    write_scenes_file(scenes_file, current)
    return new_name


def write_example_collection(directory):
    """Write gaming.json, just-chatting.json, work.json and retro.json.
    Never overwrites. Returns the paths."""
    paths = []
    for name, raw in EXAMPLE_COLLECTION.items():
        parse_scene(raw)
        path = os.path.join(directory, scene_filename(name))
        _write_json(path, raw, force=False)
        paths.append(path)
    return paths
