# Changelog

## 0.12.0 (unreleased)

- New: `lightstream support-bundle [--out FILE]` writes a redacted JSON file for bug reports (version, platform, encoder list, config with keys and addresses hidden, recent history rows). Opt-in, never sent anywhere. A seeded secret is asserted absent in tests (VERIFIED); there is no log file yet, so none is included.
- Test: golden ffmpeg argv files in `tests/golden/` for every performance and hardware profile (fixed config, placeholder key). Regenerate after an intended change with `LIGHTSTREAM_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_argv`.
- Test: `tools/spikes.py` runs loopback ffmpeg experiments (split publisher, tee recording, potato filters, SRT) and prints JSON; results and decisions in `docs/BENCHMARKS.md` and `docs/ARCHITECTURE-NOTES.md`. Found: with ffmpeg 7.0.2, recording while streaming (`record_to`) fails to start (tee output without `-map`), the Matroska slot needs `-flags +global_header`, and a tee slot without `onfail` keeps ffmpeg running after the RTMP server drops, so the reconnect loop never fires. Not fixed yet (planned in this release).
- Build: `.gitattributes` forces LF line endings and marks images and fonts binary.

## 0.11.0 (unreleased)

- New: `optimus_mx250` hardware profile, chosen automatically when an Intel graphics adapter and a GeForce MX250 are both detected (for example i7-1065G7 Iris Plus G7 + MX250). Quick Sync encodes first, NVENC second; recording on by default and the 4500 kbps cap as in `mx250_streamer`. Behavior change: such laptops used to get `mx250_streamer`. A deliberate design choice, UNVERIFIED on real hardware. Single-GPU machines are unchanged.
- Fix: Windows GPU detection tries PowerShell `Get-CimInstance Win32_VideoController` first and `wmic` second (wmic is removed on Windows 11 24H2). Tested with fake output only; UNVERIFIED on Windows.
- Fix: a restart request that arrived during a reconnect backoff no longer causes a second, needless relaunch.
- Fix: key redaction also hides the `quote_plus` form and accepts several secrets.
- Fix: the upload speed test accepts only `https://` URLs.
- New: a custom URL that already contains a stream key (`rtmp://host/app/KEY`) triggers a warning, is hidden in the dry-run command and in output, and is never saved.
- New: emergency mode. `start --emergency` and a GUI Emergency button (with Restore) switch to the safest settings: potato size and bitrate, two threads, no overlays or webcam, no AI audio, small buffer. A live click restarts ffmpeg briefly and pauses auto-scale. Never automatic. Argv accepted by real ffmpeg; effect on real streams UNVERIFIED.
- New: weak connection mode, `start --weak-connection [--upload-mbps N]`: lower bitrate, 1 second keyframes, 2 second buffer. UNVERIFIED on real bad links.
- New: backup ingest failover, `--backup-url rtmp://host/app` (config `backup_url`, GUI Advanced). After 3 quick connection failures the stream switches to the backup with the same key (status `failover`); a switch does not reset `max_failures`, so the runner still gives up; a recording continues in the next numbered file. The key is never saved or logged. Tested with fake processes; real ingest servers UNVERIFIED.
- Change: the GUI always supplies the relaunch argv builder to the runner (needed for Emergency and failover).
- New: window look and usability. Dark and light themes, compact (sidebar-only) mode, keyboard shortcuts shown in labels (Ctrl+Enter start, Ctrl+. stop, Ctrl+Shift+E emergency, Ctrl+Shift+D theme, Ctrl+Shift+C compact, Ctrl+1..6 pages), a visible focus color, and small graphs for fps, bitrate and CPU (last minute, redrawn once per second, fixed memory). The choice is saved in `ui.json` (no secrets). Color contrast of all text pairs is tested to WCAG AA (4.5:1). Logic VERIFIED by unit tests; on-screen rendering UNVERIFIED.
- New: web site accessibility and offline use. A nav landmark, 44 px touch targets, a sideways-scrolling comparison table, a light color scheme (`prefers-color-scheme`), a visually hidden h1 on the companion page, and an optional offline service worker (`web/sw.js`, cache-first assets, network-first `presets.json` and pages, same-origin GET only, registered defensively). The CSP stays strict (no inline script or style, no `unsafe-inline`). Node tests parse the HTML and CSS (landmarks, labels, ids, CSP, WCAG AA contrast, 44 px targets) and test the pure cache rules; real browser behavior is UNVERIFIED (headless Chromium does not run in the dev sandbox). Add `tools/page_weight.py`; page weight went from 48811 to 54256 bytes (18085 to 20190 gzip).
- Docs: plugin protocol v1 spec (`docs/architecture/PLUGIN-PROTOCOL.md`, spec only, no code), v0.11 before and after bench tables with method in `docs/BENCHMARKS.md` (no measurable change on the one test machine; competitor numbers remain UNKNOWN), companion token fragment risks in `docs/audit/EVIDENCE.md`, Top 100 and roadmap statuses recomputed.
- Version bumped to 0.11.0 (`pyproject.toml`, `__init__.py`, README artifact names, RELEASING example).
- Docs: the key in the ffmpeg command line is documented as an OS-level exposure, with alternatives evaluated in `docs/ARCHITECTURE-NOTES.md`.

