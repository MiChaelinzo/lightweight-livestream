# lightstream

[![CI](https://github.com/MiChaelinzo/lightweight-livestream/actions/workflows/ci.yml/badge.svg)](https://github.com/MiChaelinzo/lightweight-livestream/actions/workflows/ci.yml)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

<p align="center">
  <img src="web/img/gui-dashboard-light.webp" alt="lightstream Dashboard, light theme" width="46%">
  <img src="web/img/gui-dashboard-dark.webp" alt="lightstream Dashboard, dark theme" width="46%">
</p>
<p align="center"><sub>Real screenshots, rendered on Linux under Xvfb; fonts differ on Windows.</sub></p>

**Go live from an old PC without the lag.** lightstream is a tiny launcher for old laptops and PCs where OBS stutters while you play light games such as Arknights or Limbus Company. It needs only Python and FFmpeg.

- **One window, 3 steps.** Pick a site, paste your key, pick your PC strength, press START.
- **Lean by design.** One low-delay FFmpeg command, no B-frames, small buffer, hardware encoder when a test encode proves it works.
- **Plays nice.** Runs at low priority so your game wins.
- **Hard to break.** Reconnects with backoff, falls back to software encoding if a GPU encoder fails, and never prints or saves your key.
- **Safe to try.** `--test-local` records 10 seconds to a file instead of going live. `--mute` sends silence.
- Streams to Twitch, YouTube, Facebook Live (RTMPS) or any custom RTMP or SRT server.
- **New in 0.18:** architecture-labelled desktop release plans for Windows x86_64 (portable ZIP and per-user MSI), macOS arm64 (app ZIP, DMG, PKG), and Linux x86_64 (tar.gz, AppImage, deb, rpm); a frozen-app `--self-test`; one checked version invariant; and an installable offline web companion for Android/iPhone home screens. The Linux tarball was built and self-tested locally. Every other native package and the billing-locked release workflow remain UNVERIFIED. The mobile install is a companion, not an APK/AAB/IPA broadcaster. See [the install guide](docs/INSTALLING.md) and [v0.18 status map](docs/architecture/V018-MAP.md).
- **In 0.17:** an opt-in phone remote (GUI only, `127.0.0.1` by default, home network only by a second explicit box, random token that is never saved) that can trigger Emergency, Restore and Stop but cannot start a stream, and a Session timeline box on the Dashboard. Tested with loopback sockets; a real phone and a real home network are UNVERIFIED. See [docs/architecture/V017-MAP.md](docs/architecture/V017-MAP.md).
- **In 0.16:** opt-in `--guardian` and `--auto-survival` (off by default; every step restarts the encoder), a bandwidth trend predictor (synthetic tests only), a session timeline in the end-of-session output, profiles `potato_pc`, `office_laptop` and `budget_gaming`, idle budgets (startup, RSS, CPU) measured under Xvfb. Real machines UNVERIFIED. See [docs/architecture/V016-MAP.md](docs/architecture/V016-MAP.md).
- **New in 0.15:** eight GUI themes and a reduce-motion setting, `lightstream audio-check`, Teaching and Meeting audio profiles, copilot insights, `lightstream highlights` (heuristic clips, 9:16 export) and `dashboard`, a plugin runtime (`lightstream plugins`, not yet connected to `start`) and `tools/benchlab.py` (OBS and Streamlabs columns are UNKNOWN). Details in [docs/FEATURES.md](docs/FEATURES.md) and the [CHANGELOG](CHANGELOG.md).
- **In 0.14:** the health score uses the real dropped-frame percent, the Recording page has a persistent-ingest checkbox, the GUI banner states can be rendered for review, and this README is shorter (details moved to [docs/FEATURES.md](docs/FEATURES.md)). Earlier highlights are listed there and in the [CHANGELOG](CHANGELOG.md). Real platforms, Windows and macOS are UNVERIFIED; see [docs/ROADMAP.md](docs/ROADMAP.md) for the honest status of each area.

**More:** [Install guide](docs/INSTALLING.md) | [Features and guides](docs/FEATURES.md) | [Documentation index](docs/README.md) | [Roadmap](docs/ROADMAP.md) | [Benchmarks](docs/BENCHMARKS.md) | [Web companion](web/)

## Download (no Python, no Git)

Get the app from the [Releases page](https://github.com/MiChaelinzo/lightweight-livestream/releases). The v0.18 workflow is configured but UNVERIFIED because GitHub Actions is billing-locked. Treat an absent release as expected until the maintainer fixes billing and publishes one.

| Platform | v0.18 workflow output | Implemented and tested locally | Honest status |
|---|---|---|---|
| Windows 10/11 x86_64 | portable ZIP and per-user MSI | deterministic layout, WiX source, metadata and command tests | Workflow-only; exe and MSI install UNVERIFIED |
| macOS 11+ arm64 | app ZIP, DMG with Applications link, PKG to `/Applications` | deterministic metadata and command tests | Workflow-only; app/install/signing UNVERIFIED |
| Linux x86_64 | tar.gz, AppImage, deb, rpm | real tar.gz built, extracted, and frozen self-test passed; other formats have metadata/command tests | tar package integrity VERIFIED locally; capture and installed formats UNVERIFIED |
| Android, iPhone, iPad | installable companion web app | manifest, icons, CSP, cache fingerprint and offline rules pass Node tests | Browser installation UNVERIFIED; not a broadcaster |
| Android/iOS broadcaster | no artifact | none | NOT SUPPORTED; requires a separate native product |

Exact native names include version, platform, and architecture, for example `LightStream-0.18.0-windows-x86_64-unsigned.msi`, `LightStream-0.18.0-macos-arm64-unsigned.dmg`, and `LightStream-0.18.0-linux-x86_64.AppImage`. Signed artifacts use a different label only when optional secret-based signing succeeds.

- **FFmpeg is not included.** The first-run window explains where to get it and offers **Choose ffmpeg file...**.
- **Unsigned warnings are expected.** Verify `SHA256SUMS.txt`, then follow the Windows SmartScreen or macOS Gatekeeper steps in [docs/INSTALLING.md](docs/INSTALLING.md).
- **Run package integrity checks without a window:** `lightstream gui --self-test`, or run a frozen executable with `--self-test`. Add `--self-test-json` for structured output. Missing FFmpeg is a warning, not a failed app-integrity check.
- **Mobile means companion only.** Android Chrome and iPhone/iPad Safari can add the web companion to the home screen. There is no APK, AAB, or IPA broadcaster.

See [docs/INSTALLING.md](docs/INSTALLING.md) for exact install, FFmpeg, uninstall, checksum, unsigned-warning, and troubleshooting steps.

Prefer Python? Use the steps below instead.

## Quick start (3 steps)

1. Install: `pip install .` (or `export PYTHONPATH=src`).
2. Check: `lightstream doctor`.
3. Go: `lightstream gui` for the window, or the commands below.

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

### Alternative: one-time setup with Python (Windows)

1. **Install Python.** Download it from [python.org](https://www.python.org/downloads/) (3.8 or newer). In the installer, tick **"Add Python to PATH"**, then click Install.
2. **Install FFmpeg** (the part that sends your video). Download it from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), unzip it, and put `ffmpeg.exe` in a folder that is on your PATH.
3. **Get this project.** On GitHub press Code, then Download ZIP, then unzip it.
4. **Double-click `launchers\start-gui.bat`.** The window opens.

On Linux or macOS, run `./launchers/start-gui.sh` (or `lightstream gui` after `pip install .`).

### Every time you stream

1. Pick **where to stream** (Twitch, YouTube, Facebook Live or Other site).
2. Paste your **secret stream key** (see "Where do I find my stream key?" below).
3. Pick **how good your PC is**. Not sure? Choose **Old PC (light)**.
4. Press the big green **START** (or press Enter).
5. Want to check first? Press **Test first** to record 10 seconds to `lightstream-test.mkv` without going live.
6. Wait for the banner to say **YOU ARE LIVE!** Then open your game.
7. Press the red **STOP** when you are done. Closing the window also stops the stream.

What the window looks like, with ASCII layouts of the Offline and LIVE states and banner colors, is in [docs/FEATURES.md](docs/FEATURES.md#what-the-window-looks-like).

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

1. Open `launchers\start-stream.bat` in Notepad, set `PLATFORM` (`twitch`, `youtube` or `facebook`) and `PRESET`, save.
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

## More features

Hardware profiles, scenes and webcam overlay, recording a copy, noise suppression, bandwidth optimizer, performance profiles, Emergency and backup ingest, insights and auto-scale, the sidebar window and the browser companion are described in [docs/FEATURES.md](docs/FEATURES.md), with their status tables.

## Stream key safety

The key is read from the `STREAM_KEY` environment variable or typed at a hidden prompt (asked by lightstream itself, also from the Windows launcher). It is never stored by lightstream, and it is hidden (`****`) in everything lightstream prints. Limitation: RTMP puts the key in the FFmpeg command line, so other local processes running as your user may be able to see it in the process list. Custom URLs that carry their own tokens are not redacted beyond the key. Never share your key or commit it.

## Commands

`lightstream doctor`, `devices`, `presets`, `profiles`, `init`, `gui [--self-test [--self-test-json]]`, `setup [--yes] [--platform NAME] [--upload-mbps N]`, `bandwidth [--platform NAME] [--upload-mbps N | --measure-url URL] [--hardware NAME]`, `scenes list|validate|example|export|import [--scenes-file FILE]`, `start [--platform twitch|youtube|facebook|custom] [--url URL] [--preset NAME] [--fps N] [--res WxH] [--bitrate K] [--window TITLE] [--audio-device NAME] [--video-device INDEX] [--mute] [--test-local [FILE]] [--keep-trying] [--encoder NAME] [--software] [--scene NAME] [--scenes-file FILE] [--record [FILE]] [--no-record] [--analytics] [--profile NAME] [--stream-preset NAME] [--audio-profile NAME] [--noise off|light|ai] [--noise-model PATH] [--hardware auto|intel_hd|intel_hd_optimized|nvidia_mx|mx250_streamer|optimus_mx250|nvidia|generic] [--potato-stream 2000|4000] [--grayscale] [--skip-static] [--rate-mode vbr|cbr] [--persistent-ingest] [--guardian] [--auto-survival] [--dry-run]`

`--keep-trying` never gives up reconnecting. `--video-device` (macOS) picks the screen. On Linux the capture follows `$DISPLAY`.

`--dry-run` prints the FFmpeg command without streaming. `--test-local [FILE]` records 10 seconds (default `lightstream-test.mkv`) and needs no stream key.

## Web demo (Vercel)

`web/` is a separate static companion site: a 3D hero, preset picker, install help, local screen-recording demo, and overlay shell. Its manifest lets Android Chrome and iPhone/iPad Safari add it to the home screen, and its versioned service worker caches the static companion shell. It cannot capture a phone screen or push RTMP, and it never asks for a stream key. Manifest/install metadata, CSP, and cache behavior are VERIFIED by Node tests; real Android/iOS installation, WebGL on a real GPU, Firefox, and Safari are UNVERIFIED. It is not an APK, AAB, or IPA broadcaster.

## Verification status

| Item | Status | Evidence |
|---|---|---|
| GUI controller logic (validation, banner states, prefs, key never saved or logged) | VERIFIED | unit tests, no display needed |
| GUI window rendering on Linux (layout, fonts, buttons, colors) | PARTIALLY VERIFIED (Linux only) | real screenshots captured under Xvfb with `tools/ui_snapshots.py` (see [docs/DEV-RENDERING.md](docs/DEV-RENDERING.md)); read by eye, no automated pixel assertions |
| GUI look on Windows and macOS, real fonts and DPI scaling | UNVERIFIED | never run on those systems |
| GUI callback crash capture in a live Tk window | UNVERIFIED | the report function is unit tested; the Tk hook was not exercised on a display |
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
| Performance profiles, stream presets, audio profile selection, thread math, optimizer rules, network stability score, auto-scale ladder and hysteresis, readiness scoring, bench report schema (0.9.0) | VERIFIED | unit tests with fake clocks and injected callables |
| Ten audio filter chains accepted by FFmpeg (0.9.0) | VERIFIED | run through ffmpeg 7.0.2 static build on a sine input in the dev sandbox; a bad chain was rejected |
| Real libx264 synthetic encode and bench numbers (0.9.0) | VERIFIED (this machine only) | `docs/BENCHMARKS.md`, Linux x86_64 sandbox; not representative of low-end laptops |
| Restart through the reconnect path (auto-scale) | PARTIALLY VERIFIED | exercised against a real subprocess, not a real capture or RTMP stream |
| Auto-scale on real games and streams, threshold fit to real hardware | UNVERIFIED | not run |
| Game FPS gain from Gaming First (thread cap, CPU affinity) | UNVERIFIED | not measured |
| Telemetry on Windows and macOS, `nvidia-smi` GPU readings, GUI telemetry row and new controls | UNVERIFIED | Linux parsing tested on sample text only; no display |
| Frozen `--self-test` (imports, Tcl/Tk, app/portable roots, writable state, FFmpeg status) | VERIFIED in source and a real Linux x86_64 tarball | unit tests plus extracted v0.18 PyInstaller executable; missing FFmpeg correctly warned and returned 0 |
| Linux v0.18 PyInstaller tar.gz, architecture name and checksum | VERIFIED on this Linux sandbox | built with PyInstaller 6.11.1, extracted, frozen self-test passed; GUI/capture not run |
| Windows portable ZIP/MSI, macOS app ZIP/DMG/PKG, Linux AppImage/deb/rpm | UNVERIFIED native artifacts | deterministic source/metadata/command tests use fake native tools; not built or installed here |
| Release workflow `release.yml` | UNVERIFIED | YAML parses and static tests cover provenance, pins, matrix, checks and secret-only signing; Actions is billing-locked and has never run |
| Installable web companion manifest and offline shell | VERIFIED as static logic only | Node tests cover manifest fields, icons, install metadata, CSP, registration and cache fingerprint; real browser installation UNVERIFIED |
| First-run FFmpeg dialog on a real GUI | UNVERIFIED | no display; guidance and validator logic are unit tested |

## Known limitations, portable mode and standalone builds

See [docs/FEATURES.md](docs/FEATURES.md#known-limitations) for the limitations list, [portable mode](docs/FEATURES.md#portable-mode-usb-stick-friendly) and [building a standalone app](docs/FEATURES.md#build-a-standalone-app-optional). Key points: Windows window capture can show black for GPU emulators, RTMP only, and the stream key is visible to local processes in the FFmpeg command line. The zipapp recipe is VERIFIED on Linux; the PyInstaller recipe is UNVERIFIED.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
node --test "web/test/*.test.js"
python3 tools/export_presets.py --check
python3 tools/generate_icons.py --check
python3 tools/check_version.py
python3 tools/page_weight.py
```

CI runs the source checks on Linux and Windows. The billing-locked release workflow repeats them on every native runner before packaging.
