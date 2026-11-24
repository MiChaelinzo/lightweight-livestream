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
- Streams to Twitch, YouTube, Facebook Live (RTMPS) or any custom RTMP server.

## Download (no Python, no Git)

Get the app from the [Releases page](https://github.com/MiChaelinzo/lightweight-livestream/releases). The release workflow is UNVERIFIED (never run yet), so a release may not exist until the maintainer publishes one.

| Platform | Download | How to start |
|---|---|---|
| Windows | `LightStream-0.11.0-windows-portable.zip` | Unzip, double-click `LightStream.exe` |
| macOS | `LightStream-0.11.0-macos.zip` (or `.dmg`) | Open it, move `LightStream.app` to Applications, right-click > Open (Apple Silicon only, no Intel build) |
| Linux | `LightStream-0.11.0-linux-x86_64.tar.gz` | `tar xzf` it, run `./LightStream` from a desktop session (needs a glibc as new as Ubuntu's current runner image; older distros may fail) |

- **FFmpeg is not included.** On first run the app tells you if it is missing and offers a download link and a "Choose ffmpeg file..." button.
- **Windows SmartScreen** may say "Windows protected your PC" because the app is unsigned. Click More info, then Run anyway. **macOS** may block it: right-click > Open, or run `xattr -d com.apple.quarantine LightStream.app`.
- Android, iOS, `.msi`, `.deb`, `.rpm` and AppImage are not provided. See [docs/RELEASING.md](docs/RELEASING.md).

Prefer Python? Use the steps below instead.

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

## Low-end studio features (0.6.0)

Everything in this section is aimed at old laptops. It lowers work by design (mechanisms below); no CPU or RAM numbers have been measured. See the status table at the end of this section.

### Hardware profiles (Intel HD, MX250)

`lightstream doctor` prints the detected GPU and profile. `start` detects the GPU when no profile is set (`--hardware auto`, the default). **This changes the default `start` command on every machine**: even an unknown GPU gets the `generic` profile (`-filter_threads 1`, `-sws_flags fast_bilinear`, `-threads 2` for libx264, a small input probe). Plain `build_command` without a profile is unchanged, or you can pick `intel_hd`, `nvidia_mx`, `nvidia` or `generic`, or set `"hardware"` in `config.json`.

Mechanisms: fewer FFmpeg threads (`-filter_threads 1`, `-threads 2` for libx264), a smaller probe size (capture buffers are left at their defaults), the cheapest scaler (`fast_bilinear`), no lookahead on hardware encoders, one audio/video path. Intel HD uses Quick Sync (`h264_qsv`) and caps the preset at `light` unless you pass `--preset` yourself or set `force_preset` in `config.json`; with a cap in effect the preset you did not pick explicitly is lowered. On Linux, Intel tries Quick Sync, then VAAPI. MX series uses NVENC first and Quick Sync second.

Caveats (UNVERIFIED on real hardware): an Intel HD GPU has to share system RAM with the game, Quick Sync needs a recent driver, and MX250 NVENC session support depends on the driver. If a hardware encoder fails to start, the existing fallback switches to software encoding.

### Scenes, webcam overlay and "browser source"

A scene is a screen capture plus light overlays, kept in `scenes.json` next to `config.json`.

```sh
lightstream scenes example      # writes an example file, never overwrites
lightstream scenes validate
lightstream scenes list
lightstream start --scene game-with-webcam
```

The example has a webcam overlay, a window-capture "browser source" and a chroma key webcam. Source kinds: `screen`, `window`/`browser` (capture one window by title, optional crop), `webcam` (one per scene, 5 to 35 percent of the frame, at most 15 fps), `image` and `text`.

Browser source trade-off: lightstream has no embedded browser engine (that would add a heavy dependency and RAM use). To show a web overlay, open it in any browser window and capture that window by title. Window capture is Windows only (`gdigrab`) and often shows black for GPU-accelerated windows.

Scene switching: the scene is chosen at START. Switching while live is NOT implemented; stop and start again. The window's scene dropdown (under Advanced) also applies at START.

Webcam and fonts (UNVERIFIED): a live webcam feeding `overlay` may stall the stream if the camera clock drifts, and `drawtext` needs a font; set `font_file` on text overlays on ffmpeg builds without fontconfig (common on Windows). Windows drive-letter paths in filter options use a `\:` escape that has not been run against real ffmpeg. If a webcam stalls the stream, remove it from the scene.

Background handling: only chroma key (`chromakey`) and `blur`. `blur` is a plain box blur of the whole webcam picture, not background segmentation.

### Recording a copy

`lightstream start --record [FILE]` (or the "Record a copy" checkbox) encodes once and writes to RTMP and a Matroska file through FFmpeg's tee muxer, so there is no second encode. Matroska survives a crash. The folder is created and checked for write access before starting (an error is printed if it fails), but a write error later (full disk) is ignored so the stream keeps going. After an automatic reconnect the copy goes to a new file (`name-2.mkv`, `name-3.mkv`) so earlier footage is never overwritten. The window saves to `recordings/` in the app data folder with a timestamp and prints the path. `--record` is ignored with `--test-local` (a notice is printed). Since 0.12 the tee maps video and audio explicitly and the live slot aborts on ingest failure so the reconnect loop works; `.mp4` records fragmented MP4, `.webm` is refused, `--rate-mode cbr` is optional (libx264 only). `--persistent-ingest` (opt in) keeps one publisher connection and a continuous file across ingest failures; see [docs/ARCHITECTURE-NOTES.md](docs/ARCHITECTURE-NOTES.md). The path may not contain `| [ ] '`.

### Noise suppression

`--noise light`: a rumble cut plus FFmpeg's built-in `afftdn` FFT denoiser. `--noise ai`: `arnndn` with an RNNoise `.rnnn` model. No model is bundled. Download one yourself, check its license before using it, and pass `--noise-model PATH`. Without the file, `start` stops with a clear error. `arnndn` costs more CPU than `afftdn`, so `light` is cheaper than `ai`. The wizard saves `off` because filtering costs CPU on the machines this targets; turn it on with `--noise light` if your mic is noisy.

### Bandwidth optimizer

```sh
lightstream bandwidth --upload-mbps 3 --platform twitch --hardware intel_hd
lightstream bandwidth --measure-url https://your-server.example/upload
```

Picks the heaviest preset whose video plus audio fits in 70 percent of your upload speed, capped by the platform maximum. `--measure-url` posts 1 MiB to an endpoint you control; no third-party speed test is built in.

### Stream health

The CLI prints a summary at the end of a session (speed, dropped frames, reconnects, longest lag). The window shows one advice line while live. Advice rules: speed under 0.95x means the PC is the limit; low bitrate while speed is fine points at the network; many dropped frames or two or more reconnects get their own advice. Thresholds are fixed constants in `health.py`.

### One-click setup wizard

`lightstream setup` (or the window's "One-click setup" button) detects GPU, CPU threads and RAM, asks at most two questions (platform, upload speed), and writes safe settings to `config.json`. The window button fills the fields and saves nothing until you press START. The stream key is never asked for or saved. With 4 GB RAM or less the preset never goes above `light`.

### Not done

- **AI background removal.** Not implemented. ML segmentation would use a lot of CPU, which conflicts with the ultra-low CPU goal on old laptops, and it needs a model and a heavy dependency. Use a green screen with `chromakey`.
- Mid-stream scene switching, embedded browser source, multi-webcam scenes.

### Status of the 0.6.0 features

| Item | Status | Evidence |
|---|---|---|
| Hardware profile parsing, GPU classification (sample `lspci`/`wmic` text), tuned argv | VERIFIED (as strings) | unit tests |
| `build_command` without a profile or new option unchanged | VERIFIED | golden test and combination sweep |
| Default `start` argv (auto hardware profile applied) | Changed on purpose, see Hardware profiles | unit tests (strings only) |
| Scenes parsing, validation, filter graph text, example file, `scenes` command | VERIFIED (as strings) | unit tests |
| `--record` tee argument, key redaction | VERIFIED (as strings) | unit tests |
| Noise filter text, missing model error | VERIFIED (as strings) | unit tests |
| Bandwidth maths, health tracker, advice rules, wizard config | VERIFIED | unit tests (fake clock, fake probes) |
| GUI controller additions (setup, record, scene list, advice) | VERIFIED | unit tests, no display |
| GUI window layout of the new widgets | UNVERIFIED | no display |
| Real FFmpeg accepting the scene graphs, tee, `arnndn`, `afftdn` | UNVERIFIED | no FFmpeg in the dev sandbox |
| Webcam capture (dshow, v4l2, avfoundation) | UNVERIFIED | no camera |
| Quick Sync / NVENC tuning on Intel HD and MX250 | UNVERIFIED | no such hardware |
| Windows RAM probe, PowerShell and `wmic` GPU detection | UNVERIFIED | not run on Windows (parsing tested on fake output) |
| Real upload measurement with `--measure-url` | PARTIALLY VERIFIED | fake HTTP in tests only |
| Lower CPU/RAM use than before | UNVERIFIED | mechanisms only, not measured |
| AI background removal, mid-stream scene switching | NOT DONE | see Not done |

## Ultra low-end studio (0.7.0)

All of this is optional and off or suggestion-only by default. Real FFmpeg, GPU and webcam behavior is UNVERIFIED (no FFmpeg, GPU or display in the dev sandbox); the tests check pure logic and command text. No CPU or RAM numbers are claimed.

- **Adaptive advisor** (`adaptive.py`): watches speed, fps, dropped frames and reconnects. Speed under 0.90x for 30 seconds suggests the next lighter preset; more than 30 dropped frames in a minute suggests 20% less bitrate; 2 reconnects in 10 minutes suggests `lightstream bandwidth`. It only suggests: nothing is ever applied without you. The CLI prints suggestions at the end of a session; the window controller exposes `recommendations()` (the sidebar window shows them, see below). CPU pressure is a proxy (slow speed plus low fps), not a CPU reading.
- **`intel_hd_optimized` profile** (auto for Intel HD 4000/520/620; other Intel graphics keep `intel_hd`): preset capped at `light` (an explicit `--preset` still wins), half-second rate-control buffer, webcam capped at 10 fps, chroma key and blur skipped, AI noise suppression off unless you pass `--noise ai`.
- **`optimus_mx250` profile** (auto when an Intel iGPU and a GeForce MX250 are both present): Quick Sync first so the idle iGPU encodes while the MX250 runs the game, NVENC second; same recording and 4500 kbps defaults as `mx250_streamer`. A design choice, UNVERIFIED on real hardware.
- **`mx250_streamer` profile** (auto for a GeForce MX250 without an Intel iGPU): NVENC first, then Quick Sync; webcam overlay allowed; a local copy is recorded by default (`--no-record` or `"record": false` turns it off); video bitrate capped at 4500 kbps unless you pass `--bitrate`. For 1080p use `--res 1920x1080`; there is no 1080p preset yet and 1080p on an MX250 is UNVERIFIED.
- **Scene collections**: `lightstream scenes export [NAME] [--to PATH]` (one scene to a file, or every scene to `scenes/NAME.json`), `lightstream scenes import PATH` (a file or a folder of `.json` scenes), `lightstream scenes example --collection` (writes `scenes/gaming.json`, `just-chatting.json`, `work.json`, `retro.json`). Files are indented JSON, every scene is validated, and nothing is replaced without `--force`. `scene_collections.py` also has save and duplicate helpers for the window.
- **Overlay widgets** (`overlays.py`): add an `"overlays"` list to a scene with kinds `text`, `clock`, `fps` (average since start), `recording` (blinking REC) and `image` (PNG). Each has `corner`, `margin_x`, `margin_y` and a size (`font_size` or `size_percent`). They compile to FFmpeg `drawtext` or `overlay` filters; no browser, no HTML. A missing PNG is skipped with a warning. At most 6 overlays per scene.
- **Session reports** (opt-in): `lightstream start --analytics` (or `"analytics": true` in `config.json`, or `analytics` in the window prefs) writes `reports/session-YYYYMMDD.json` with average speed, average bitrate, reconnect count, encoder, preset, profile and recording seconds. It never contains the stream key, URL or file paths, and is never uploaded. Recording seconds equal the session length when recording (approximation).

### Sidebar window (0.7.0)

The window now has a sidebar (Dashboard, Setup wizard, Scenes, Overlays, Recording, Advanced) built from native `ttk` widgets only, with each page created the first time you open it. The Dashboard shows health cards and suggestions from the adaptive advisor; a suggestion changes a setting only after you press Apply (and takes effect at the next START), or you can Dismiss it. The Scenes page has Save Scene, Duplicate Scene, Import Scene and Export Scene (indented JSON). The Overlays page has position and scale controls and shows the resulting FFmpeg filter text as the preview; it does not draw video. The session report checkbox (Advanced) is off by default. Logic lives in `gui_pages.py` and `gui_controller.py`; layout in `gui.py` is UNVERIFIED (never run on a screen here). Dark/light theme (Ctrl+Shift+D), a compact sidebar-only mode (Ctrl+Shift+C), shortcuts (Ctrl+Enter start, Ctrl+. stop, Ctrl+Shift+E emergency, Ctrl+1..6 pages) and small fps/bitrate/CPU graphs are in `gui_theme.py` (logic VERIFIED by tests; on-screen look UNVERIFIED).

### Browser companion overlay (0.7.0)

`web/companion/` is a static page you add as a browser source or open in a window: chat, viewer count, stream timer and goal bar. With no credentials it runs in demo mode. Twitch chat uses anonymous IRC; the viewer count needs a client ID and token that you pass in the URL fragment (after `#`). They are read at runtime, never stored and never committed. YouTube is not implemented. Chat text is inserted with `textContent`. The CSP in `web/vercel.json` allows `wss://irc-ws.chat.twitch.tv` and `https://api.twitch.tv` only for `/companion/*`; the showcase keeps `connect-src 'self'`. OBS stores a browser-source URL in its scene file, so a token in the fragment is saved there: use a limited-scope token and do not share the scene file. Logic is tested with node; rendering and the Twitch connection are UNVERIFIED.

### Windows portable builder (0.7.0)

`python tools/build_windows_portable.py` creates `LightStreamPortable/` with `portable.flag`, `ffmpeg/`, `scenes/`, `recordings/` and `config/`. In portable mode scene collections go to `scenes/` and the default recording to `recordings/`. `config/` is created but NOT used yet: settings, `scenes.json` and reports are still stored in `data/`, which the app creates on first run. `LightStream.exe` is built with PyInstaller only if PyInstaller is installed; otherwise use `--layout-only`. FFmpeg is never bundled: the `ffmpeg/` folder gets a note telling you to add your own copy. The folder layout is tested; the exe build is UNVERIFIED.

### Web showcase upgrade (0.7.0)

The `web/` showcase has an animated hero title (respects reduced motion), SVG mockups labeled as illustrations rather than screenshots, a design-difference comparison with OBS (no measurements are claimed) and setup guides for Intel HD and MX250. Browser rendering is UNVERIFIED.

### Status of the 0.7.0 features

| Item | Status | Evidence |
| --- | --- | --- |
| Adaptive advisor (rules, thresholds, no mutation) | VERIFIED | `tests/test_adaptive.py` (fake clock) |
| Scene collections (export, import, duplicate, save, CLI flow) | VERIFIED | `tests/test_scene_collections.py` |
| Overlays (filter text, validation, scene integration) | VERIFIED (as strings) | `tests/test_overlays.py`; real FFmpeg acceptance of `drawtext` and PNG overlay UNVERIFIED |
| Browser companion | PARTIALLY VERIFIED | node tests cover logic; rendering, Twitch chat and viewer API UNVERIFIED; YouTube not implemented |
| `intel_hd_optimized` profile | VERIFIED (as strings) | `tests/test_hardware.py`; stability gain on real Intel HD UNVERIFIED |
| `mx250_streamer` profile | VERIFIED (as strings) | `tests/test_hardware.py`; NVENC behavior and 1080p on an MX250 UNVERIFIED |
| Windows portable builder | PARTIALLY VERIFIED | `tests/test_portable.py` covers the layout; PyInstaller exe UNVERIFIED |
| UI refresh (sidebar) | PARTIALLY VERIFIED | page logic and display-free import tested in `tests/test_gui_pages.py`; window rendering UNVERIFIED |
| Analytics reports (content, no key, opt-in) | VERIFIED | `tests/test_analytics.py` |
| Web showcase | UNVERIFIED | static page, no browser in the dev sandbox |

## Performance profiles (0.9.0)

Run `lightstream profiles` for the full list.

- Performance profiles (`--profile`): `potato`, `balanced`, `quality`, `competitive`, `low_latency`. Each picks an existing preset (the numbers stay in `presets.py`) plus knobs: x264 tune, thread cap, cores left free for the game ("Gaming First"), keyframe interval and rate-control buffer. `quality` is still capped by your hardware profile.
- Stream presets (`--stream-preset`): `youtube_gaming`, `twitch_gaming`, `facebook_live`, `kick`, `podcast`, `just_chatting`, `tutorial`, `esports`. Each sets platform, profile and audio profile, and keeps the bitrate within the platform cap. `kick` needs `--url` (no Kick address is built in).
- Audio profiles (`--audio-profile`): `gaming`, `podcast`, `music`, `commentary`, `asmr`, built from FFmpeg filters. The light chain is used with the `potato` profile and on hardware profiles that strip expensive filters. `--noise light|ai` takes priority over an audio profile.
- Precedence: explicit flag, then a profile from the command line, then the config file, then a profile named in the config file.

Status: option parsing, settings resolution, thread math and command building are VERIFIED by unit tests. All ten audio chains (five profiles, light and full) were run through ffmpeg 7.0.2 (static build) on a 1 second sine and were accepted; set `LIGHTSTREAM_TEST_FFMPEG` to repeat that. Effects on real games, Windows/macOS telemetry, `nvidia-smi` and CPU affinity on real hardware are UNVERIFIED.

`lightstream readiness [--upload-mbps N] [--platform twitch]` scores how ready this PC is (0 to 100) with a fix per factor. `lightstream bench --ffmpeg PATH` measures startup, memory, CPU cost and a synthetic encode; see `docs/BENCHMARKS.md` for the method and the numbers from the dev sandbox (not representative of low-end laptops). `lightstream support-bundle` writes a redacted JSON file (no stream key or address) to attach to a bug report.

### Emergency, weak connection and backup ingest (0.11.0)

- `start --potato-stream 2000|4000` (Potato Stream for very weak PCs: 15 fps, 360p or 480p, ultrafast, 1-2 threads; `--grayscale` and `--skip-static` are opt-in looks, not CPU savers). CPU numbers are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md); the 512 MB memory budget is UNVERIFIED.
- `start --emergency` starts with the safest settings. In the window, the orange EMERGENCY button does it while live (ffmpeg restarts briefly); press it again (it then reads RESTORE) to go back. Never automatic.
- `start --weak-connection [--upload-mbps 5]` lowers the bitrate, uses 1 second keyframes and a 2 second buffer for a poor uplink.
- `start --backup-url rtmp://backup-host/app` (no key in it) switches to that server after 3 quick connection failures, using the same stream key. A recording continues in the next numbered file. Real ingest servers are UNVERIFIED; the logic is tested with fakes and the ffmpeg argv with real ffmpeg.

### Explained insights and opt-in auto-scale (0.9.0)

- The end-of-session report now prints `insight:` lines. Each has plain words and a confidence percent, and says what the likely limit is: CPU, encoder, network, GPU, heat or unknown. The network stability score is an inference from ffmpeg readings, not a packet loss measurement.
- `start --auto-scale` (or the Advanced checkbox) steps quality down one notch at a time when the stream struggles and back up after it stays healthy. It is off by default. Each step restarts ffmpeg briefly; a recording continues as `name-2.mkv`. See [docs/ARCHITECTURE-NOTES.md](docs/ARCHITECTURE-NOTES.md).
- The window now has Performance profile, Microphone profile and Auto-scale controls in Advanced. A chosen profile replaces the Strength dropdown.
- Status: rules, ladder, hysteresis, runner restart and settings wiring are VERIFIED by unit tests with fake clocks, and the restart was run against a real subprocess. Behavior on real streams and games, the Tk widgets and the thresholds' fit to real hardware are UNVERIFIED.

Planned work and why it is not in 0.9.0 is listed in [docs/ROADMAP.md](docs/ROADMAP.md).

The v0.10 audit, blueprint, benchmark method (competitor numbers UNKNOWN) and Top 100 list are indexed in [docs/README.md](docs/README.md).

## Stream key safety

The key is read from the `STREAM_KEY` environment variable or typed at a hidden prompt (asked by lightstream itself, also from the Windows launcher). It is never stored by lightstream, and it is hidden (`****`) in everything lightstream prints. Limitation: RTMP puts the key in the FFmpeg command line, so other local processes running as your user may be able to see it in the process list. Custom URLs that carry their own tokens are not redacted beyond the key. Never share your key or commit it.

## Commands

`lightstream doctor`, `devices`, `presets`, `profiles`, `init`, `gui`, `setup [--yes] [--platform NAME] [--upload-mbps N]`, `bandwidth [--platform NAME] [--upload-mbps N | --measure-url URL] [--hardware NAME]`, `scenes list|validate|example|export|import [--scenes-file FILE]`, `start [--platform twitch|youtube|facebook|custom] [--url URL] [--preset NAME] [--fps N] [--res WxH] [--bitrate K] [--window TITLE] [--audio-device NAME] [--video-device INDEX] [--mute] [--test-local [FILE]] [--keep-trying] [--encoder NAME] [--software] [--scene NAME] [--scenes-file FILE] [--record [FILE]] [--no-record] [--analytics] [--profile NAME] [--stream-preset NAME] [--audio-profile NAME] [--noise off|light|ai] [--noise-model PATH] [--hardware auto|intel_hd|intel_hd_optimized|nvidia_mx|mx250_streamer|optimus_mx250|nvidia|generic] [--potato-stream 2000|4000] [--grayscale] [--skip-static] [--rate-mode vbr|cbr] [--persistent-ingest] [--dry-run]`

`--keep-trying` never gives up reconnecting. `--video-device` (macOS) picks the screen. On Linux the capture follows `$DISPLAY`.

`--dry-run` prints the FFmpeg command without streaming. `--test-local [FILE]` records 10 seconds (default `lightstream-test.mkv`) and needs no stream key.

## Web demo (Vercel)

`web/` is a separate static site: a 3D hero (plain WebGL, no libraries), a preset picker that estimates upload need and data use, install steps, and a local screen-recording demo. It is a guide and calculator only. Browsers cannot push RTMP, so it cannot stream to Twitch or YouTube, and it never asks for a stream key. The desktop app does not use it.

Deploy on Vercel: import the repo, set **Root Directory** to `web`, Framework Preset **Other**, leave Build Command and Output Directory empty. Preview locally with `python3 -m http.server -d web` (ES modules need http, not file://).

The Python presets are the source of truth. After changing `src/lightstream/presets.py`, run:

```sh
python3 tools/export_presets.py          # regenerate web/presets.json
python3 tools/export_presets.py --check  # fails if it is stale
```

| Web item | Status | Evidence |
|---|---|---|
| Presets JSON matches Python presets | VERIFIED | unit test and `--check` |
| Bandwidth maths, recommendation, geometry, mode selection | VERIFIED | `node --test "web/test/*.test.js"` |
| WebGL rendering, shaders, layout, CSS | UNVERIFIED | no browser or GPU in the dev sandbox |
| Screen capture and recording | UNVERIFIED | needs a real browser |
| Vercel deployment and headers (CSP) | UNVERIFIED | not deployed yet |
| Companion logic (timer, goal, URL parsing, chat parsing/sanitizing) | VERIFIED | node tests |
| Companion rendering, Twitch chat and viewer API | UNVERIFIED | no browser or network in the dev sandbox; YouTube not implemented |
| `build_windows_portable.py` folder layout | VERIFIED | unit tests and a `--layout-only` run |
| `LightStream.exe` build with PyInstaller | UNVERIFIED | needs Windows and PyInstaller |

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
| Performance profiles, stream presets, audio profile selection, thread math, optimizer rules, network stability score, auto-scale ladder and hysteresis, readiness scoring, bench report schema (0.9.0) | VERIFIED | unit tests with fake clocks and injected callables |
| Ten audio filter chains accepted by FFmpeg (0.9.0) | VERIFIED | run through ffmpeg 7.0.2 static build on a sine input in the dev sandbox; a bad chain was rejected |
| Real libx264 synthetic encode and bench numbers (0.9.0) | VERIFIED (this machine only) | `docs/BENCHMARKS.md`, Linux x86_64 sandbox; not representative of low-end laptops |
| Restart through the reconnect path (auto-scale) | PARTIALLY VERIFIED | exercised against a real subprocess, not a real capture or RTMP stream |
| Auto-scale on real games and streams, threshold fit to real hardware | UNVERIFIED | not run |
| Game FPS gain from Gaming First (thread cap, CPU affinity) | UNVERIFIED | not measured |
| Telemetry on Windows and macOS, `nvidia-smi` GPU readings, GUI telemetry row and new controls | UNVERIFIED | Linux parsing tested on sample text only; no display |
| Linux PyInstaller build (`tools/build_release.py`), tar.gz plus SHA256SUMS, runs headless and prints the no-screen message | VERIFIED | built for 0.8.0 with PyInstaller, extracted and run locally (GUI itself not shown, no display) |
| Windows `.exe` zip, macOS `.app` zip and `.dmg` | UNVERIFIED | only tested with a faked PyInstaller |
| Release workflow `release.yml` | UNVERIFIED | YAML parses; Actions is billing-locked, never run |
| First-run FFmpeg dialog on a real GUI | UNVERIFIED | no display; guidance and validator logic are unit tested |

## Known limitations

- Window capture on Windows (`--window`) uses gdigrab and often shows black for GPU-accelerated emulators (BlueStacks, LDPlayer, MuMu). Capture the whole desktop instead.
- The hardware encoder check runs short test encodes (8 second timeout each, run in parallel and cached), so worst-case startup is about 8 seconds plus the `-encoders` listing. This is derived from the timeouts, not measured on real hardware.
- RTMP only. Scenes are fixed when you press START; there is no mid-stream scene switching and no embedded browser engine (see Scenes above).
- Screen capture: gdigrab (Windows), x11grab (Linux X11, not Wayland, follows `$DISPLAY`) and avfoundation (macOS, screen picked with `--video-device`).
- Windows without `--audio-device` streams silent audio.
- The stream key appears in the FFmpeg command line, so other local processes running as your user may see it in the process list. Lightstream hides it in everything it prints. Hiding it from the process list is not feasible with FFmpeg's RTMP output, so on a shared PC use your own user account.
- 0.7.0: a recording started by a later session can overwrite the file of an earlier one with the same name (only reconnects within a session get `-2`, `-3` suffixes). Give each session its own file name.
- 0.7.0: a stalled webcam may block the stream. If it does, remove the webcam from the scene.
- 0.7.0: `drawtext` `font_file` and Windows `C\:` path escaping have not been run against real FFmpeg.
- 0.7.0: 1080p on an MX250 is UNVERIFIED. There is no 1080p preset.
- 0.7.0: the YouTube companion is not implemented (Twitch only).
- 0.7.0: the sidebar window, real FFmpeg, the PyInstaller exe, the browser pages and the Twitch connection are UNVERIFIED in the dev sandbox.
- The window needs Python's tkinter, which some Linux installs lack (`python3-tk`).

Reports of what works on your hardware are welcome.

## Portable mode (USB stick friendly)

```sh
python tools/build_portable.py        # writes lightstream-portable.zip
```

Unzip anywhere, put `ffmpeg.exe` (or `ffmpeg`) into the `ffmpeg/` folder, then run `launchers/start-gui.bat` (or `.sh`). Settings go to the `data/` folder next to the app, nothing is written to your user profile, and deleting the folder removes everything. The stream key is still never saved. A bundled ffmpeg is used before any ffmpeg on PATH. Python 3 still has to be installed on the PC (use the PyInstaller recipe below for a no-Python exe).

- VERIFIED (Linux): the zip builds, unzips, and `init` from the unzipped copy wrote `data/config.json` and nothing in the home folder; unit tests cover flag, env var, config path and ffmpeg lookup.
- UNVERIFIED: running from a Windows USB stick, and the GUI in portable mode (no display in the dev sandbox; the GUI has still never been rendered).

## Browser companion and Windows portable folder

- `web/companion/` is a static overlay page (chat, viewers, timer, goal). Open `/companion` in a browser and capture that window with a browser-source scene. Settings go in the URL fragment, for example `/companion#channel=name&goal=200`; `clientId` and `token` (optional, for viewer counts) are read from the fragment only, so they are not sent to the host and never stored. With no channel it shows demo data.
- `python tools/build_windows_portable.py` creates `LightStreamPortable/` with `LightStream.exe` (needs `pip install pyinstaller`, run on Windows), `portable.flag`, `ffmpeg/`, `scenes/`, `recordings/`, `config/` (`config/` is not read yet; settings stay in `data/`). Use `--layout-only` to skip the exe. FFmpeg is not bundled; put your own in `ffmpeg/`.

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

```sh
node --test "web/test/*.test.js"
```

CI runs the same commands on Linux and Windows (`.github/workflows/ci.yml`).
