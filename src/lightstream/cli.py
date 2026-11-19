"""Command line interface."""

import argparse
import getpass
import os
import shutil
import subprocess
import sys

from . import __version__
from .command import (build_command, numbered_recording_path,
                      prepare_recording_path)
from .config import (config_path, detect_os, load_file_config, resolve_key,
                     resolve_settings, scenes_path, write_example_config)
from .audio import NOISE_LEVELS
from .bandwidth import measure_upload, mbps_to_kbps, recommend
from .encoders import (HARDWARE_ORDER, SOFTWARE_ENCODER, choose_encoder,
                       choose_working_encoder, probe_encoders)
from .portable import find_ffmpeg, is_portable
from .hardware import PROFILES, classify_gpus, detect_gpu_names, get_profile
from .health import HealthTracker
from .platforms import PLATFORMS, parse_audio_devices
from .presets import PRESETS
from .runner import format_command, run_with_reconnect
from .scenes import load_scenes, write_example_scenes


DEFAULT_TEST_FILE = "lightstream-test.mkv"
DEFAULT_RECORDING_FILE = "lightstream-recording.mkv"
MAX_QUICK_FAILURES = 5  # consecutive quick failures before giving up


def build_parser():
    p = argparse.ArgumentParser(prog="lightstream",
                                description="Very lightweight livestreaming via FFmpeg.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check ffmpeg and available encoders")
    sub.add_parser("presets", help="list quality presets")
    sub.add_parser("init", help="write an example config file")
    sub.add_parser("devices", help="list audio devices (Windows and macOS)")
    sub.add_parser("gui", help="open the easy window (3 steps, for beginners)")
    u = sub.add_parser("setup", help="pick safe settings for this PC (never saves the key)")
    u.add_argument("--yes", action="store_true", help="no questions, use defaults")
    u.add_argument("--platform", choices=PLATFORMS)
    u.add_argument("--upload-mbps", help="your upload speed in Mbps")
    b = sub.add_parser("bandwidth", help="suggest a preset and bitrate for your upload speed")
    b.add_argument("--platform", choices=PLATFORMS, default="twitch")
    b.add_argument("--upload-mbps", help="your upload speed in Mbps")
    b.add_argument("--measure-url", help="a URL you control that accepts a POST upload")
    b.add_argument("--hardware", help="hardware profile, e.g. intel_hd")
    sc = sub.add_parser("scenes", help="list, check or create a scenes file")
    sc.add_argument("action", choices=("list", "validate", "example"))
    sc.add_argument("--scenes-file", help="scenes file (default: scenes.json next to config.json)")
    s = sub.add_parser("start", help="start streaming")
    s.add_argument("--platform", choices=PLATFORMS)
    s.add_argument("--url", help="RTMP base URL for --platform custom")
    s.add_argument("--preset", choices=sorted(PRESETS))
    s.add_argument("--fps", type=int)
    s.add_argument("--res", dest="resolution", help="for example 854x480")
    s.add_argument("--bitrate", type=int, help="video kbps")
    s.add_argument("--window", help="Windows only: exact window title to capture")
    s.add_argument("--audio-device", help="dshow/pulse/avfoundation audio device")
    s.add_argument("--video-device",
                   help="macOS only: avfoundation screen index (see ffmpeg -list_devices)")
    s.add_argument("--mute", action="store_true",
                   help="send silence instead of capturing audio")
    s.add_argument("--test-local", nargs="?", const=DEFAULT_TEST_FILE,
                   metavar="FILE",
                   help="record 10 seconds to FILE instead of going live "
                        "(default %s); no stream key needed" % DEFAULT_TEST_FILE)
    s.add_argument("--keep-trying", action="store_true",
                   help="never give up reconnecting (for flaky internet)")
    s.add_argument("--encoder", help="force an encoder, e.g. libx264")
    s.add_argument("--software", action="store_true",
                   help="do not use a hardware encoder")
    s.add_argument("--scene", help="scene name from the scenes file (set at start; "
                                   "to switch scenes, stop and start again)")
    s.add_argument("--scenes-file", help="scenes file (default: scenes.json next to config.json)")
    s.add_argument("--record", nargs="?", const=DEFAULT_RECORDING_FILE, metavar="FILE",
                   help="also save a local copy while streaming (default %s)"
                        % DEFAULT_RECORDING_FILE)
    s.add_argument("--noise", choices=NOISE_LEVELS,
                   help="microphone noise suppression: off, light (afftdn), ai (arnndn model)")
    s.add_argument("--noise-model", help="path to an arnndn .rnnn model for --noise ai")
    s.add_argument("--hardware", choices=("auto",) + tuple(PROFILES),
                   help="hardware profile; auto detects the GPU (default when none is configured)")
    s.add_argument("--dry-run", action="store_true",
                   help="print the ffmpeg command (key hidden) and exit")
    return p


