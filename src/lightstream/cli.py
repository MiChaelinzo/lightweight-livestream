"""Command line interface."""

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import threading
import time

from . import __version__
from .command import (build_command, numbered_recording_path,
                      prepare_recording_path)
from .config import (config_path, detect_os, load_file_config, resolve_key,
                     resolve_settings, scenes_path, effective_preset_name, write_example_config,
                     DEFAULT_RECORDING_FILE)
from .audio import AUDIO_PROFILES, NOISE_LEVELS
from .bandwidth import measure_upload, mbps_to_kbps, recommend
from .encoders import (HARDWARE_ORDER, SOFTWARE_ENCODER, choose_encoder,
                       choose_working_encoder, probe_encoders)
from .bench import (DEFAULT_ENCODE_SECONDS, DEFAULT_IMPORT_RUNS, DEFAULT_TICKS,
                    build_report, report_path, write_report)
from .portable import find_ffmpeg, is_portable, recordings_dir
from .hardware import PROFILES, classify_gpus, detect_gpu_names, get_profile
from .adaptive import AdaptiveAdvisor
from .autoscale import AutoScaleSession, AutoScaler, build_ladder, top_step
from .optimizer import (OptimizerContext, bottleneck_of, build_insights, health_line,
                        insight_line, session_health)
from .telemetry import TelemetrySampler
from .analytics import (analytics_enabled, append_history, history_entry,
                        load_history, build_session_report, reports_dir,
                        performance_snapshot, save_performance_snapshot,
                        write_session_report)
from .health import HealthTracker
from .network import detect_congestion, detect_link, link_advice, output_kind
from .platforms import PLATFORMS, embedded_key_in_url, ingest_url, parse_audio_devices
from .command import RATE_MODES, ignored_setting_notes, publisher_command
from .emergency import (POTATO_STREAM_PROFILES, emergency_settings, failover_settings,
                        potato_stream_settings,
                        weak_connection_settings)
from .perf_profiles import (PERF_PROFILES, STREAM_PRESETS, affinity_cpus)
from .presets import PRESETS
from .runner import (format_command, free_udp_port, run_with_publisher,
                     run_with_reconnect)
from .overlays import missing_images
from .scene_collections import (collection_dir, export_collection, export_scene,
                                import_scenes, scene_filename,
                                write_example_collection)
from .scenes import load_scenes, write_example_scenes


DEFAULT_TEST_FILE = "lightstream-test.mkv"
MAX_QUICK_FAILURES = 5  # consecutive quick failures before giving up


