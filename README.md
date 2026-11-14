# lightstream

[![CI](https://github.com/MiChaelinzo/lightweight-livestream/actions/workflows/ci.yml/badge.svg)](https://github.com/MiChaelinzo/lightweight-livestream/actions/workflows/ci.yml)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

**Go live from an old PC without the lag.** lightstream is a tiny launcher for old laptops and PCs where OBS stutters while you play light games such as Arknights or Limbus Company. It needs only Python and FFmpeg.

- **One window, 3 steps.** Pick a site, paste your key, pick your PC strength, press START.
- **Lean by design.** One low-delay FFmpeg command, no B-frames, small buffer, hardware encoder when a test encode proves it works.
- **Plays nice.** Runs at low priority so your game wins.
- **Hard to break.** Reconnects with backoff, falls back to software encoding if a GPU encoder fails, and never prints or saves your key.
- **Safe to try.** `--test-local` records 10 seconds to a file instead of going live. `--mute` sends silence.
- Streams to Twitch, YouTube or any custom RTMP server.

## Quick start

```sh
pip install .                       # or: export PYTHONPATH=src
lightstream doctor                  # checks ffmpeg and your encoder
lightstream gui                     # the easy window
# or the command line:
lightstream start --test-local      # record 10 seconds, nothing goes live
STREAM_KEY=your_key lightstream start --platform twitch --preset light
```

Installing also gives you the `lightstream-gui` command. No install? Use `python -m lightstream ...` with `PYTHONPATH=src`.

## Easiest way: the window app

No typing commands needed. If you are a kid, ask a parent to help with steps 1 to 3 once. After that it is just click and go.

### One-time setup (Windows)

1. **Install Python.** Download it from [python.org](https://www.python.org/downloads/) (3.8 or newer). In the installer, tick **"Add Python to PATH"**, then click Install.
2. **Install FFmpeg** (the part that sends your video). Download it from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), unzip it, and put `ffmpeg.exe` in a folder that is on your PATH.
3. **Get this project.** On GitHub press Code, then Download ZIP, then unzip it.
4. **Double-click `launchers\start-gui.bat`.** The window opens.

On Linux or macOS, run `./launchers/start-gui.sh` (or `lightstream gui` after `pip install .`).

### Every time you stream

1. Pick **where to stream** (Twitch, YouTube or Other site).
2. Paste your **secret stream key** (see "Where do I find my stream key?" below).
3. Pick **how good your PC is**. Not sure? Choose **Old PC (light)**.
4. Press the big green **START** (or press Enter).
5. Want to check first? Press **Test first** to record 10 seconds to `lightstream-test.mkv` without going live.
6. Wait for the banner to say **YOU ARE LIVE!** Then open your game.
7. Press the red **STOP** when you are done. Closing the window also stops the stream.

### What the window looks like

Before you start (Offline):

```
+--------------------------------------------------+
|                 Let's go live!                   |
|                                                  |
| 1. Where do you want to stream?                  |
| [ Twitch                                     v ] |
| (Other site only) address starting with rtmp://  |
| [                                              ] |
|                                                  |
| 2. Paste your secret stream key                  |
| [ ********************                         ] |
| [ ] Show the key                                 |
| Never show your key to anyone. It is not saved.  |
|                                                  |
| 3. How good is your PC?                          |
| [ Old PC (light)                             v ] |
| Not sure? Pick 'Old PC (light)'.                 |
|                                                  |
| [      START (green)     ] [   STOP (greyed)   ] |
|                                                  |
| +----------------------------------------------+ |
| | Offline. Press START when you are ready.     | |
| +----------------------------------------------+ |
| [Check my PC]                                    |
| [Show advanced options]                          |
| +----------------------------------------------+ |
| | (log: what the program is doing)             | |
| +----------------------------------------------+ |
+--------------------------------------------------+
```

While streaming (LIVE):

```
| [  START (greyed)  ] [      STOP (red)       ]   |
| +----------------------------------------------+ |
| |              YOU ARE LIVE!  (green)          | |
| +----------------------------------------------+ |
```

Banner colors: grey = Offline, orange = Starting or Reconnecting, green = LIVE, red = Problem. If the PC is too slow the green banner says "LIVE, but your PC is struggling. Try a weaker setting." Then STOP and pick a weaker option in step 3.

### Where do I find my stream key?

- **Twitch:** log in, open your Creator Dashboard, then Settings, then Stream. Press "Copy" next to Primary Stream key.
- **YouTube:** open YouTube Studio, press Create, then Go live, then Stream. Copy the Stream key (you may need to enable live streaming first, which can take up to 24 hours).
- **Other site:** use the address the site gives you (it starts with `rtmp://`) and its key.

Parent tip: the key is like a password for the channel. Keep it private, and if it ever leaks, reset it on the site. Lightstream never saves the key and never prints it in its log.

### Something went wrong? (plain words)

| What you see | What it means | What to do |
|---|---|---|
| The window does not open | Python has no window support (tkinter) or there is no screen | Windows: reinstall Python and keep "tcl/tk" ticked. Linux: install the `python3-tk` package. Or use the command line below |
| "ffmpeg not found" or Check my PC says missing | FFmpeg is not installed where the PC can find it | Redo setup step 2 and restart the window |
| Banner is red: Problem | The stream could not start | Read the red "What is wrong?" text under the banner. Check the key and your internet |
| Twitch or YouTube says no signal | Wrong key, or the wrong site was picked in step 1 | Copy the key again, pick the right site |
| Orange: Reconnecting | Your internet blinked | Wait. It tries again by itself. After 5 quick failures in a row it stops, and the advanced option "Keep trying if the internet drops" makes it never give up |
| LIVE, but your PC is struggling | The PC cannot keep up | Press STOP, choose a weaker setting in step 3, close other programs, start again |
| Viewers see a black picture | The capture cannot see your game window (common with BlueStacks, LDPlayer, MuMu) | Leave the advanced "Window title" empty to share the whole screen, or switch the emulator to DirectX or software rendering |
| No sound | Audio device not found | Run `lightstream devices`, then type the name in advanced options. Tick "Mute" for silence on purpose |

Still stuck? Press **Check my PC** and read the answer, or ask a parent to try the command line below.

## Command line (for advanced users)

### Windows

1. Open `launchers\start-stream.bat` in Notepad, set `PLATFORM` (`twitch` or `youtube`) and `PRESET`, save.
2. Double-click it, paste your stream key when asked, and play. Press Ctrl+C to stop.

Check your setup any time: `python -m lightstream doctor` (with `set PYTHONPATH=src`), or `pip install .` once, then use `lightstream doctor`.

### Linux / macOS

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

Override anything: `--fps 30 --res 960x540 --bitrate 1500`. Invalid values (such as `--fps 0` or a negative `--bitrate`) are rejected. If FFmpeg keeps failing, lightstream gives up after 5 quick failures in a row. Settings priority: command line, then config file (`lightstream init` writes an example), then preset.

## Arknights / Limbus Company tips

- **Mobile emulator** (BlueStacks, LDPlayer, MuMu): use `--preset potato` or `light` and `--window "exact window title"` (Windows) so only the game is captured, not your whole desktop.
- Run the game windowed or borderless, not exclusive fullscreen.
- Both games are fine at 30 FPS (or 24 with `potato`). Higher FPS costs CPU and gains little.
- Lower the emulator's own FPS and resolution and give it fewer CPU cores, leaving one for streaming.
- Close browsers and other apps. Use wired ethernet if you can.
- If it still lags, drop to `potato`, then lower `--bitrate`. A hardware encoder (NVIDIA, Intel QuickSync, AMD) is used only if a tiny test encode succeeds on your machine, otherwise it falls back to software `libx264`; if it later fails twice in a row with an error naming the encoder, the stream switches to `libx264` (wrong keys or network drops do not trigger this); use `--software` to skip hardware, or `--encoder NAME` to force one.
- **Black picture?** `--window` uses Windows gdigrab, which often captures black for hardware-accelerated emulator windows (BlueStacks, LDPlayer, MuMu). If so, drop `--window` to capture the whole desktop, or try the emulator's DirectX/software render mode.
- Window and desktop captures keep their aspect ratio and get black bars when it differs from the preset, instead of being stretched.
- Audio: run `lightstream devices` (Windows, macOS) to list names, then pass `--audio-device "Device name"` (macOS wants the index). Without it, Windows streams silent audio. `--mute` forces silence on any OS.

## Stream key safety

The key is read from the `STREAM_KEY` environment variable or typed at a hidden prompt (asked by lightstream itself, also from the Windows launcher). It is never stored by lightstream, and it is hidden (`****`) in everything lightstream prints. Limitation: RTMP puts the key in the FFmpeg command line, so other local processes running as your user may be able to see it in the process list. Custom URLs that carry their own tokens are not redacted beyond the key. Never share your key or commit it.

## Commands

`lightstream doctor`, `devices`, `presets`, `init`, `gui`, `start [--platform twitch|youtube|custom] [--url URL] [--preset NAME] [--fps N] [--res WxH] [--bitrate K] [--window TITLE] [--audio-device NAME] [--video-device INDEX] [--mute] [--test-local [FILE]] [--keep-trying] [--encoder NAME] [--software] [--dry-run]`

`--keep-trying` never gives up reconnecting. `--video-device` (macOS) picks the screen. On Linux the capture follows `$DISPLAY`.

`--dry-run` prints the FFmpeg command without streaming. `--test-local [FILE]` records 10 seconds (default `lightstream-test.mkv`) and needs no stream key.

## Verification status

| Item | Status | Evidence |
|---|---|---|
| GUI controller logic (validation, banner states, prefs, key never saved or logged) | VERIFIED | unit tests, no display needed |
| GUI window rendering (layout, fonts, buttons, colors) | UNVERIFIED | no display in the dev sandbox; mockups above are drawn from the code, not screenshots |
| Command building (all OSes, encoders) | VERIFIED (as strings) | unit tests |
| Preset, config precedence, key handling | VERIFIED | unit tests |
| Key redaction in printed output | VERIFIED | unit tests, dry run |
| Reconnect/backoff, stop, status and stats parsing | VERIFIED (fake process) | unit tests |
| Mute, `--test-local` command, audio device list parsing (sample text) | VERIFIED (as strings) | unit tests; real device output may differ |
| Encoder-failure detection (known FFmpeg messages) | VERIFIED (sample lines) | unit tests; real FFmpeg wording may vary by version |
| CI on Linux and Windows, Python 3.9 to 3.12 | UNVERIFIED | workflow added, not yet run on GitHub |
| Test-encode fallback and retry cap logic | VERIFIED (fake process) | unit tests; no real GPU or FFmpeg run |
| `--help` flags match this README | VERIFIED | checked against `lightstream start --help` |
| Real capture and streaming with real FFmpeg | UNVERIFIED | no FFmpeg, display or network in dev sandbox |
| Hardware encoder flags (NVENC, QSV, AMF, VAAPI, VideoToolbox) | UNVERIFIED | never run on real hardware |
| Windows window capture, dshow audio, low priority | UNVERIFIED | not run on Windows |
| Actual lag/CPU improvement vs OBS | UNVERIFIED | not measured |

## Known limitations

- Window capture on Windows (`--window`) uses gdigrab and often shows black for GPU-accelerated emulators (BlueStacks, LDPlayer, MuMu). Capture the whole desktop instead.
- The hardware encoder check runs short test encodes (8 second timeout each, run in parallel and cached), so worst-case startup is about 8 seconds plus the `-encoders` listing. This is derived from the timeouts, not measured on real hardware.
- RTMP only. No scenes, overlays or webcam mixing.
- Screen capture: gdigrab (Windows), x11grab (Linux X11, not Wayland, follows `$DISPLAY`) and avfoundation (macOS, screen picked with `--video-device`).
- Windows without `--audio-device` streams silent audio.
- The stream key appears in the FFmpeg command line, so other local processes running as your user may see it in the process list. Lightstream hides it in everything it prints. Hiding it from the process list is not feasible with FFmpeg's RTMP output, so on a shared PC use your own user account.
- The window needs Python's tkinter, which some Linux installs lack (`python3-tk`).

Reports of what works on your hardware are welcome.

## Build a standalone app (optional)

Nothing is committed as a binary. To make your own, with [PyInstaller](https://pyinstaller.org) (needs network once):

```sh
pip install pyinstaller .
printf 'from lightstream.gui import main\nmain()\n' > gui_entry.py
pyinstaller --onefile --windowed --name lightstream-gui gui_entry.py
```

Or build a single runnable file with the standard library (needs Python on the target PC):

```sh
python -m zipapp src -m "lightstream.cli:main" -o lightstream.pyz
python lightstream.pyz doctor
```

The zipapp recipe is VERIFIED on Linux (`presets` and `start --help` ran from the `.pyz`). The PyInstaller recipe is UNVERIFIED (not run in the dev sandbox). FFmpeg is not bundled; install it separately.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
```

CI runs the same two commands on Linux and Windows (`.github/workflows/ci.yml`).