## 0.10.0 (unreleased draft)

- New: Facebook Live platform (`--platform facebook`, GUI "Facebook Live", stream preset `facebook_live`). Ingest is `rtmps://live-api-s.facebook.com:443/rtmp/KEY`. The video cap of 4000 kbps is a conservative design choice, not read from Facebook's documentation here. PARTIALLY VERIFIED: the unit tests cover URL building, the CLI choice, key redaction and the preset, and the bundled FFmpeg 7.0.2 (GnuTLS) parsed an rtmps output and failed with "Connection refused" on a closed local port. No Facebook account was available, so a real go-live is UNVERIFIED.
- Fix: config, preferences, history and report files are written with mode 0600 on POSIX (no-op on Windows) through a temp file and `os.replace`, so a process crash cannot leave a truncated JSON file (no fsync, so not power-loss safe). Scope is limited to those files; scene collections, portable config and bench output still use plain writes because they hold no stream keys. Report creation uses O_EXCL and removes the partial file if the write fails.
- Fix: key redaction in FFmpeg output also hides the percent-encoded form of the key.
- Docs: audit with scored rubric (`docs/audit/AUDIT.md`), measured evidence (`docs/audit/EVIDENCE.md`), blueprint and delivery plan (`docs/architecture/`), Top 100 improvements with hackathon mode (`docs/audit/TOP-100.md`) and an index (`docs/README.md`). Competitor numbers are UNKNOWN; only a method is given. Roadmap rows are design, not code.
- Known limitation: the key is part of the FFmpeg command line, so other local users can read it from the process list. FFmpeg has no other way to receive it.

## 0.9.0

Performance core: telemetry, profiles, audio profiles, optimizer, opt-in auto-scale, bench harness and readiness score. Logic is VERIFIED by unit tests with fake clocks; behavior on real games, real streams, hardware encoders, Windows, macOS and the Tk window is UNVERIFIED. See `docs/ROADMAP.md` for what is not done.
- Version bumped to 0.9.0.
- Behavior change: starting from the window with a performance profile chosen replaces the Strength dropdown, and applying a preset suggestion clears the profile.
- Behavior change: with `--analytics`, `reports/` also holds `history.json` (newest 30 sessions).
- Fix: after an auto-scale step the health tracker and advisor are retargeted to the new bitrate and fps, so later readings are not scored as a network shortfall.
- Fix: a step down caused by Gaming First CPU pressure is not undone for 10 minutes (`GAMING_STEP_UP_HOLDOFF_SECONDS`), which stops a down, up, down cycle. The 600 s value is a design choice, UNVERIFIED on real games.
- Fix: telemetry sampling runs outside the GUI controller lock, so a slow `nvidia-smi` cannot freeze the window.
- Known limitations: auto-scale restarts ffmpeg on each step (viewers see a short interruption); the network stability score is an inference, not packet loss; the bench numbers come from one Linux sandbox and are not representative of low-end laptops; the TCP latency helper is only wired into `readiness` when `--platform` or `--url` is given.

