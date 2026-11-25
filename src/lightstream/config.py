"""Settings resolution. Precedence: command line > config file > preset."""

import json
import os
import sys

from .audio import (CHAIN_FULL, CHAIN_LIGHT, NOISE_LEVELS, audio_profile_chain,
                    get_audio_profile, require_model_file)
from .command import RATE_MODES, StreamSettings, recording_format
from .fileio import write_private_text
from .hardware import cap_preset_name, cap_video_kbps, get_profile
from .portable import data_dir, is_portable, recordings_dir
from .presets import DEFAULT_PRESET, get_preset, parse_resolution
from .platforms import is_srt_url, validate_backup_url, validate_srt_url
from .perf_profiles import (get_perf_profile, get_stream_preset, resolve_tuning,
                            stream_preset_bitrate_cap)
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
    "profile": None,
    "stream_preset": None,
    "audio_profile": None,
    "auto_scale": False,
    "backup_url": None,
    "rate_mode": "vbr",
}


DEFAULT_RECORDING_FILE = "lightstream-recording.mkv"


def default_recording_path(root=None, environ=None):
    """recordings/ in the app folder in portable mode, else the plain file name."""
    if is_portable(root, environ):
        return os.path.join(recordings_dir(root), DEFAULT_RECORDING_FILE)
    return DEFAULT_RECORDING_FILE


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
    write_private_text(path, json.dumps(EXAMPLE_CONFIG, indent=2) + "\n")


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


DEFAULT_PLATFORM = "twitch"


def _derived_values(cli, file_cfg):
    """Values implied by --profile / --stream-preset, and whether they came
    from the command line. A stream preset supplies the profile and audio
    profile unless --profile or --audio-profile is set explicitly."""
    from_cli = bool(cli.get("profile") or cli.get("stream_preset"))
    layer = cli if from_cli else file_cfg
    stream_name = layer.get("stream_preset")
    profile_name = layer.get("profile")
    stream = get_stream_preset(stream_name) if stream_name else None
    if profile_name is None and stream:
        profile_name = stream.perf_profile
    derived = {}
    if profile_name:
        profile = get_perf_profile(profile_name)
        derived["preset"] = profile.preset_name
        derived["audio_profile"] = profile.audio_profile
    if stream:
        derived["platform"] = stream.platform
        derived["audio_profile"] = stream.audio_profile
        derived["bitrate_cap"] = stream_preset_bitrate_cap(stream_name)
    return derived, profile_name, from_cli


def _layered(name, cli, file_cfg, derived, derived_from_cli, default=None):
    """cli > profile from cli > file > profile from file > default."""
    value = cli.get(name)
    if value is None and derived_from_cli:
        value = derived.get(name)
    if value is None:
        value = file_cfg.get(name)
    if value is None and not derived_from_cli:
        value = derived.get(name)
    return default if value is None else value


def effective_preset_name(cli, file_cfg, hardware=None):
    """Preset name after the hardware profile's cap (unless forced)."""
    derived, _, from_cli = _derived_values(cli, file_cfg)
    preset_name = _layered("preset", cli, file_cfg, derived, from_cli, DEFAULT_PRESET)
    get_preset(preset_name)  # raises a clear error for unknown names
    if hardware:
        preset_name = cap_preset_name(
            hardware, preset_name, bool(_pick("force_preset", cli, file_cfg, False)))
    return preset_name


def _audio_filter(name, hardware, profile_name):
    """Chain string for an audio profile, or None. The light chain is used on
    hardware profiles that strip expensive filters and with the potato profile."""
    if not name:
        return None
    get_audio_profile(name)  # raises a clear error for unknown names
    light = (profile_name == "potato"
             or bool(hardware and get_profile(hardware).strip_expensive_filters))
    return audio_profile_chain(name, CHAIN_LIGHT if light else CHAIN_FULL)


def resolve_settings(cli, file_cfg, cpu_count=None):
    """cli and file_cfg are dicts; None means 'not set'. cpu_count (default
    os.cpu_count()) feeds the Gaming First thread math.

    --profile / --stream-preset fill in values the person did not set: an
    explicit command line flag beats a profile, a profile from the command
    line beats the config file, and the config file beats a profile it names.
    """
    derived, profile_name, from_cli = _derived_values(cli, file_cfg)
    hardware = _pick("hardware", cli, file_cfg)
    if hardware:
        get_profile(hardware)  # raises a clear error for unknown names
    preset_name = effective_preset_name(cli, file_cfg, hardware)
    preset = get_preset(preset_name)
    audio_profile = _layered("audio_profile", cli, file_cfg, derived, from_cli)
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
    if "bitrate_cap" in derived and cli.get("bitrate") is None \
            and file_cfg.get("bitrate") is None:
        video_kbps = min(video_kbps, derived["bitrate_cap"])
    if hardware and cli.get("bitrate") is None:
        video_kbps = cap_video_kbps(hardware, video_kbps)  # explicit --bitrate is kept
    record = _pick("record", cli, file_cfg)
    if record is None and hardware and get_profile(hardware).record_by_default:
        record = DEFAULT_RECORDING_FILE
    if record == DEFAULT_RECORDING_FILE:
        record = default_recording_path()
    profile = get_perf_profile(profile_name) if profile_name else None
    tuning = resolve_tuning(profile_name, cpu_count) if profile else None
    extras = {}
    if profile:
        extras = {"threads": tuning.threads,
                  "reserved_cores": tuning.reserved_cores or None,
                  "keyint_seconds": profile.keyint_seconds,
                  "x264_tune": profile.x264_tune,
                  "bufsize_seconds": profile.bufsize_seconds}
    custom_url = _pick("url", cli, file_cfg)
    if custom_url and is_srt_url(custom_url):
        validate_srt_url(custom_url)
    rate_mode = _pick("rate_mode", cli, file_cfg, "vbr")
    if rate_mode not in RATE_MODES:
        raise ValueError("Unknown rate mode %r. Choose one of: %s"
                         % (rate_mode, ", ".join(RATE_MODES)))
    if record:
        recording_format(record)  # refuses .webm with the reason
    backup_url = _pick("backup_url", cli, file_cfg)
    if backup_url:
        backup_url = validate_backup_url(backup_url)
    return StreamSettings(
        backup_url=backup_url or None,
        platform=_layered("platform", cli, file_cfg, derived, from_cli, DEFAULT_PLATFORM),
        custom_url=custom_url,
        rate_mode=rate_mode,
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
        audio_filter=_audio_filter(audio_profile, hardware, profile_name),
        **extras,
    )


def resolve_key(environ, prompt, saved=None):
    """Stream key from STREAM_KEY, then the opt-in credential store value
    (saved), else prompt (hidden input). Never from config files. saved may be
    a function, so the store is only asked when STREAM_KEY is not set."""
    key = environ.get("STREAM_KEY")
    if key:
        return key.strip()
    if callable(saved):
        saved = saved()
    if saved:
        return saved.strip()
    key = prompt("Stream key (hidden): ").strip()
    if not key:
        raise ValueError("No stream key. Set STREAM_KEY or type it when asked.")
    return key
