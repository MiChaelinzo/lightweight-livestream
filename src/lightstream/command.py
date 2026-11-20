"""Pure FFmpeg command builder: same inputs always give the same argv."""

import os
from collections import namedtuple

from .audio import noise_filter_args
from .filtergraph import letterbox_filter
from .hardware import (low_resource_input_args, low_resource_output_args,
                       rate_control_bufsize_kbps, tuned_encoder_args)
from .platforms import capture_inputs, ingest_url, silent_audio_input
from .scenes import compile_scene, scene_window

StreamSettings = namedtuple(
    "StreamSettings",
    "platform custom_url width height fps video_kbps audio_kbps x264_preset "
    "window audio_device encoder display video_device mute "
    "scene noise noise_model hardware_profile record_to",
    defaults=(None, None, False, None, "off", None, None, None),
)

VAAPI_DEVICE = "/dev/dri/renderD128"


def _encoder_args(encoder, s):
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", s.x264_preset, "-tune", "zerolatency",
                "-profile:v", "main", "-pix_fmt", "yuv420p"]
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


def tee_output(live_url, record_to):
    """tee muxer spec: encode once, send to RTMP and a local Matroska file.

    Matroska survives a crash, and onfail=ignore keeps the stream alive if the
    file cannot be written. The key stays inside live_url as plain text, so
    redact() still hides it.
    """
    if "|" in live_url:
        raise ValueError("Stream URL or key must not contain '|' when recording")
    if any(c in record_to for c in "|[]'"):
        raise ValueError("Recording path %r must not contain | [ ] or '" % record_to)
    return "[f=flv:flvflags=no_duration_filesize]%s|[f=matroska:onfail=ignore]%s" % (
        live_url, record_to.replace("\\", "/"))


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
        if vaapi_tail:
            scale += "," + vaapi_tail
        args += ["-vf", scale, "-r", str(s.fps)]

    args += noise_filter_args(s.noise, s.noise_model)
    if s.hardware_profile:
        args += low_resource_output_args(s.hardware_profile, encoder, bool(s.scene))
    args += (tuned_encoder_args(s.hardware_profile, encoder)
             or _encoder_args(encoder, s))
    args += [
        "-b:v", "%dk" % s.video_kbps,
        "-maxrate", "%dk" % s.video_kbps,
        # about 1 second (half for lean profiles): small buffer, low delay
        "-bufsize", "%dk" % rate_control_bufsize_kbps(s.hardware_profile, s.video_kbps),
        "-g", str(s.fps * 2),              # keyframe every 2 seconds
        "-bf", "0",                        # no B-frames: less delay and CPU
        "-c:a", "aac", "-b:a", "%dk" % s.audio_kbps, "-ar", "44100", "-ac", "2",
    ]
    if record_path:
        return args + ["-t", str(TEST_SECONDS), "-f", "matroska", "-y", record_path]
    url = ingest_url(s.platform, key, s.custom_url)
    if s.record_to:
        return args + ["-flush_packets", "1", "-f", "tee", tee_output(url, s.record_to)]
    return args + [
        "-flush_packets", "1",
        "-flvflags", "no_duration_filesize",
        "-f", "flv", url,
    ]