def build_parser():
    p = argparse.ArgumentParser(prog="lightstream",
                                description="Very lightweight livestreaming via FFmpeg.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check ffmpeg and available encoders")
    sub.add_parser("presets", help="list quality presets")
    sub.add_parser("profiles", help="list performance profiles, stream presets "
                                    "and audio profiles")
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
    r = sub.add_parser("readiness", help="score 0-100 for how ready this PC is to stream")
    r.add_argument("--ffmpeg", help="path to ffmpeg (default: search as usual)")
    r.add_argument("--upload-mbps", help="your upload speed in Mbps")
    r.add_argument("--platform", choices=PLATFORMS,
                   help="also test how fast a connection to this platform opens")
    r.add_argument("--url", help="rtmp:// address to test (for --platform custom)")
    ac = sub.add_parser("audio-check", help="check an audio or video file for "
                                            "clipping and loudness (needs ffmpeg)")
    ac.add_argument("file", help="audio or video file to analyze")
    ac.add_argument("--ffmpeg", help="path to ffmpeg (default: search as usual)")
    hl = sub.add_parser("highlights", help="HEURISTIC: find loud, busy or fast-changing "
                                           "moments in a recording and cut clips (needs ffmpeg)")
    hl.add_argument("file", help="recording to analyze")
    hl.add_argument("--top", type=int, default=5, help="number of moments (default 5)")
    hl.add_argument("--length", type=float, default=30.0,
                    help="clip length in seconds (default 30)")
    hl.add_argument("--min-gap", type=float, default=20.0,
                    help="least seconds between two moments (default 20)")
    hl.add_argument("--out", help="folder for clips and the JSON report "
                                  "(default: NAME-highlights next to the file)")
    hl.add_argument("--no-clips", action="store_true", help="write the report only")
    hl.add_argument("--vertical", action="store_true",
                    help="re-encode clips to 1080x1920 (9:16, centre crop) for Shorts/TikTok")
    hl.add_argument("--blur-background", action="store_true",
                    help="with --vertical: show the whole frame over a blurred copy")
    hl.add_argument("--ffmpeg", help="path to ffmpeg (default: search as usual)")
    db = sub.add_parser("dashboard", help="one-page summary of sessions, recordings, "
                                          "clips and free disk space")
    db.add_argument("--recordings", help="recordings folder (default: the app "
                                         "recordings folder in portable mode, else here)")
    sb = sub.add_parser("support-bundle",
                        help="write a redacted JSON file to attach to a bug report")
    sb.add_argument("--out", help="file to write (default: support-bundle.json "
                                  "next to config.json)")
    bn = sub.add_parser("bench", help="measure this PC: startup, memory, CPU cost "
                                      "and a synthetic encode; writes a JSON report")
    bn.add_argument("--ffmpeg", help="path to ffmpeg (default: search as usual)")
    bn.add_argument("--seconds", type=int, default=DEFAULT_ENCODE_SECONDS,
                    help="stream seconds per encode (default %d)" % DEFAULT_ENCODE_SECONDS)
    bn.add_argument("--ticks", type=int, default=DEFAULT_TICKS,
                    help="calls per CPU cost measurement (default %d)" % DEFAULT_TICKS)
    bn.add_argument("--import-runs", type=int, default=DEFAULT_IMPORT_RUNS)
    bn.add_argument("--compare-src", help="another lightstream src folder "
                                          "(for example an older version) to compare startup")
    bn.add_argument("--out", help="report file (default: reports/bench-DATE.json)")
    op = sub.add_parser("optimize", help="detect this PC, propose settings and show "
                                         "the config diff; applies only if you confirm")
    op.add_argument("--platform", choices=PLATFORMS)
    op.add_argument("--upload-mbps", help="your upload speed in Mbps")
    op.add_argument("--yes", action="store_true", help="confirm without asking")
    op.add_argument("--no-bench", action="store_true",
                    help="skip the short benchmark (tier is then not measured)")
    ky = sub.add_parser("key", help="opt-in: keep the stream key in the system "
                                    "credential store (never in config.json)")
    ky.add_argument("action", choices=("status", "save", "forget"))
    ky.add_argument("--yes", action="store_true",
                    help="confirm that you want the key stored (required for save)")
    sc = sub.add_parser("scenes", help="list, check or create a scenes file")
    sc.add_argument("action", choices=("list", "validate", "example", "export", "import"))
    sc.add_argument("target", nargs="?",
                    help="export: scene name (omit to export every scene); "
                         "import: a scene file or a folder of .json files")
    sc.add_argument("--to", help="export: file (one scene) or folder (all scenes); "
                                 "default is scenes/ next to the scenes file")
    sc.add_argument("--collection", action="store_true",
                    help="example: write scenes/gaming.json, just-chatting.json, "
                         "work.json, retro.json instead of scenes.json")
    sc.add_argument("--force", action="store_true",
                    help="export/import: replace existing files or scenes")
    sc.add_argument("--scenes-file", help="scenes file (default: scenes.json next to config.json)")
    pl = sub.add_parser("plugins", help="list or check plugins, or run the demo plugin "
                                        "(plugins are off unless enabled in config.json)")
    pl.add_argument("action", choices=("list", "check", "run-demo"))
    pl.add_argument("name", nargs="?", help="check: plugin folder name")
    pl.add_argument("--plugins-dir", help="plugins folder (default: plugins/ next to config.json)")
    s = sub.add_parser("start", help="start streaming")
    s.add_argument("--platform", choices=PLATFORMS)
    s.add_argument("--url", help="RTMP base URL for --platform custom")
    s.add_argument("--preset", choices=sorted(PRESETS))
    s.add_argument("--profile", choices=sorted(PERF_PROFILES),
                   help="performance profile (see: lightstream profiles)")
    s.add_argument("--stream-preset", choices=sorted(STREAM_PRESETS),
                   help="platform + profile + audio bundle (see: lightstream profiles)")
    s.add_argument("--audio-profile", choices=sorted(AUDIO_PROFILES),
                   help="microphone filter chain; --noise light/ai takes priority")
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
    s.add_argument("--no-record", action="store_true",
                   help="do not save a local copy (some hardware profiles record by default)")
    s.add_argument("--analytics", action="store_true",
                   help="opt in: save a session report (numbers only, no key) to reports/")
    s.add_argument("--auto-scale", action="store_true",
                   help="opt in: step quality down (and back up) automatically when the "
                        "stream struggles. Each step restarts ffmpeg briefly. Off by default")
    s.add_argument("--emergency", action="store_true",
                   help="start with the safest settings (potato size, two threads, no "
                        "overlays, no AI audio, small buffer). Never automatic")
    s.add_argument("--weak-connection", action="store_true",
                   help="for a poor uplink: lower bitrate, 1 second keyframes, "
                        "longer rate-control buffer")
    s.add_argument("--upload-mbps", help="your upload speed in Mbps; with "
                   "--weak-connection it can lower the bitrate further")
    s.add_argument("--potato-stream", type=int, choices=sorted(POTATO_STREAM_PROFILES),
                   metavar="KBPS",
                   help="Potato Stream for very weak PCs (about 512 MB): target 2000 or "
                        "4000 kbps with low fps, small size and 1-2 threads. Never automatic")
    s.add_argument("--grayscale", action="store_true",
                   help="with --potato-stream: grayscale picture. A bitrate/look option, "
                        "NOT a CPU saver (it raised CPU in measurements)")
    s.add_argument("--skip-static", action="store_true",
                   help="with --potato-stream: drop near-identical frames (mpdecimate, "
                        "variable frame rate). Helps static screens only; platform "
                        "handling is UNVERIFIED")
    s.add_argument("--rate-mode", choices=RATE_MODES,
                   help="vbr (capped, default) or cbr (libx264 only; pads quiet pictures "
                        "up to the bitrate)")
    s.add_argument("--persistent-ingest", action="store_true",
                   help="opt in: a second ffmpeg (-c copy) keeps the connection while "
                        "the encoder restarts, and a recording keeps going through "
                        "ingest failures. The output size stays fixed per session")
    s.add_argument("--backup-url", help="backup ingest rtmp://host/app (no key). Used "
                   "after repeated quick connection failures, same stream key")
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


