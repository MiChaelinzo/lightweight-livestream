"""Settings resolution. Precedence: command line > config file > preset."""

import json
import os
import sys

from .audio import NOISE_LEVELS, require_model_file
from .command import StreamSettings
from .hardware import cap_preset_name, cap_video_kbps, get_profile
from .portable import data_dir, is_portable
from .presets import DEFAULT_PRESET, get_preset, parse_resolution
from .scenes import load_scenes, select_scene

EXAMPLE_CONFIG = {
    "platform": "twitch",
    "preset": DEFAULT_PRESET,
    "fps": None,
    "resolution": None,
    "bitrate": None,
    "window": None,
    "audio_device": None,
    "encoder": None,
    "video_device": None,
    "url": None,
    "mute": False,
    "scene": None,
    "scenes_file": None,
    "noise": "off",
    "noise_model": None,
    "record": None,
    "hardware": None,
    "force_preset": False,
}


DEFAULT_RECORDING_FILE = "lightstream-recording.mkv"


def config_path(os_name=None, environ=None, root=None):
    environ = os.environ if environ is None else environ
    if is_portable(root, environ):
        return os.path.join(data_dir(root), "config.json")
    if (os_name or detect_os()) == "windows":
        base = environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "lightstream", "config.json")


def scenes_path(os_name=None, environ=None, root=None):
    """Default scenes.json: next to config.json."""
    return os.path.join(os.path.dirname(config_path(os_name, environ, root)),
                        "scenes.json")


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


def effective_preset_name(cli, file_cfg, hardware=None):
    """Preset name after the hardware profile's cap (unless forced)."""
    preset_name = _pick("preset", cli, file_cfg, DEFAULT_PRESET)
    get_preset(preset_name)  # raises a clear error for unknown names
    if hardware:
        preset_name = cap_preset_name(
            hardware, preset_name, bool(_pick("force_preset", cli, file_cfg, False)))
    return preset_name


def resolve_settings(cli, file_cfg):
    """cli and file_cfg are dicts; None means 'not set'."""
    hardware = _pick("hardware", cli, file_cfg)
    if hardware:
        get_profile(hardware)  # raises a clear error for unknown names
    preset_name = effective_preset_name(cli, file_cfg, hardware)
    preset = get_preset(preset_name)
    noise = _pick("noise", cli, file_cfg, "off")
    if noise not in NOISE_LEVELS:
        raise ValueError("Unknown noise level %r. Choose one of: %s"
                         % (noise, ", ".join(NOISE_LEVELS)))
    noise_model = _pick("noise_model", cli, file_cfg)
    if noise == "ai" and hardware and not get_profile(hardware).allow_ai_audio \
            and cli.get("noise") != "ai":
        noise = "off"  # AI audio is off by default on this profile; --noise ai still works
    if noise == "ai":
        require_model_file(noise_model)
    scene = None
    scene_name = _pick("scene", cli, file_cfg)
    if scene_name:
        scene = select_scene(
            load_scenes(_pick("scenes_file", cli, file_cfg) or scenes_path()),
            scene_name)
    resolution = _pick("resolution", cli, file_cfg)
    width, height = (parse_resolution(resolution) if resolution
                     else (preset.width, preset.height))
    video_kbps = _positive_int("bitrate", _pick("bitrate", cli, file_cfg, preset.video_kbps))
    if hardware and cli.get("bitrate") is None:
        video_kbps = cap_video_kbps(hardware, video_kbps)  # explicit --bitrate is kept
    record = _pick("record", cli, file_cfg)
    if record is None and hardware and get_profile(hardware).record_by_default:
        record = DEFAULT_RECORDING_FILE
    return StreamSettings(
        platform=_pick("platform", cli, file_cfg, "twitch"),
        custom_url=_pick("url", cli, file_cfg),
        width=width,
        height=height,
        fps=_positive_int("fps", _pick("fps", cli, file_cfg, preset.fps)),
        video_kbps=video_kbps,
        audio_kbps=preset.audio_kbps,
        x264_preset=preset.x264_preset,
        window=_pick("window", cli, file_cfg),
        audio_device=_pick("audio_device", cli, file_cfg),
        encoder=_pick("encoder", cli, file_cfg),
        display=_pick("display", cli, file_cfg),
        video_device=_pick("video_device", cli, file_cfg),
        mute=bool(_pick("mute", cli, file_cfg, False)),
        scene=scene,
        noise=noise,
        noise_model=noise_model,
        hardware_profile=hardware,
        record_to=record or None,  # False (--no-record) turns recording off
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
