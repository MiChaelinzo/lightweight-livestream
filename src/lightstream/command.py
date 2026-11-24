"""Pure FFmpeg command builder: same inputs always give the same argv."""

import os
from collections import namedtuple

from .audio import noise_filter_args
from .filtergraph import letterbox_filter
from .hardware import (low_resource_input_args, low_resource_output_args,
                       rate_control_bufsize_kbps, tuned_encoder_args)
from .platforms import capture_inputs, ingest_url, is_srt_url, silent_audio_input
from .scenes import compile_scene, scene_window

DEFAULT_KEYINT_SECONDS = 2        # keyframe every 2 seconds
DEFAULT_X264_TUNE = "zerolatency"  # "" means: pass no -tune at all
THREAD_OPTIONS = ("-threads", "-filter_threads", "-filter_complex_threads")

StreamSettings = namedtuple(
    "StreamSettings",
    "platform custom_url width height fps video_kbps audio_kbps x264_preset "
    "window audio_device encoder display video_device mute "
    "scene noise noise_model hardware_profile record_to "
    "audio_filter threads reserved_cores keyint_seconds x264_tune bufsize_seconds "
    "backup_url rate_mode grayscale skip_static local_ingest_port",
    defaults=(None, None, False, None, "off", None, None, None,
              None, None, None, DEFAULT_KEYINT_SECONDS, DEFAULT_X264_TUNE, None, None,
              "vbr", False, False, None),
)

RATE_MODES = ("vbr", "cbr")
LOCAL_INGEST_HOST = "127.0.0.1"
MPEGTS_PACKET_SIZE = 1316        # 7 TS packets of 188 bytes fit one UDP datagram
RECORDING_FORMATS = {".mkv": "matroska", ".mp4": "mp4"}
FRAGMENTED_MP4 = "movflags=frag_keyframe+empty_moov+default_base_moof"
WEBM_REASON = (
    "WEBM needs a VP8/VP9 encode, which cannot share the one H.264 encode that "
    "feeds the live stream. A second software encode would defeat the low-end "
    "goal. Use .mkv (default) or .mp4")

VAAPI_DEVICE = "/dev/dri/renderD128"


def _encoder_args(encoder, s):
    if encoder == "libx264":
        tune = ["-tune", s.x264_tune] if s.x264_tune else []
        return (["-c:v", "libx264", "-preset", s.x264_preset] + tune
                + ["-profile:v", "main", "-pix_fmt", "yuv420p"])
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-rc", "cbr",
                "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-look_ahead", "0"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-usage", "ultralowlatency", "-rc", "cbr"]
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-realtime", "1"]
    if encoder == "h264_vaapi":
        return ["-c:v", "h264_vaapi"]
    raise ValueError("Unsupported encoder %r" % encoder)


TEST_SECONDS = 10


def _without_options(args, names):
    """args minus each option in names and its value (options come in pairs)."""
    out = []
    i = 0
    while i < len(args):
        if args[i] in names:
            i += 2
        else:
            out.append(args[i])
            i += 1
    return out


def thread_args(threads, complex_graph, encoder):
    """-threads (libx264 only) and the filter thread option for a thread count."""
    graph_threads = "-filter_complex_threads" if complex_graph else "-filter_threads"
    args = [graph_threads, str(threads)]
    if encoder == "libx264":
        args += ["-threads", str(threads)]
    return args


def numbered_recording_path(path, attempt):
    """Recording path for a connection attempt. Attempt 0 keeps the path; later
    attempts get -2, -3, ... before the extension so ffmpeg never truncates
    footage written before a drop."""
    if attempt <= 0:
        return path
    root, ext = os.path.splitext(path)
    return "%s-%d%s" % (root, attempt + 1, ext)


def prepare_recording_path(path):
    """Create the folder and check it is writable. onfail=ignore would hide a
    bad path, so fail loudly before starting. Raises ValueError."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise ValueError("Cannot create the recording folder %s (%s)" % (folder, exc))
    if not os.access(folder, os.W_OK):
        raise ValueError("Cannot write recordings to %s. Pick another folder." % folder)
    if os.path.isdir(path):
        raise ValueError("Recording path %s is a folder, not a file" % path)


def recording_format(path):
    """Container name for a recording path: .mp4 is fragmented MP4, anything
    else is Matroska (the crash-safe default). .webm raises ValueError."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".webm":
        raise ValueError(WEBM_REASON)
    return RECORDING_FORMATS.get(ext, "matroska")