def _cmd_scene_transfer(args, path, out):
    if args.action == "import":
        if not args.target:
            raise ValueError("Tell import where to read from: lightstream scenes import PATH")
        added, replaced = import_scenes(path, args.target, args.force)
        out.write("Imported %d new, replaced %d: %s\n"
                  % (len(added), len(replaced), ", ".join(added + replaced) or "nothing"))
        return 0
    folder = args.to or collection_dir(path)
    if args.target:
        dest = args.to or os.path.join(folder, scene_filename(args.target))
        out.write("Wrote %s\n" % export_scene(path, args.target, dest, args.force))
    else:
        for written in export_collection(path, folder, args.force):
            out.write("Wrote %s\n" % written)
    return 0


def cmd_scenes(args, out):
    path = args.scenes_file or scenes_path()
    if args.action in ("export", "import"):
        return _cmd_scene_transfer(args, path, out)
    if args.action == "example" and args.collection:
        for written in write_example_collection(collection_dir(path)):
            out.write("Wrote %s\n" % written)
        return 0
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
    profile = get_profile(classify_gpus(names))
    out.write("Hardware profile: %s (UNVERIFIED on real hardware)\n" % profile.name)
    out.write("  %s\n" % profile.description)
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


def cmd_profiles(out):
    out.write("Performance profiles (--profile):\n")
    for p in PERF_PROFILES.values():
        out.write("  %-12s preset %-8s %s\n" % (p.name, p.preset_name, p.description))
    out.write("Stream presets (--stream-preset):\n")
    for p in STREAM_PRESETS.values():
        out.write("  %-14s %-8s profile %-12s audio %-10s %s\n" % (
            p.name, p.platform, p.perf_profile, p.audio_profile, p.description))
    out.write("Audio profiles (--audio-profile):\n")
    for p in AUDIO_PROFILES.values():
        out.write("  %-11s %s\n              %s\n" % (p.name, p.description, p.cost_note))
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


