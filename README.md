# lightweight-livestream (lightstream)

A tiny livestreaming launcher for old laptops and PCs where OBS stutters or lags while you play light games such as Arknights or Limbus Company. It has **no dependencies except Python and FFmpeg**. It builds one lean FFmpeg command (low delay, no B-frames, small buffer, hardware encoder when available), runs it at low priority so your game wins, and reconnects automatically if the network drops.

Streams to Twitch, YouTube or any custom RTMP server.

## Install (Windows, easiest)

1. Install [Python 3.8+](https://www.python.org/downloads/) (tick "Add Python to PATH").
2. Download [FFmpeg for Windows](https://www.gyan.dev/ffmpeg/builds/) and put `ffmpeg.exe` in a folder on your PATH.
3. Get this project (Code > Download ZIP) and unzip it.
4. Open `launchers\start-stream.bat` in Notepad, set `PLATFORM` (`twitch` or `youtube`) and `PRESET`, save.
5. Double-click it, paste your stream key when asked, and play. Press Ctrl+C to stop.

Check your setup any time: `python -m lightstream doctor` (with `set PYTHONPATH=src`), or `pip install .` once, then use `lightstream doctor`.

## Install (Linux / macOS)

```sh
pip install .            # or: export PYTHONPATH=src
lightstream doctor
STREAM_KEY=your_key lightstream start --platform twitch --preset light
# or: ./launchers/start-stream.sh twitch light
```

## Easy window (beginners and kids)

Double-click `launchers/start-gui.bat` (Windows) or run `./launchers/start-gui.sh`, or `lightstream gui`.
Three steps: 1 pick where to stream, 2 paste your stream key, 3 pick how strong your PC is. Then press the big green START. The banner says Offline, Starting, LIVE, Reconnecting or Problem, and "Check my PC" tests FFmpeg. Closing the window stops the stream. Your choices are remembered, but the stream key is never saved or shown in the log. Uses only Python's built-in tkinter. Status: window rendering is UNVERIFIED (no display in the test sandbox); the logic behind it is unit tested.

## Presets

| Preset | Resolution | FPS | Video kbps | Use for |
|---|---|---|---|---|
| `potato` | 640x360 | 24 | 700 | oldest PCs, weak Wi-Fi, emulators |
| `light` (default) | 854x480 | 30 | 1000 | old laptops, Arknights, Limbus Company |
| `balanced` | 1280x720 | 30 | 2500 | decent PCs or hardware encoder |
| `720p60` | 1280x720 | 60 | 4000 | fast games, needs a good PC |

Override anything: `--fps 30 --res 960x540 --bitrate 1500`. Invalid values (such as `--fps 0` or a negative `--bitrate`) are rejected. If FFmpeg keeps failing, lightstream gives up after 5 quick failures in a row. Settings priority: command line, then config file (`lightstream init` writes an example), then preset.

## Arknights / Limbus Company tips

- **Mobile emulator** (BlueStacks, LDPlayer, MuMu): use `--preset potato` or `light` and `--window "exact window title"` (Windows) so only the game is captured, not your whole desktop.
- Run the game windowed or borderless, not exclusive fullscreen.
- Both games are fine at 30 FPS (or 24 with `potato`). Higher FPS costs CPU and gains little.
- Lower the emulator's own FPS and resolution and give it fewer CPU cores, leaving one for streaming.
- Close browsers and other apps. Use wired ethernet if you can.
- If it still lags, drop to `potato`, then lower `--bitrate`. A hardware encoder (NVIDIA, Intel QuickSync, AMD) is used only if a tiny test encode succeeds on your machine, otherwise it falls back to software `libx264`; use `--software` to skip hardware, or `--encoder NAME` to force one.
- **Black picture?** `--window` uses Windows gdigrab, which often captures black for hardware-accelerated emulator windows (BlueStacks, LDPlayer, MuMu). If so, drop `--window` to capture the whole desktop, or try the emulator's DirectX/software render mode.
- Window and desktop captures keep their aspect ratio and get black bars when it differs from the preset, instead of being stretched.
- Audio: pass `--audio-device "Device name"` (Windows dshow name, run `ffmpeg -list_devices true -f dshow -i dummy`). Without it, Windows streams silent audio.

## Stream key safety

The key is read from the `STREAM_KEY` environment variable or typed at a hidden prompt (asked by lightstream itself, also from the Windows launcher). It is never stored by lightstream, and it is hidden (`****`) in everything lightstream prints. Limitation: RTMP puts the key in the FFmpeg command line, so other local processes running as your user may be able to see it in the process list. Custom URLs that carry their own tokens are not redacted beyond the key. Never share your key or commit it.

## Commands

`lightstream doctor`, `presets`, `init`, `start [--platform twitch|youtube|custom] [--url RTMP_URL] [--preset NAME] [--fps N] [--res WxH] [--bitrate K] [--window TITLE] [--audio-device NAME] [--encoder NAME] [--software] [--dry-run]`

`--dry-run` prints the FFmpeg command without streaming.

## Verification status

| Item | Status | Evidence |
|---|---|---|
| Command building (all OSes, encoders) | VERIFIED (as strings) | unit tests |
| Preset, config precedence, key handling | VERIFIED | unit tests |
| Key redaction in printed output | VERIFIED | unit tests, dry run |
| Reconnect/backoff logic | VERIFIED | unit tests with fake process |
| Real capture and streaming | UNVERIFIED | no FFmpeg, display or network in dev sandbox |
| Test-encode fallback and retry cap logic | VERIFIED (fake process) | unit tests; no real GPU or FFmpeg run |
| Hardware encoder flags (NVENC, QSV, AMF, VAAPI, VideoToolbox) | UNVERIFIED | never run on real hardware |
| Windows window capture, dshow audio, low priority | UNVERIFIED | not run on Windows |
| Actual lag/CPU improvement vs OBS | UNVERIFIED | not measured |

## Limitations

No GUI, no scenes/overlays/webcam mixing, RTMP only, screen capture via gdigrab (Windows), x11grab (Linux X11, not Wayland, display fixed to `:0.0`) and avfoundation (macOS, video device index is fixed at 1 and may point at a camera; only the audio index is configurable via `--audio-device`). Reports of what works on your hardware are welcome.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
```