def local_ingest_url(port):
    """Local MPEG-TS over UDP address the persistent publisher reads."""
    return "udp://%s:%d?pkt_size=%d" % (LOCAL_INGEST_HOST, port, MPEGTS_PACKET_SIZE)


def tee_output(live_url, record_to, live_format="flv"):
    """tee muxer spec: encode once, send to the live output and a local file.

    Live slot: onfail=abort makes ffmpeg exit when the ingest dies, so the
    runner's reconnect loop sees it (without it ffmpeg keeps running with only
    the file). Recording slot: onfail=ignore keeps the stream alive if the file
    cannot be written. The file is Matroska (crash safe) or fragmented MP4 by
    extension. live_format is flv (RTMP) or mpegts (SRT, or the local
    publisher, see publisher_command). The key stays inside live_url as plain
    text, so redact() still hides it.
    """
    if "|" in live_url:
        raise ValueError("Stream URL or key must not contain '|' when recording")
    if any(c in record_to for c in "|[]'"):
        raise ValueError("Recording path %r must not contain | [ ] or '" % record_to)
    if live_format == "mpegts":
        live = "[f=mpegts:onfail=abort]"
    elif live_format == "flv":
        live = "[f=flv:onfail=abort:flvflags=no_duration_filesize]"
    else:
        raise ValueError("Unknown live format %r" % live_format)
    if recording_format(record_to) == "mp4":
        record = "[f=mp4:%s:onfail=ignore]" % FRAGMENTED_MP4
    else:
        record = "[f=matroska:onfail=ignore]"
    return "%s%s|%s%s" % (live, live_url, record, record_to.replace("\\", "/"))


def publisher_command(port, url, ffmpeg="ffmpeg"):
    """Long-lived `-c copy` publisher: reads the encoder's MPEG-TS from the
    local UDP port and sends it to url. Contains the key; redact before display.
    Measured in docs/BENCHMARKS.md (spike A)."""
    return [ffmpeg, "-hide_banner", "-loglevel", "warning",
            "-fflags", "+genpts+nobuffer", "-analyzeduration", "1000000",
            "-probesize", "200000", "-f", "mpegts", "-i",
            "udp://%s:%d?fifo_size=1000000&overrun_nonfatal=1"
            % (LOCAL_INGEST_HOST, port),
            "-c", "copy", "-flvflags", "no_duration_filesize", "-f", "flv", url]


def ignored_setting_notes(s, encoder):
    """Plain sentences for settings build_command cannot apply, so a choice is
    never silently dropped. Pure: same inputs, same notes."""
    notes = []
    if s.rate_mode == "cbr" and encoder != "libx264":
        notes.append("--rate-mode cbr only applies to libx264; %s keeps its own "
                     "rate control." % encoder)
    filtered_out = encoder == "h264_vaapi" or bool(s.scene)
    reason = "the VAAPI encoder" if encoder == "h264_vaapi" else "a scene"
    if s.grayscale and filtered_out:
        notes.append("--grayscale is ignored with %s." % reason)
    if s.skip_static and filtered_out:
        notes.append("--skip-static is ignored with %s." % reason)
    return notes