def cmd_readiness(args, out, run=subprocess.run, connect=None, find=find_ffmpeg):
    from . import wizard
    from .bandwidth import rtmp_host_port
    target = None
    if args.url:
        target = rtmp_host_port(args.url)
    elif args.platform and args.platform != "custom":
        target = wizard.platform_latency_target(args.platform)
    elif args.platform:
        raise ValueError("Platform 'custom' needs --url rtmp://host/app")
    kbps = mbps_to_kbps(args.upload_mbps) if args.upload_mbps else None
    facts = wizard.gather_readiness_facts(
        detect_os(), upload_kbps=kbps, ffmpeg=args.ffmpeg, latency_target=target,
        run=run, find=find, connect=connect)
    for line in wizard.readiness_lines(wizard.readiness_report(facts)):
        out.write(line + "\n")
    return 0


def cmd_audio_check(args, out, find=find_ffmpeg, analyze=None):
    from . import audio_check
    analyze = analyze or audio_check.analyze_file
    check = analyze(args.ffmpeg or find(), args.file)
    for line in audio_check.check_lines(check):
        out.write(line + "\n")
    return 0


def cmd_highlights(args, out, find=find_ffmpeg, run=None):
    from . import highlights
    if args.blur_background and not args.vertical:
        raise ValueError("--blur-background needs --vertical")
    kwargs = {"run": run} if run else {}
    report, path = highlights.find_highlights(
        args.ffmpeg or find(), args.file, top=args.top, length=args.length,
        min_gap=args.min_gap, out_dir=args.out, cut=not args.no_clips,
        vertical=args.vertical, blur=args.blur_background, **kwargs)
    for line in highlights.report_lines(report, path):
        out.write(line + "\n")
    return 0


def cmd_dashboard(args, out, history_dir=None, disk_usage=shutil.disk_usage):
    from . import highlights
    folder = args.recordings or (recordings_dir() if is_portable() else os.getcwd())
    try:
        usage = disk_usage(folder)
        disk = (usage.free, usage.total)
    except OSError:
        disk = None
    history = load_history(history_dir or reports_dir(detect_os()))
    for line in highlights.dashboard_lines(
            history, highlights.list_media(folder), highlights.list_clips(folder),
            folder, disk):
        out.write(line + "\n")
    return 0


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO_PLUGIN_DIR = os.path.join(_REPO_ROOT, "examples", "plugins")
DEMO_WAIT_S = 2.0


def cmd_plugins(args, out, config_file=None):
    from . import plugins
    config_file = config_file or config_path(detect_os())
    folder = args.plugins_dir or plugins.plugins_dir(config_file)
    if args.action == "run-demo":
        return _plugins_run_demo(args, out)
    if args.action == "check":
        if not args.name:
            raise ValueError("plugins check needs a plugin name")
        try:
            manifest = plugins.load_manifest(os.path.join(folder, args.name))
        except plugins.ManifestError as exc:
            out.write("%s: INVALID: %s\n" % (args.name, exc))
            return 1
        out.write("%s %s: manifest valid (events: %s; permissions: %s)\n" % (
            manifest["name"], manifest["version"],
            ", ".join(manifest.get("events", [])) or "none",
            ", ".join(manifest.get("permissions", [])) or "none"))
        return 0
    enabled = load_file_config(config_file).get("plugins", [])
    found = plugins.discover(folder, enabled)
    if not found:
        out.write("No plugins in %s. Plugins are off unless listed in the "
                  "\"plugins\" setting of config.json.\n" % folder)
        return 0
    for item in found:
        out.write("%-20s %-9s %s\n" % (
            item["name"], "enabled" if item["enabled"] else "off",
            "ok" if item["error"] is None else "INVALID: " + item["error"]))
    return 0