- New: `lightstream profiles` lists performance profiles (`potato`, `balanced`, `quality`, `competitive`, `low_latency`), stream presets (`youtube_gaming`, `twitch_gaming`, `kick`, `podcast`, `just_chatting`, `tutorial`, `esports`) and audio profiles (`gaming`, `podcast`, `music`, `commentary`, `asmr`, each with a light and a full filter chain).
- New: `start --profile`, `--stream-preset`, `--audio-profile` and the matching config keys `profile`, `stream_preset`, `audio_profile`. Explicit flags beat a profile; a profile from the command line beats the config file.
- New: Gaming First. Profiles with it reserve cores for the game: ffmpeg gets `-threads` and `-filter_threads` of `cpu_count - reserved_cores`, and on Linux is confined to the other cores with `sched_setaffinity`. No game FPS gain is claimed (UNVERIFIED).
- New: `telemetry.py` samples CPU, RAM, CPU/GPU temperature, GPU load and ffmpeg memory (unknown values are `n/a`) and the dashboard shows them every 2 seconds while visible. Linux parsing is tested on fake `/proc` text; Windows, macOS, `nvidia-smi` and the Tk row are UNVERIFIED on real machines.
- New: `optimizer.py` explains what limits a stream as `Insight` rows (area, action, value, confidence, explanation, plain words). Printed as `insight:` lines at the end of a CLI session and available from `StreamController.insights()`.
- New: network stability score (0 to 100) from ffmpeg bitrate, speed jitter and reconnects. It is an inference, not packet loss. `bandwidth.measure_connect_latency` times a TCP connect to the ingest host.
- New: opt-in `--auto-scale` (config `auto_scale`, GUI checkbox). Steps a quality ladder down and up with hysteresis, one step at a time, by restarting ffmpeg through the runner's reconnect path (`run_with_reconnect(restart=...)`). Off by default. See `docs/ARCHITECTURE-NOTES.md` for the alternatives evaluated.
- New: with `--analytics`, `reports/history.json` keeps the newest 30 sessions (no key, URL or paths) and lets the optimizer raise confidence.
- Fix: starting from the window now passes the performance profile, microphone profile and CPU affinity (Gaming First) to ffmpeg. The window gains Performance profile, Microphone profile and Auto-scale controls.
- New: `lightstream bench` writes a JSON report of startup time, memory, per-tick CPU cost, command build time and a synthetic encode per profile (each metric labelled measured or unavailable). Results from the dev sandbox are in `docs/BENCHMARKS.md`, including import time and memory against v0.8.0.
- New: `lightstream readiness` gives a 0 to 100 stream readiness score with points and a plain fix per factor (optional `--upload-mbps`, `--platform`/`--url` connection test). It is also printed by `lightstream setup` and the window's one-click setup.

## 0.8.0

Release builds for people who do not want to install Python or Git. Windows, macOS and workflow parts are UNVERIFIED; see the README status table.
- Fix: on macOS `find_ffmpeg` also checks `/opt/homebrew/bin` and `/usr/local/bin` (Finder-launched apps have a minimal PATH). The release workflow now checks the tag against `__version__`, fails on missing artifacts when writing checksums, and can re-publish an existing release. The ffmpeg dialog shows an error instead of raising when the config cannot be saved.
- New: `tools/build_release.py` builds `LightStream-<ver>-windows-portable.zip`, `-macos.zip` (and `.dmg`), `-linux-x86_64.tar.gz` and `SHA256SUMS.txt` into `dist/release/`. Linux build VERIFIED locally for 0.8.0 (PyInstaller build, tar.gz extracted, binary ran headless); Windows and macOS packaging UNVERIFIED.
- New: first-run FFmpeg helper (download guidance, "Choose ffmpeg file..." with validation, path saved in config). FFmpeg is not bundled. Dialog rendering UNVERIFIED.
- New: `.github/workflows/release.yml` builds on three OSes on `v*.*.*` tags and publishes a GitHub release. UNVERIFIED (Actions billing lock).
- New: `docs/RELEASING.md` (release steps, FFmpeg decision, SmartScreen and Gatekeeper workarounds, formats not shipped) and a README Download section.
- Version bumped to 0.8.0.

## 0.7.0

