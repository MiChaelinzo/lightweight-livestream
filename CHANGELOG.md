# Changelog

## 0.5.0

- New: `web/`, a static demo site (raw WebGL 3D hero, preset picker, local screen-recording demo). No build step, no dependencies, deployable to Vercel. The desktop app is unchanged and stays lightweight.
- New: `tools/export_presets.py` generates `web/presets.json` from the Python presets (`--check` fails if stale); a unit test keeps them in sync.
- The 3D scene shows one still frame on weak devices or with reduced motion, falls back to a CSS gradient without WebGL, and pauses when hidden.
- Browsers cannot push RTMP to Twitch or YouTube; the capture demo only records a file locally.
- CI also runs the web tests with Node.

## 0.4.0

- New: portable mode. With a `portable.flag` file next to the app (or `LIGHTSTREAM_PORTABLE=1`), settings are kept in `./data` instead of your user profile.
- New: a copy of ffmpeg placed in `ffmpeg/` (or next to the app) is used before the one on PATH.
- New: `python tools/build_portable.py` builds `lightstream-portable.zip` (no binaries added).
- `doctor` and the window title show when portable mode is on.

## 0.3.0

- New: `--test-local [FILE]` and a GUI "Test first" button record 10 seconds to a file instead of going live (no stream key needed).
- New: `--mute` (and a GUI checkbox) sends silence; `lightstream devices` lists audio devices on Windows and macOS.
- Faster start: encoder test encodes run in parallel, time out after 8 seconds and are cached (was up to about 80 seconds worst case).
- Fix: encoder fallback now matches known FFmpeg encoder error messages instead of loose keywords.
- Fix: a short stream key no longer wipes unrelated saved preferences.
- CI on Linux and Windows (Python 3.9 to 3.12), zipapp build recipe, polished README.
- Key in the process list: documented as not avoidable with FFmpeg RTMP.

## 0.2.0

- Fix: hardware-to-libx264 fallback only when ffmpeg's error names the encoder, so a wrong key or dropped network no longer downgrades quality.
- Fix: STOP and closing the window no longer freeze the GUI; the log box only redraws when text changes (keeps selection and scroll).
- Fix: terminal users see fps/speed progress again.
- Fix: a pasted full rtmp://.../KEY address is never saved to gui.json.

- Docs: beginner step-by-step guide with window mockups, plain-language troubleshooting, stream key help, verified vs unverified table and known limitations.
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