def _plugins_run_demo(args, out):
    from . import plugins
    folder = os.path.join(args.plugins_dir or DEMO_PLUGIN_DIR, "hello")
    host = plugins.PluginHost(os.path.dirname(folder), ["hello"], __version__,
                              log=lambda text: out.write(text + "\n"))
    if not host.start_all():
        out.write("Demo plugin did not start (needs python3 on PATH).\n")
        return 1
    try:
        host.broadcast("stream_started", platform="demo")
        deadline = time.monotonic() + DEMO_WAIT_S
        seen = []
        while not seen and time.monotonic() < deadline:
            time.sleep(0.05)
            seen = host.collect_actions()
        for name, action in seen:
            out.write("[%s] %s: %s\n" % (name, action["action"], action["text"]))
    finally:
        host.stop_all()
    return 0 if seen else 1


def cmd_bench(args, out, build=build_report, find=find_ffmpeg, today=None):
    for name in ("seconds", "ticks", "import_runs"):
        if getattr(args, name) <= 0:
            raise ValueError("--%s must be greater than 0" % name.replace("_", "-"))
    ffmpeg = args.ffmpeg or find()
    out.write("Benchmarking (this takes a minute). ffmpeg: %s\n"
              % ("found" if ffmpeg else "not found, encode skipped"))
    report = build(ffmpeg=ffmpeg, seconds=args.seconds, ticks=args.ticks,
                   import_runs=args.import_runs, compare_src=args.compare_src)
    path = write_report(report, args.out or report_path(report["date"]))
    tier = report.get("tier")
    if tier:
        out.write("Tier: %s (%s)\n" % (tier["name"], tier["basis"]))
        if tier["skipped_metrics"]:
            out.write("  PARTIAL: not measured: %s. Tier is an upper bound; "
                      "run again with ffmpeg available for a full result.\n"
                      % ", ".join(tier["skipped_metrics"]))
    out.write("Wrote %s\n%s\n" % (path, report["caveat"]))
    return 0


def _saved_key(os_name):
    """Key from the system credential store if the person opted in earlier."""
    from .secure_store import SecureKeyStore, SecureStoreError, select_backend
    try:
        return SecureKeyStore(select_backend(
            os_name, os.path.dirname(config_path(os_name)))).load()
    except (SecureStoreError, OSError, subprocess.SubprocessError):
        return None


def cmd_optimize(args, out, input_fn=input, tier_fn=None, **kwargs):
    from . import wizard
    if tier_fn is None and not args.no_bench:
        def tier_fn():
            ffmpeg = find_ffmpeg()
            report = build_report(ffmpeg=ffmpeg, seconds=2, ticks=100, import_runs=1)
            return report["tier"]["name"] if ffmpeg else None
    return wizard.run_optimize(detect_os(), out, input_fn=input_fn, yes=args.yes,
                               platform=args.platform or "twitch",
                               upload_mbps=args.upload_mbps, tier_fn=tier_fn, **kwargs)


def cmd_key(args, out, store=None, prompt=getpass.getpass):
    from .secure_store import SecureKeyStore, SecureStoreError, select_backend
    os_name = detect_os()
    if store is None:
        store = SecureKeyStore(select_backend(os_name, os.path.dirname(config_path(os_name))))
    if args.action == "status":
        out.write("Secure key storage: %s\n"
                  % (store.backend_name or "not available on this system (key is never saved)"))
        return 0
    if args.action == "forget":
        store.forget()
        out.write("Saved key removed (if there was one).\n")
        return 0
    try:
        store.save(prompt("Stream key (hidden): "), opt_in=args.yes)
    except SecureStoreError as exc:
        out.write("%s\n" % exc)
        return 1
    out.write("Saved to %s. It is not in config.json.\n" % store.backend_name)
    return 0


