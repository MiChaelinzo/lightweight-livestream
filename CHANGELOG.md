# Changelog

## 0.6.0

Low-end studio release. Real FFmpeg, GPU and webcam behavior of everything below is UNVERIFIED (no FFmpeg, GPU, display or network in the dev sandbox); command text is checked by unit tests only.

- New: hardware profiles (`--hardware auto|intel_hd|nvidia_mx|nvidia|generic`). The GPU is detected when no profile is configured (`wmic` on Windows, `lspci` on Linux). Profiles use fewer threads, smaller capture buffers, a cheap scaler and no lookahead, and Intel HD caps the preset at `light`. `doctor` prints the detected GPU and profile.
- New: scenes file (`scenes.json` next to `config.json`): screen, window or "browser" capture, one webcam overlay (corner, size, chroma key or plain blur), image and text overlays. Commands: `lightstream scenes list|validate|example` (the example writer never overwrites a file) and `start --scene NAME --scenes-file FILE`. A scene is chosen at start; switching scenes while live is not implemented (stop and start again).
- New: `start --record [FILE]` saves a local Matroska copy while streaming, using one encode through the tee muxer. A failing file does not stop the stream.
- New: noise suppression `--noise off|light|ai`. `light` is a rumble cut plus `afftdn`. `ai` uses `arnndn` with an RNNoise `.rnnn` model you download yourself (not bundled).
- New: `lightstream bandwidth` (typed upload speed or `--measure-url` to an endpoint you control) recommends a preset and bitrate with 30% headroom.
- New: stream health summary at the end of a CLI session and a health advice line in the window (speed, dropped frames, reconnects, plain-words advice).
- New: `lightstream setup` wizard and a "One-click setup" button in the window. At most two questions, never saves the stream key.
- New: window gets a "Record a copy" checkbox and a scene dropdown under Advanced.
- Behavior change: the CLI now passes `on_status` to the runner (it feeds the health tracker). Because the runner only echoes raw ffmpeg progress lines to the terminal when no `on_status` is given, the CLI prints its own `fps=... speed=...` line while live instead of ffmpeg's raw progress text.
- Fix: a missing scenes file is reported in plain words instead of a traceback.
- Not done: AI background removal (see README). Only chroma key and a plain webcam blur exist.
- Version bumped to 0.6.0.

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