def resolve_hardware(cli_value, file_cfg, os_name, detect=detect_gpu_names):
    """Profile name: explicit choice wins, else the config file, else detect the GPU."""
    if cli_value and cli_value != "auto":
        return cli_value
    if not cli_value and file_cfg.get("hardware"):
        return file_cfg["hardware"]
    return classify_gpus(detect(os_name))


def cmd_scenes(args, out):
    path = args.scenes_file or scenes_path()
    if args.action == "example":
        write_example_scenes(path)  # raises FileExistsError, never overwrites
        out.write("Wrote %s\n" % path)
        return 0
    if not os.path.exists(path):
        out.write("No scenes file at %s. Create one with: lightstream scenes example\n" % path)
        return 1
    scenes = load_scenes(path)  # ValueError in plain words
    if args.action == "validate":
        out.write("OK: %d scene(s) in %s\n" % (len(scenes), path))
    else:
        for name in scenes:
            out.write("%s\n" % name)
    return 0


def cmd_doctor(out, detect=detect_gpu_names):
    os_name = detect_os()
    out.write("OS: %s\n" % os_name)
    names = detect(os_name)
    out.write("GPU: %s\n" % (", ".join(names) or "not detected"))
    out.write("Hardware profile: %s (UNVERIFIED on real hardware)\n" % classify_gpus(names))
    if is_portable():
        out.write("Mode: portable (settings in %s)\n" % os.path.dirname(config_path(os_name)))
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        out.write("ffmpeg: NOT FOUND. Install it and add it to PATH.\n")
        return 1
    out.write("ffmpeg: %s\n" % ffmpeg)
    try:
        encoders = probe_encoders(ffmpeg)
    except RuntimeError as exc:
        out.write("%s\n" % exc)
        return 1
    out.write("Encoder that would be used (test-encoded): %s\n"
              % choose_working_encoder(ffmpeg, encoders))
    return 0


def cmd_devices(out, os_name=None, run=subprocess.run):
    os_name = os_name or detect_os()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        out.write("ffmpeg: NOT FOUND. Install it and add it to PATH.\n")
        return 1
    if os_name == "windows":
        cmd = [ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow",
               "-i", "dummy"]
    elif os_name == "macos":
        cmd = [ffmpeg, "-hide_banner", "-f", "avfoundation",
               "-list_devices", "true", "-i", ""]
    else:
        out.write("Linux: use 'default' (or a name from 'pactl list short sources').\n")
        return 0
    try:  # ffmpeg prints the list on stderr and exits with an error: expected
        text = run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   universal_newlines=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        out.write("Could not list devices: %s\n" % exc)
        return 1
    names = parse_audio_devices(text)
    for name in names:
        out.write("%s\n" % name)
    if not names:
        out.write("No audio devices found.\n")
    return 0


def cmd_presets(out):
    for p in PRESETS.values():
        out.write("%-9s %dx%d @%dfps %dk  %s\n" % (
            p.name, p.width, p.height, p.fps, p.video_kbps, p.description))
    return 0


def cmd_bandwidth(args, out, post=None):
    if args.upload_mbps:
        kbps = mbps_to_kbps(args.upload_mbps)
    else:
        kbps = measure_upload(args.measure_url, **({"post": post} if post else {}))
        out.write("Measured upload: %.0f kbps\n" % kbps)
    if args.hardware:
        get_profile(args.hardware)
    rec = recommend(kbps, args.platform, args.hardware)
    out.write("Recommended preset: %s, video %d kbps (audio %d kbps, %d kbps usable)\n"
              % (rec.preset, rec.video_kbps, rec.audio_kbps, rec.usable_kbps))
    out.write("Use: lightstream start --preset %s --bitrate %d\n"
              % (rec.preset, rec.video_kbps))
    return 0


