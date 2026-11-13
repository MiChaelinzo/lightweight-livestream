"""Ingest URLs and per-OS screen/audio capture inputs. Pure functions."""

INGEST_URLS = {
    "twitch": "rtmp://live.twitch.tv/app/",
    "youtube": "rtmp://a.rtmp.youtube.com/live2/",
}

PLATFORMS = ("twitch", "youtube", "custom")


def ingest_url(platform, key, custom_url=None):
    """Full RTMP URL including the stream key. Never print this unredacted."""
    if platform == "custom":
        if not custom_url:
            raise ValueError("Platform 'custom' needs --url rtmp://host/app")
        return custom_url.rstrip("/") + "/" + key
    if platform not in INGEST_URLS:
        raise ValueError(
            "Unknown platform %r. Choose one of: %s" % (platform, ", ".join(PLATFORMS))
        )
    return INGEST_URLS[platform] + key


DEFAULT_DISPLAY = ":0.0"
DEFAULT_MAC_VIDEO_DEVICE = "1"  # usually the main screen


def capture_inputs(os_name, fps, window=None, audio_device=None,
                   display=None, video_device=None):
    """FFmpeg input arguments for screen (+ audio when the OS allows it here).

    os_name is one of 'windows', 'linux', 'macos'. Returns (args, has_audio).
    """
    low_latency = ["-fflags", "nobuffer", "-thread_queue_size", "64"]
    if os_name == "windows":
        target = "title=" + window if window else "desktop"
        args = low_latency + [
            "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "0",
            "-rtbufsize", "32M", "-i", target,
        ]
        if audio_device:
            args += low_latency + ["-f", "dshow", "-i", "audio=" + audio_device]
        return args, bool(audio_device)
    if os_name == "linux":
        if window:
            raise ValueError("--window is only supported on Windows")
        args = low_latency + ["-f", "x11grab", "-framerate", str(fps),
                              "-draw_mouse", "0", "-i",
                              display or DEFAULT_DISPLAY]
        args += low_latency + ["-f", "pulse", "-i", audio_device or "default"]
        return args, True
    if os_name == "macos":
        if window:
            raise ValueError("--window is only supported on Windows")
        # avfoundation takes "video:audio" device indexes in a single input.
        args = low_latency + ["-f", "avfoundation", "-framerate", str(fps),
                              "-capture_cursor", "0", "-i",
                              (video_device or DEFAULT_MAC_VIDEO_DEVICE) + ":"
                              + (audio_device or "0")]
        return args, True
    raise ValueError("Unsupported OS %r" % os_name)


def silent_audio_input():
    """Used when no audio device is given; many sites want an audio track."""
    return ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