Ultra low-end studio: adaptive advisor, new hardware profiles, scene collections, overlays, analytics, sidebar window, browser companion, Windows portable builder and web showcase. Real FFmpeg, hardware, browser, Twitch and PyInstaller behavior is UNVERIFIED; see the README status table.
- Version bumped to 0.7.0.
- Known limitations: a later session can overwrite an earlier recording with the same name; a stalled webcam may block the stream; `drawtext` `font_file` and Windows `C\:` escaping are unverified; 1080p on MX250 is unverified; YouTube companion is not implemented.

- New: `adaptive.py` advisor (preset downgrade, bitrate reduction and bandwidth suggestions; never applies anything). Printed at the end of a CLI session and exposed by `StreamController.recommendations()`.
- New: hardware profiles `intel_hd_optimized` (HD 4000/520/620) and `mx250_streamer` (MX250). Behavior change: auto detection now picks these instead of `intel_hd` and `nvidia_mx` for those GPUs; the MX250 profile records a local copy by default (`--no-record` to disable) and caps bitrate at 4500 kbps unless `--bitrate` is given.
- New: scene collections (`scenes export`, `scenes import`, `scenes example --collection`) and `scene_collections.py` save/duplicate helpers.
- New: scene `overlays` (text, clock, FPS, REC indicator, PNG) compiled to FFmpeg filters in `overlays.py`.
- New: opt-in session reports in `reports/session-YYYYMMDD.json` (`--analytics`), no stream key.
- New: sidebar window (ttk only, lazy pages) with health cards, Apply/Dismiss suggestions, scene Save/Duplicate/Import/Export, overlay position/scale controls with filter text preview, hardware profile dropdown and an opt-in session report checkbox. Logic in `gui_pages.py`. Window rendering is UNVERIFIED (no display).
- New: `web/companion/` browser overlay (chat, viewer count, stream timer, goal bar). Demo mode without credentials; Twitch chat and viewer count optional, client ID and token read from the URL fragment only and never stored. CSP `connect-src` allows `wss://irc-ws.chat.twitch.tv` and `https://api.twitch.tv`. Twitch/YouTube connections are UNVERIFIED (no network); YouTube is not implemented.
- New: `tools/build_windows_portable.py` builds `LightStreamPortable/` (exe via PyInstaller when installed, `--layout-only` otherwise). No binaries or FFmpeg are bundled. The exe build is UNVERIFIED. Layout: `LightStream.exe`, `portable.flag`, `ffmpeg/`, `scenes/`, `recordings/`, `config/`. In portable mode scene collections use `scenes/` and the default recording uses `recordings/`; `config/` is created but not read yet (settings stay in `data/`).
- New: web showcase upgrade: animated hero title, illustrative SVG mockups (labeled as not real captures), design-difference comparison with OBS (no measurements), Intel HD and MX250 guides.
- Refactor: overlay position helpers moved into `filtergraph.py`; `config.effective_preset_name`.

## 0.6.0

Low-end studio release. Real FFmpeg, GPU and webcam behavior of everything below is UNVERIFIED (no FFmpeg, GPU, display or network in the dev sandbox); command text is checked by unit tests only.

- New: hardware profiles (`--hardware auto|intel_hd|nvidia_mx|nvidia|generic`). The GPU is detected when no profile is configured (`wmic` on Windows, `lspci` on Linux). Profiles use fewer threads, a smaller input probe, a cheap scaler and no lookahead, and Intel HD caps the preset at `light`. `doctor` prints the detected GPU and profile. Note: auto detection means the default `start` command now differs on every machine (even `generic` adds `-filter_threads 1`, `-sws_flags fast_bilinear`, `-threads 2`). An explicit `--preset` overrides the Intel HD cap; Intel on Linux tries Quick Sync then VAAPI.
- New: scenes file (`scenes.json` next to `config.json`): screen, window or "browser" capture, one webcam overlay (corner, size, chroma key or plain blur), image and text overlays. Commands: `lightstream scenes list|validate|example` (the example writer never overwrites a file) and `start --scene NAME --scenes-file FILE`. A scene is chosen at start; switching scenes while live is not implemented (stop and start again).
- New: `start --record [FILE]` saves a local Matroska copy while streaming, using one encode through the tee muxer. The folder is checked before start; a later write error does not stop the stream. After a reconnect the copy goes to `name-2.mkv`, `name-3.mkv`, so earlier footage is not overwritten. The window saves a timestamped file under the app data folder.
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
