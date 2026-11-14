"""Pure FFmpeg command builder: same inputs always give the same argv."""

from collections import namedtuple

from .platforms import capture_inputs, ingest_url, silent_audio_input

StreamSettings = namedtuple(
    "StreamSettings",
    "platform custom_url width height fps video_kbps audio_kbps x264_preset "
    "window audio_device encoder display video_device mute",
    defaults=(None, None, False),
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


def build_command(s, key, os_name, encoder, ffmpeg="ffmpeg", record_path=None):
    """Return the full ffmpeg argv list. Contains the key; redact before display.

    With record_path, record TEST_SECONDS to that file instead of going live.
    """
    video_in, has_audio = capture_inputs(os_name, s.fps, s.window, s.audio_device,
                                      s.display, s.video_device, s.mute)
    args = [ffmpeg, "-hide_banner", "-loglevel", "warning",
            "-stats"]  # progress lines feed the live/lagging indicator
    if encoder == "h264_vaapi":
        args += ["-vaapi_device", VAAPI_DEVICE]
    args += video_in
    if not has_audio:
        args += silent_audio_input()

    # Keep the source aspect ratio; letterbox the rest instead of stretching.
    scale = ("scale=%d:%d:flags=fast_bilinear:force_original_aspect_ratio=decrease,"
             "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (s.width, s.height, s.width, s.height))
    if encoder == "h264_vaapi":
        scale += ",format=nv12,hwupload"
    args += ["-vf", scale, "-r", str(s.fps)]

    args += _encoder_args(encoder, s)
    args += [
        "-b:v", "%dk" % s.video_kbps,
        "-maxrate", "%dk" % s.video_kbps,
        "-bufsize", "%dk" % s.video_kbps,  # about 1 second: small buffer, low delay
        "-g", str(s.fps * 2),              # keyframe every 2 seconds
        "-bf", "0",                        # no B-frames: less delay and CPU
        "-c:a", "aac", "-b:a", "%dk" % s.audio_kbps, "-ar", "44100", "-ac", "2",
    ]
    if record_path:
        return args + ["-t", str(TEST_SECONDS), "-f", "matroska", "-y", record_path]
    return args + [
        "-flush_packets", "1",
        "-flvflags", "no_duration_filesize",
        "-f", "flv", ingest_url(s.platform, key, s.custom_url),
    ]