def cmd_support_bundle(args, out, find=find_ffmpeg, probe=probe_encoders,
                       environ=None):
    """Opt-in: runs only when asked. The stream key and addresses are hidden."""
    from .analytics import (BUNDLE_FILENAME, build_support_bundle, load_history,
                            load_performance_snapshot, reports_dir,
                            write_support_bundle)
    environ = os.environ if environ is None else environ
    os_name = detect_os()
    cfg_file = config_path(os_name)
    ffmpeg = find()
    try:
        encoders = probe(ffmpeg) if ffmpeg else set()
    except RuntimeError:
        encoders = set()
    bundle = build_support_bundle(
        __version__, os_name, encoders, load_file_config(cfg_file),
        load_history(reports_dir(os_name)),
        known_secrets=(environ.get("STREAM_KEY"),),
        performance=load_performance_snapshot(reports_dir(os_name)))
    path = args.out or os.path.join(os.path.dirname(cfg_file), BUNDLE_FILENAME)
    write_support_bundle(path, bundle)
    out.write("Wrote %s (no stream key or address inside; check it before sharing)\n"
              % path)
    return 0


def cmd_start(args, out, detect=detect_gpu_names, clock=time.monotonic,
              report_dir=None, secret_sink=None):
    """secret_sink (a list) receives the resolved stream key so a crash report
    can scrub it even when it came from the prompt or the credential store."""
    os_name = detect_os()
    file_cfg = load_file_config(config_path(os_name))
    hardware = resolve_hardware(args.hardware, file_cfg, os_name, detect)
    cli_values = (
        {"platform": args.platform, "url": args.url, "preset": args.preset,
         "force_preset": True if args.preset else None,
         "fps": args.fps, "resolution": args.resolution, "bitrate": args.bitrate,
         "window": args.window, "audio_device": args.audio_device,
         "encoder": args.encoder, "video_device": args.video_device,
         "display": os.environ.get("DISPLAY"),
         "mute": args.mute or None, "scene": args.scene,
         "scenes_file": args.scenes_file,
         "record": False if args.no_record else args.record,
         "noise": args.noise, "noise_model": args.noise_model,
         "profile": args.profile, "stream_preset": args.stream_preset,
         "audio_profile": args.audio_profile,
         "backup_url": args.backup_url, "rate_mode": args.rate_mode,
         "hardware": hardware})
    settings = resolve_settings(cli_values, file_cfg)
    if args.emergency:
        settings = emergency_settings(settings)
    if args.potato_stream:
        settings = potato_stream_settings(settings, args.potato_stream,
                                          args.grayscale, args.skip_static)
    elif args.grayscale or args.skip_static:
        raise ValueError("--grayscale and --skip-static need --potato-stream")
    if args.weak_connection:  # after emergency: its longer buffer is kept
        settings = weak_connection_settings(
            settings, mbps_to_kbps(args.upload_mbps) if args.upload_mbps else None)
    persistent = bool(args.persistent_ingest) and not args.test_local
    if args.persistent_ingest and args.test_local:
        out.write("Note: --persistent-ingest is ignored with --test-local.\n")
    if persistent and settings.backup_url:
        raise ValueError("--persistent-ingest cannot be combined with --backup-url")
    if persistent:
        settings = settings._replace(local_ingest_port=free_udp_port())
    cpu_affinity = affinity_cpus(os.cpu_count() or 1, settings.reserved_cores)
    record_path = args.test_local
    if settings.scene:
        for path in missing_images(settings.scene.overlays):
            out.write("Warning: overlay image %s not found; that overlay is skipped.\n" % path)
    if settings.record_to and record_path:
        out.write("Note: --record is ignored with --test-local.\n")
    elif settings.record_to:
        prepare_recording_path(settings.record_to)  # ValueError -> "Error: ..."
        out.write("Recording a copy to %s (later attempts add -2, -3, ...)\n"
                  % settings.record_to)
    key = "test" if record_path else resolve_key(
        os.environ, getpass.getpass, saved=lambda: _saved_key(os_name))
    if secret_sink is not None and not record_path:
        secret_sink.append(key)  # --test-local uses a fixed placeholder, not a secret
    secrets = key
    backup = bool(settings.backup_url) and not record_path
    if settings.backup_url and record_path:
        out.write("Note: --backup-url is ignored with --test-local.\n")
    embedded = embedded_key_in_url(settings.custom_url) if (
        settings.platform == "custom") else None
    if embedded:
        out.write("Warning: the custom URL looks like it contains a stream key. "
                  "Use rtmp://host/app and give the key through STREAM_KEY or the "
                  "prompt, so it is never kept in config.json or shell history. "
                  "It is hidden in output here and never saved.\n")
        secrets = (key, embedded)

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
    for note in ignored_setting_notes(settings, encoder):
        out.write("Note: %s\n" % note)
    out.write(format_command(argv, secrets) + "\n")
    publisher_argv = None
    if persistent:
        publisher_argv = publisher_command(
            settings.local_ingest_port,
            ingest_url(settings.platform, key, settings.custom_url),
            ffmpeg or "ffmpeg")
        out.write("Persistent ingest (opt in): the publisher keeps the connection "
                  "while the encoder restarts. The output size stays fixed.\n")
        out.write(format_command(publisher_argv, secrets) + "\n")
    if backup:
        out.write("Backup ingest: %s (key hidden)\n"
                  % format_command(
                      [failover_settings(settings).custom_url], secrets))
    if record_path:
        out.write("Test mode: recording 10 seconds to %s (not live).\n" % record_path)
    if args.dry_run:
        return 0
    tracker = HealthTracker(target_kbps=settings.video_kbps)
    preset_name = effective_preset_name(cli_values, file_cfg, hardware)
    advisor = AdaptiveAdvisor(preset_name, settings.video_kbps, settings.fps)
    sampler = TelemetrySampler(os_name)
    auto_scale = bool(args.auto_scale) or file_cfg.get("auto_scale") is True
    if auto_scale and record_path:
        auto_scale = False
        out.write("Note: --auto-scale is ignored with --test-local.\n")
    scale = AutoScaleSession(
        settings, advisor, AutoScaler(build_ladder(top_step(settings), constant_size=persistent), clock,
                                      enabled=auto_scale),
        threading.Event(), out.write, sampler,
        gaming_first=bool(settings.reserved_cores),
        monitors=(tracker, advisor))
    if auto_scale:
        out.write("Auto-scale is ON: quality steps down when the stream struggles "
                  "and back up when it is healthy. Each step restarts ffmpeg briefly.\n")

    def on_status(state, detail):
        tracker.on_status(state, detail)
        advisor.on_status(state, detail)
        if state == "live":
            sampler.tick_if_due()
            out.write("fps=%s speed=%sx\r" % (detail.get("fps", "?"),
                                              detail.get("speed", "?")))
        scale.on_status(state, detail)

    def settings_for_attempt(attempt):
        current = scale.current_settings
        if current.record_to:  # a new file per attempt so footage is never truncated
            current = current._replace(
                record_to=numbered_recording_path(current.record_to, attempt))
        return current

    started = clock()
    encoder_stop = threading.Event()  # set when the publisher gives up

    def run_encoder():
        return run_with_reconnect(
            argv, secrets, os_name, on_status=on_status,
            max_failures=(1 if record_path else
                          None if args.keep_trying else MAX_QUICK_FAILURES),
            encoder=encoder, cpu_affinity=cpu_affinity, restart=scale.restart,
            stop=encoder_stop if persistent else None,
            argv_factory=lambda enc: build_command(
                scale.current_settings, key, os_name, enc, ffmpeg, record_path),
            argv_for_attempt=(None if record_path or not (
                settings.record_to or auto_scale or backup)
                              else lambda n, enc: build_command(
                                  settings_for_attempt(n), key, os_name, enc, ffmpeg)),
            backup_argv_for_attempt=(
                lambda n, enc: build_command(
                    failover_settings(settings_for_attempt(n)), key, os_name, enc,
                    ffmpeg)) if backup else None)

    try:
        if persistent:
            code = run_with_publisher(
                publisher_argv, secrets, os_name, run_encoder, out=out,
                on_publisher_status=lambda state, detail: (
                    tracker.on_status(state, detail) if state == "reconnecting" else None),
                max_failures=None if args.keep_trying else MAX_QUICK_FAILURES,
                encoder_stop=encoder_stop)
        else:
            code = run_encoder()
        if tracker.samples or tracker.reconnects:
            out.write("\n" + "\n".join(tracker.report_lines()) + "\n")
            stability = tracker.network_stability()
            if stability:
                out.write("  network stability: %d/100 (%s)\n"
                          % (stability.score, stability.basis))
            kind = output_kind(ingest_url(settings.platform, "x", settings.custom_url))
            sample = sampler.latest
            congestion = detect_congestion(
                tracker.summary(), scale.current_settings.video_kbps, kind,
                getattr(sample, "cpu_percent", None))
            for finding in congestion:
                out.write("  network: %s\n" % finding.message)
            link = detect_link(os_name)
            out.write("  link: %s%s (probe UNVERIFIED on real machines)\n"
                      % (link.kind, ", hotspot hint" if link.hotspot_hint else ""))
            for line in link_advice(link, tracker.speed_readings(), tracker.reconnects):
                out.write("  network: %s\n" % line)
            recording_analytics = not record_path and analytics_enabled(
                args.analytics, file_cfg)
            directory = report_dir or reports_dir(os_name)
            insights = build_insights(
                advisor, tracker.summary(), list(sampler.history), stability,
                OptimizerContext(preset_name, scale.current_settings.video_kbps,
                                 scale.current_settings.fps, encoder, settings.noise),
                load_history(directory) if recording_analytics else (),
                congestion)
            for rec in advisor.recommendations():  # suggestions only, never applied
                out.write("  suggestion (not applied): %s\n" % rec.message)
            for insight in insights:
                out.write("  insight: %s\n" % insight_line(insight))
            health = session_health(tracker.summary(), sample, stability)
            out.write("  %s\n" % health_line(health))
            if recording_analytics:
                path = write_session_report(
                    directory,
                    build_session_report(
                        tracker.summary(), encoder, clock() - started,
                        bool(settings.record_to),
                        preset=preset_name,
                        hardware_profile=settings.hardware_profile))
                append_history(directory, history_entry(
                    tracker.summary(), bottleneck_of(insights), preset_name,
                    health_score=health.score))
                save_performance_snapshot(directory, performance_snapshot(
                    tracker.summary(), sample, health))
                out.write("Session report saved to %s (no stream key inside)\n" % path)
        return code
    except OSError as exc:
        out.write("Could not start ffmpeg: %s\n" % exc)
        return 1