def build_command(s, key, os_name, encoder, ffmpeg="ffmpeg", record_path=None):
    """Return the full ffmpeg argv list. Contains the key; redact before display.

    With record_path, record TEST_SECONDS to that file instead of going live.
    Optional settings (scene, noise, hardware_profile, record_to) change the
    argv only when set; defaults give the same argv as before they existed.
    """
    window = scene_window(s.scene, s.window) if s.scene else s.window
    video_in, has_audio = capture_inputs(os_name, s.fps, window, s.audio_device,
                                      s.display, s.video_device, s.mute)
    if s.hardware_profile:
        video_in = low_resource_input_args(video_in)
    args = [ffmpeg, "-hide_banner", "-loglevel", "warning",
            "-stats"]  # progress lines feed the live/lagging indicator
    if encoder == "h264_vaapi":
        args += ["-vaapi_device", VAAPI_DEVICE]
    args += video_in
    if not has_audio:
        args += silent_audio_input()

    vaapi_tail = "format=nv12,hwupload" if encoder == "h264_vaapi" else ""
    if s.scene:
        audio_index = 0 if os_name == "macos" and has_audio else 1
        extra_inputs, graph, video_map = compile_scene(
            s.scene, s, os_name, args.count("-i"), vaapi_tail)
        args += extra_inputs
        args += ["-filter_complex", graph, "-map", video_map,
                 "-map", "%d:a" % audio_index, "-r", str(s.fps)]
    else:
        scale = letterbox_filter(s.width, s.height)
        if s.grayscale and not vaapi_tail:
            scale += ",format=gray,format=yuv420p"
        if s.skip_static and not vaapi_tail:
            # mpdecimate drops near-identical frames; vfr keeps them dropped
            args += ["-vf", scale + ",mpdecimate", "-fps_mode", "vfr"]
        else:
            if vaapi_tail:
                scale += "," + vaapi_tail
            args += ["-vf", scale, "-r", str(s.fps)]

    if s.noise != "off" or not s.audio_filter:  # an explicit noise level wins
        args += noise_filter_args(s.noise, s.noise_model)
    else:
        args += ["-af", s.audio_filter]
    thread_opts = []
    if s.hardware_profile:
        thread_opts = low_resource_output_args(s.hardware_profile, encoder, bool(s.scene))
    if s.threads:  # an explicit thread count replaces the hardware profile's
        thread_opts = (_without_options(thread_opts, THREAD_OPTIONS)
                       + thread_args(s.threads, bool(s.scene), encoder))
    args += thread_opts
    args += (tuned_encoder_args(s.hardware_profile, encoder)
             or _encoder_args(encoder, s))
    if s.rate_mode not in RATE_MODES:
        raise ValueError("Unknown rate mode %r. Choose one of: %s"
                         % (s.rate_mode, ", ".join(RATE_MODES)))
    if s.rate_mode == "cbr" and encoder == "libx264":
        # strict CBR pads quiet pictures up to the target (see BENCHMARKS.md)
        args += ["-minrate", "%dk" % s.video_kbps, "-x264-params", "nal-hrd=cbr"]
    args += [
        "-b:v", "%dk" % s.video_kbps,
        "-maxrate", "%dk" % s.video_kbps,
        # about 1 second (half for lean profiles): small buffer, low delay
        "-bufsize", "%dk" % rate_control_bufsize_kbps(s.hardware_profile, s.video_kbps,
                                                  s.bufsize_seconds),
        "-g", str(s.fps * s.keyint_seconds),  # keyframe interval, 2 seconds by default
        "-bf", "0",                        # no B-frames: less delay and CPU
        "-c:a", "aac", "-b:a", "%dk" % s.audio_kbps, "-ar", "44100", "-ac", "2",
    ]
    if record_path:
        return args + ["-t", str(TEST_SECONDS), "-f", "matroska", "-y", record_path]
    url = ingest_url(s.platform, key, s.custom_url)
    local = s.local_ingest_port is not None
    srt = is_srt_url(url)
    if s.record_to:
        if not s.scene:  # a scene graph already maps its own streams
            audio_index = 0 if os_name == "macos" and has_audio else 1
            args += ["-map", "0:v", "-map", "%d:a" % audio_index]
        # without -map ffmpeg exits 234; without global_header the file slot is empty
        args += ["-flags", "+global_header", "-flush_packets", "1"]
        if local:
            args += ["-f", "tee", tee_output(local_ingest_url(s.local_ingest_port),
                                             s.record_to, "mpegts")]
        else:
            args += ["-f", "tee", tee_output(url, s.record_to,
                                             "mpegts" if srt else "flv")]
        return args
    if local:
        return args + ["-flush_packets", "1", "-f", "mpegts",
                       local_ingest_url(s.local_ingest_port)]
    if srt:
        return args + ["-flush_packets", "1", "-f", "mpegts", url]
    return args + [
        "-flush_packets", "1",
        "-flvflags", "no_duration_filesize",
        "-f", "flv", url,
    ]
