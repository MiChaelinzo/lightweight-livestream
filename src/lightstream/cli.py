"""Command line interface."""

import argparse
import getpass
import os
import shutil
import sys

from . import __version__
from .command import build_command
from .config import (config_path, detect_os, load_file_config, resolve_key,
                     resolve_settings, write_example_config)
from .encoders import (SOFTWARE_ENCODER, choose_encoder,
                       choose_working_encoder, probe_encoders)
from .platforms import PLATFORMS
from .presets import PRESETS
from .runner import format_command, run_with_reconnect


MAX_QUICK_FAILURES = 5  # consecutive quick failures before giving up


def build_parser():
    p = argparse.ArgumentParser(prog="lightstream",
                                description="Very lightweight livestreaming via FFmpeg.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check ffmpeg and available encoders")
    sub.add_parser("presets", help="list quality presets")
    sub.add_parser("init", help="write an example config file")
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
    s.add_argument("--keep-trying", action="store_true",
                   help="never give up reconnecting (for flaky internet)")
    s.add_argument("--encoder", help="force an encoder, e.g. libx264")
    s.add_argument("--software", action="store_true",
                   help="do not use a hardware encoder")
    s.add_argument("--dry-run", action="store_true",
                   help="print the ffmpeg command (key hidden) and exit")
    return p


def cmd_doctor(out):
    os_name = detect_os()
    out.write("OS: %s\n" % os_name)
    ffmpeg = shutil.which("ffmpeg")
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


def cmd_presets(out):
    for p in PRESETS.values():
        out.write("%-9s %dx%d @%dfps %dk  %s\n" % (
            p.name, p.width, p.height, p.fps, p.video_kbps, p.description))
    return 0


def cmd_start(args, out):
    os_name = detect_os()
    file_cfg = load_file_config(config_path(os_name))
    settings = resolve_settings(
        {"platform": args.platform, "url": args.url, "preset": args.preset,
         "fps": args.fps, "resolution": args.resolution, "bitrate": args.bitrate,
         "window": args.window, "audio_device": args.audio_device,
         "encoder": args.encoder, "video_device": args.video_device,
         "display": os.environ.get("DISPLAY")}, file_cfg)
    key = resolve_key(os.environ, getpass.getpass)

    ffmpeg = shutil.which("ffmpeg")
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
                                         settings.encoder)
    else:  # dry run: never launch ffmpeg, so no hardware test encode
        encoder = (settings.encoder or
                   (choose_encoder(available) if available and not args.software
                    else SOFTWARE_ENCODER))
    argv = build_command(settings, key, os_name, encoder, ffmpeg or "ffmpeg")

    out.write("Encoder: %s\n" % encoder)
    out.write(format_command(argv, key) + "\n")
    if args.dry_run:
        return 0
    try:
        return run_with_reconnect(
            argv, key, os_name,
            max_failures=None if args.keep_trying else MAX_QUICK_FAILURES,
            encoder=encoder,
            argv_factory=lambda enc: build_command(
                settings, key, os_name, enc, ffmpeg))
    except OSError as exc:
        out.write("Could not start ffmpeg: %s\n" % exc)
        return 1


def main(argv=None, out=sys.stdout):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return cmd_doctor(out)
        if args.command == "presets":
            return cmd_presets(out)
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