def main(argv=None, out=sys.stdout):
    args = build_parser().parse_args(argv)
    secret_sink = []
    try:
        if args.command == "doctor":
            return cmd_doctor(out)
        if args.command == "devices":
            return cmd_devices(out)
        if args.command == "presets":
            return cmd_presets(out)
        if args.command == "profiles":
            return cmd_profiles(out)
        if args.command == "readiness":
            return cmd_readiness(args, out)
        if args.command == "audio-check":
            return cmd_audio_check(args, out)
        if args.command == "highlights":
            return cmd_highlights(args, out)
        if args.command == "dashboard":
            return cmd_dashboard(args, out)
        if args.command == "bench":
            return cmd_bench(args, out)
        if args.command == "plugins":
            return cmd_plugins(args, out)
        if args.command == "optimize":
            return cmd_optimize(args, out)
        if args.command == "key":
            return cmd_key(args, out)
        if args.command == "support-bundle":
            return cmd_support_bundle(args, out)
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
        return cmd_start(args, out, secret_sink=secret_sink)
    except (ValueError, FileExistsError) as exc:
        out.write("Error: %s\n" % exc)
        return 2
    except Exception as exc:  # unexpected: keep a local report, never upload
        return _report_crash(exc, out, secrets=secret_sink)


def _report_crash(exc, out, directory=None, secrets=()):
    """Write crashes/crash-*.json next to the config (this PC only) and say so."""
    from .analytics import CRASH_DIRNAME, build_crash_report, write_crash_report
    os_name = detect_os()
    directory = directory or os.path.join(
        os.path.dirname(config_path(os_name)), CRASH_DIRNAME)
    report = build_crash_report(exc, __version__, os_name,
                                known_secrets=(os.environ.get("STREAM_KEY"),) + tuple(secrets))
    out.write("Unexpected error: %s: %s\n" % (report["error_type"], report["message"]))
    try:
        path = write_crash_report(directory, report)
        out.write("A crash report was saved to %s. It stays on this PC and is "
                  "never sent anywhere; check it before sharing.\n" % path)
    except OSError as err:
        out.write("Could not save a crash report (%s).\n" % err)
    return 70
