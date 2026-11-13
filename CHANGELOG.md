# Changelog

## Unreleased

- Easy window: `lightstream gui` / `lightstream-gui` with 3 steps, big START/STOP, status banner, plain-language help, "Check my PC", advanced options and safe close. Key is never saved or logged. Window rendering UNVERIFIED; controller logic tested.
- Runner can be stopped from another thread (`stop` event), reports status (starting, live, reconnecting, fallback, stopped, failed) and parses ffmpeg `-stats` into fps/bitrate/speed for a live/lagging indicator.
- A hardware encoder that fails quickly twice in a row falls back to libx264 mid-stream.
- `--keep-trying` never gives up reconnecting; Linux capture follows `$DISPLAY`; macOS `--video-device` picks the screen.
- Hardware encoders are chosen only if a short test encode succeeds, else libx264 (`doctor` uses the same check).
- Stop retrying after 5 consecutive quick failures; report a missing ffmpeg at launch.
- Keep source aspect ratio (scale plus pad) instead of stretching.
- Validate fps, bitrate and config file shape; fix docs about the key prompt, emulator black capture and key visibility in process lists.
- Windows launcher no longer echoes the stream key.

## 0.1.0

- Initial release: FFmpeg-driven CLI with presets, encoder auto-selection, low-priority runner with auto-reconnect, key redaction, launchers for Windows and Linux.
- Real streaming is UNVERIFIED (see README).