def cmd_start(args, out, detect=detect_gpu_names):
    os_name = detect_os()
    file_cfg = load_file_config(config_path(os_name))
    hardware = resolve_hardware(args.hardware, file_cfg, os_name, detect)
    settings = resolve_settings(
        {"platform": args.platform, "url": args.url, "preset": args.preset,
         "force_preset": True if args.preset else None,
         "fps": args.fps, "resolution": args.resolution, "bitrate": args.bitrate,
         "window": args.window, "audio_device": args.audio_device,
         "encoder": args.encoder, "video_device": args.video_device,
         "display": os.environ.get("DISPLAY"),
         "mute": args.mute or None, "scene": args.scene,
         "scenes_file": args.scenes_file, "record": args.record,
         "noise": args.noise, "noise_model": args.noise_model,
         "hardware": hardware}, file_cfg)
    record_path = args.test_local
    if settings.record_to and record_path:
        out.write("Note: --record is ignored with --test-local.\n")
    elif settings.record_to:
        prepare_recording_path(settings.record_to)  # ValueError -> "Error: ..."
        out.write("Recording a copy to %s (later attempts add -2, -3, ...)\n"
                  % settings.record_to)
    key = "test" if record_path else resolve_key(os.environ, getpass.getpass)

    order = (get_profile(settings.hardware_profile).encoder_order
             if settings.hardware_profile else HARDWARE_ORDER)
    ffmpeg = find_ffmpeg()
    if ffmpeg is None and not args.dry_run:
        out.write("ffmpeg not found. Run 'lightstream doctor'.\n")
        return 1
    available = set()
    if ffmpeg:
        try:
            available = probe_encoders(ffmpeg)
        except RuntimeError as exc:
            out.write("Warning: %s. Using libx264.\n" % exc)
    if ffmpeg and not args.dry_run:
        encoder = choose_working_encoder(ffmpeg, available, not args.software,
                                         settings.encoder, order=order)
    else:  # dry run: never launch ffmpeg, so no hardware test encode
        encoder = (settings.encoder or
                   (choose_encoder(available, order=order) if available and not args.software
                    else SOFTWARE_ENCODER))
    argv = build_command(settings, key, os_name, encoder, ffmpeg or "ffmpeg",
                         record_path)

    out.write("Encoder: %s\n" % encoder)
    out.write(format_command(argv, key) + "\n")
    if record_path:
        out.write("Test mode: recording 10 seconds to %s (not live).\n" % record_path)
    if args.dry_run:
        return 0
    tracker = HealthTracker(target_kbps=settings.video_kbps)

    def on_status(state, detail):
        tracker.on_status(state, detail)
        if state == "live":
            out.write("fps=%s speed=%sx\r" % (detail.get("fps", "?"),
                                              detail.get("speed", "?")))

    try:
        code = run_with_reconnect(
            argv, key, os_name, on_status=on_status,
            max_failures=(1 if record_path else
                          None if args.keep_trying else MAX_QUICK_FAILURES),
            encoder=encoder,
            argv_factory=lambda enc: build_command(
                settings, key, os_name, enc, ffmpeg, record_path),
            argv_for_attempt=(None if not settings.record_to or record_path else
                              lambda n, enc: build_command(
                                  settings._replace(record_to=numbered_recording_path(
                                      settings.record_to, n)),
                                  key, os_name, enc, ffmpeg)))
        if tracker.samples or tracker.reconnects:
            out.write("\n" + "\n".join(tracker.report_lines()) + "\n")
        return code
    except OSError as exc:
        out.write("Could not start ffmpeg: %s\n" % exc)
        return 1


def main(argv=None, out=sys.stdout):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return cmd_doctor(out)
        if args.command == "devices":
            return cmd_devices(out)
        if args.command == "presets":
            return cmd_presets(out)
        if args.command == "gui":
            from .gui import main as gui_main  # lazy: tkinter is optional
            return gui_main()
        if args.command == "bandwidth":
            return cmd_bandwidth(args, out)
        if args.command == "setup":
            from .wizard import run_setup
            return run_setup(detect_os(), out, yes=args.yes,
                             platform=args.platform, upload_mbps=args.upload_mbps)
        if args.command == "scenes":
            return cmd_scenes(args, out)
        if args.command == "init":
            path = config_path()
            try:
                write_example_config(path)
            except FileExistsError:
                out.write("Config already exists: %s\n" % path)
                return 1
            out.write("Wrote %s (the stream key is never stored here)\n" % path)
            return 0
        return cmd_start(args, out)
    except (ValueError, FileExistsError) as exc:
        out.write("Error: %s\n" % exc)
        return 2
