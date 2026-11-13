"""Settings resolution. Precedence: command line > config file > preset."""

import json
import os
import sys

from .command import StreamSettings
from .presets import DEFAULT_PRESET, get_preset, parse_resolution

EXAMPLE_CONFIG = {
    "platform": "twitch",
    "preset": DEFAULT_PRESET,
    "fps": None,
    "resolution": None,
    "bitrate": None,
    "window": None,
    "audio_device": None,
    "encoder": None,
    "url": None,
}


def config_path(os_name=None, environ=None):
    environ = os.environ if environ is None else environ
    if (os_name or detect_os()) == "windows":
        base = environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "lightstream", "config.json")


def detect_os(platform_name=None):
    name = platform_name or sys.platform
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return "linux"


def load_file_config(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except ValueError as exc:
            raise ValueError("Config file %s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ValueError("Config file %s must contain a JSON object" % path)
    return data


def write_example_config(path):
    if os.path.exists(path):
        raise FileExistsError(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(EXAMPLE_CONFIG, fh, indent=2)
        fh.write("\n")


def _pick(name, cli, file_cfg, default=None):
    """Command line value, else config file value, else default."""
    value = cli.get(name)
    if value is None:
        value = file_cfg.get(name)
    return default if value is None else value


def _positive_int(name, value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a whole number, got %r" % (name, value))
    if number <= 0:
        raise ValueError("%s must be greater than 0, got %d" % (name, number))
    return number


def resolve_settings(cli, file_cfg):
    """cli and file_cfg are dicts; None means 'not set'."""
    preset = get_preset(_pick("preset", cli, file_cfg, DEFAULT_PRESET))
    resolution = _pick("resolution", cli, file_cfg)
    width, height = (parse_resolution(resolution) if resolution
                     else (preset.width, preset.height))
    return StreamSettings(
        platform=_pick("platform", cli, file_cfg, "twitch"),
        custom_url=_pick("url", cli, file_cfg),
        width=width,
        height=height,
        fps=_positive_int("fps", _pick("fps", cli, file_cfg, preset.fps)),
        video_kbps=_positive_int(
            "bitrate", _pick("bitrate", cli, file_cfg, preset.video_kbps)),
        audio_kbps=preset.audio_kbps,
        x264_preset=preset.x264_preset,
        window=_pick("window", cli, file_cfg),
        audio_device=_pick("audio_device", cli, file_cfg),
        encoder=_pick("encoder", cli, file_cfg),
    )


def resolve_key(environ, prompt):
    """Stream key from STREAM_KEY, else prompt (hidden input). Never from files."""
    key = environ.get("STREAM_KEY")
    if key:
        return key.strip()
    key = prompt("Stream key (hidden): ").strip()
    if not key:
        raise ValueError("No stream key. Set STREAM_KEY or type it when asked.")
    return key
