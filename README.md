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

## Presets

| Preset | Resolution | FPS | Video kbps | Use for |
|---|---|---|---|---|
| `potato` | 640x360 | 24 | 700 | oldest PCs, weak Wi-Fi, emulators |
| `light` (default) | 854x480 | 30 | 1000 | old laptops, Arknights, Limbus Company |
| `balanced` | 1280x720 | 30 | 2500 | decent PCs or hardware encoder |
| `720p60` | 1280x720 | 60 | 4000 | fast games, needs a good PC |

Override anything: `--fps 30 --res 960x540 --bitrate 1500`. Settings priority: command line, then config file (`lightstream init` writes an example), then preset.

## Arknights / Limbus Company tips

- **Mobile emulator** (BlueStacks, LDPlayer, MuMu): use `--preset potato` or `light` and `--window "exact window title"` (Windows) so only the game is captured, not your whole desktop.
- Run the game windowed or borderless, not exclusive fullscreen.
- Both games are fine at 30 FPS (or 24 with `potato`). Higher FPS costs CPU and gains little.
- Lower the emulator's own FPS and resolution and give it fewer CPU cores, leaving one for streaming.
- Close browsers and other apps. Use wired ethernet if you can.
- If it still lags, drop to `potato`, then lower `--bitrate`. A hardware encoder (NVIDIA, Intel QuickSync, AMD) is picked automatically when found; use `--software` to turn that off.
- Audio: pass `--audio-device "Device name"` (Windows dshow name, run `ffmpeg -list_devices true -f dshow -i dummy`). Without it, Windows streams silent audio.

## Stream key safety

The key is read from the `STREAM_KEY` environment variable or typed at a hidden prompt. It is never stored by lightstream, and it is hidden (`****`) in everything printed. Never share your key or commit it.

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
| Hardware encoder flags (NVENC, QSV, AMF, VAAPI, VideoToolbox) | UNVERIFIED | never run on real hardware |
| Windows window capture, dshow audio, low priority | UNVERIFIED | not run on Windows |
| Actual lag/CPU improvement vs OBS | UNVERIFIED | not measured |

## Limitations

No GUI, no scenes/overlays/webcam mixing, RTMP only, screen capture via gdigrab (Windows), x11grab (Linux X11, not Wayland) and avfoundation (macOS, device indexes may need `--audio-device`). Reports of what works on your hardware are welcome.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
```
