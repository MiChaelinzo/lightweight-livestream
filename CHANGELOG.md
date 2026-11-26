# Changelog

## Unreleased (v0.17)

- Phone remote (`src/lightstream/remote.py`, opt-in): local HTTP API on 127.0.0.1 with a random bearer token, Host-header check and failed-auth lockout. It exposes emergency, restore and stop only; start is not exposed and the stream key never passes through it. Added `StreamController.timeline_lines()`.
- GUI: Advanced page checkboxes "Phone remote (this PC network only, off by default)" and "Allow my home network" (prefs `remote`, `remote_lan`; the token is never saved), a read-only link box with Copy link, and a themed "Session timeline" box on the Dashboard. `remote.RemoteSession` starts the server only while a stream runs and stops it on stream end, untick or window close. GUI only: no CLI `--remote` flag (the CLI has no emergency/restore controller). Idle budget unchanged within noise (see the task findings).
- Test: Auto-survival entering at the same moment as an Emergency press never leaves both modes active.

## 0.16.0

- Version bumped to 0.16.0 (`pyproject.toml`, `__init__.py`, README artifact names, RELEASING example).
- Docs: `docs/architecture/V016-MAP.md` (feature map, decisions, final status, suite table), README, FEATURES, ROADMAP and docs index updated. Control API, phone remote, cloud scene sync and the companion app stay Roadmap; Crowd-Assisted Encoding savings are not claimed.
- Observation, no change made: `.github/workflows/dependabot-auto-merge.yml` uses `pull_request_target` with `contents: write` and merges dependabot PRs without CI gating, there is no `dependabot.yml` and no runtime dependencies. Recommendation in `docs/ARCHITECTURE-NOTES.md`; needs the owner's decision.

- New (opt in, off by default): `--guardian` (config `guardian`, GUI checkbox) turns on auto-scale and adds telemetry pressure (CPU, RAM, CPU temperature, GPU) and a bandwidth trend prediction as extra STRESSED reasons for the existing AutoScaler (`guardian.py`, `predictor.py`). Every step still restarts the encoder; `--persistent-ingest` keeps the connection alive meanwhile (about 10 percent of frames were lost near a restart on loopback). The ladder gained a 900p step (1920x1080 to 1600x900) and a 45 fps step (60, 45, 30, 24). Predictor results are on SYNTHETIC traces only (see `docs/BENCHMARKS.md`); real streams UNVERIFIED.
- New (opt in, off by default): `--auto-survival` (config `auto_survival`, GUI checkbox). CPU at or above 95 percent or RAM at or above 90 percent for 10 seconds switches to constant-size emergency settings (same picture size, audio untouched, lower fps and bitrate, x264 ultrafast, no overlays, chromakey or blur). It leaves after CPU and RAM stay under 80 percent for 60 seconds, with a 60 second cooldown and at most 4 entries per hour. State machines VERIFIED with a fake clock; real machines UNVERIFIED.
- Changed: with persistent ingest the GUI Emergency button is no longer declined. It uses the constant-size variant because persistent ingest keeps the picture size fixed (`emergency_settings(constant_size=True)`).
- New: `timeline.py`, a bounded in-memory event log (guardian steps, survival, reconnects, Emergency and Restore). The end-of-session output lists load spikes with the events that "happened around" them (a time correlation, never a cause). Nothing is persisted, so there is no `lightstream timeline` command yet.
- Changed: plain `--auto-scale` now has a longer ladder (a 45 fps rung and a 900p rung). Each rung is one encoder restart. Profile-only presets are excluded from the ladder sources.
- New: one-click profiles `potato_pc` (480p30, 1000k, 2 threads), `office_laptop` (900p30, 3500k) and `budget_gaming` (1080p60, 6000k, needs a hardware encoder) with presets `office_laptop` and `budget_gaming` (exported to `web/presets.json`, marked `profile_only` in the JSON so the web recommender skips them, as `bandwidth.recommend` does), and a pure `recommend_profile()` whose answer `optimize` prints. 40 fps was rejected (judders on 60 Hz displays). Reasoning in `docs/PROFILES.md`; real PCs UNVERIFIED. `wizard.LOW_RAM_MB` and `POTATO_RAM_MB` now live in `perf_profiles.py`.
- Fix: plugin names are matched with `fullmatch`, so a name with a trailing newline is rejected (the `$` anchor accepted it).

- Dev: `tools/idle_budget.py` measures GUI startup, idle RSS and idle CPU on a DISPLAY; `tests/test_idle_budget.py` enforces startup under 2 s, RSS under 150 MB and idle CPU under 5 percent (real-window test skipped without DISPLAY).
- Dev: `tools/spikes.py --spike f` (runtime bitrate change) and `--spike g` (overlay cost). Findings and numbers in `docs/BENCHMARKS.md` ("v0.16 evidence"): `sendcmd` reaches filters but not encoders in this ffmpeg build, `zmq` and `drawtext` are absent here, and a pre-rendered PNG overlay showed no reliable CPU win.

## 0.15.0

- New: `lightstream audio-check FILE` reports clipping and loudness (LUFS) of an audio or video file using ffmpeg `volumedetect` and `ebur128`. Pure parser in `audio_check.py`. VERIFIED by unit tests and a real-ffmpeg test (clipped sine detected, -12 dB sine not).
- New: audio profiles `teaching` and `meeting` (dynaudnorm auto-gain; meeting adds stronger denoise) and `audio_profile_chain(..., autogain=True)`. Echo removal is not available in FFmpeg and is documented as such. No existing chain changed, so the golden argv files were not regenerated.
- New: optimizer rules `reduce_input_gain`, `high_latency` and upload-based `lower_bitrate` (only when their input is passed in); `Insight.expected_gain` is filled only from local history with at least 3 sessions per side and is always shown with its session counts n; `AIStreamingAssistant` facade over `build_insights`; optional `audio` factor in the health score.
- New: `lightstream highlights FILE [--top N --length S --min-gap S --out DIR --no-clips --vertical --blur-background]` (HEURISTIC) ranks one-second windows by scene change, motion and audio loudness bursts, writes a JSON report and cuts clips. Default clips use `-c copy` and start on a keyframe; `--vertical` re-encodes to 1080x1920 (9:16 centre crop, optional blurred background). It does not detect game events and uses no machine learning. Output names are sanitised and never overwrite an existing file (a `-2` suffix is added). Pure scoring and peak picking in `highlights.py`. VERIFIED by unit tests and a real-ffmpeg test (injected sine bursts found within 1.5 s, vertical clips are 1080x1920). Analysis cost is in `docs/BENCHMARKS.md`.
- New: `lightstream dashboard [--recordings DIR]` prints sessions from local history, recordings and highlight clips with sizes, and free disk space. Text only; no Creator page in the window yet (see the roadmap).
- Dev: `tools/spikes.py --spike e` measures the CPU cost of every audio chain (numbers in `docs/BENCHMARKS.md`).
- New: six more GUI themes next to light and dark: Midnight, Cyberpunk, Aurora, Synthwave, Minimal Dark and OLED True Black. Every palette passes the WCAG AA text (4.5:1) and non-text (3:1) tests (VERIFIED, unit tests). A Theme picker (combobox) in the sidebar replaces the Dark / light button; Ctrl+Shift+D now cycles through all themes. `ui.json` accepts the new theme names. Rendered at 1366x768 under Xvfb and inspected by eye for dark, midnight, cyberpunk, aurora, synthwave, minimal_dark and oled: PARTIALLY VERIFIED (Linux fonts).
- New: "Reduce motion" setting (saved in `ui.json` as `reduce_motion`). Motion is also off while a Potato Stream choice or Emergency mode is active (`gui_theme.animation_enabled`). The only animation is easing of the Speed, FPS and Bitrate health card values (`gui_theme.ease_step`); the tick stops when the values settle.
- Docs: native Tk cannot blur or make widgets translucent. The "glass" look here is layered, tinted cards. Real backdrop blur exists only on the web page.
- New: plugin runtime v1 (`src/lightstream/plugins.py`) and `lightstream plugins list|check|run-demo`, implementing `docs/architecture/PLUGIN-PROTOCOL.md`: manifest validation, subprocess without shell and with a minimal environment, JSON lines with `v:1`, 5 s handshake, 16 KiB lines, 20 msg/s rate limit, permissions, disable after 10 violations, one restart, shutdown sequence, 4 KiB redacted stderr tail. Off by default (`plugins` list in `config.json`). VERIFIED by tests with real subprocess plugins on Linux, including that a seeded `LIGHTSTREAM_KEY` is absent from the plugin environment. Not connected to `start` (Roadmap); subprocess isolation is not an OS sandbox. Example: `examples/plugins/hello`.
- New: `tools/benchlab.py` samples CPU, RSS and startup of a process by PID or command from `/proc` and writes JSON plus a markdown table. OBS Studio and Streamlabs Desktop columns are UNKNOWN unless you measure them; no competitor numbers are included. Linux only. Method in `docs/architecture/DELIVERY.md`, harness check in `docs/BENCHMARKS.md`.
- Fix: plugin names from `config.json` (and `plugins check NAME`) must match `[a-z0-9-]{1,32}`, so `../x` can no longer start a plugin outside the plugins folder; a non-list `plugins` setting is rejected with a clear message; the secret check on plugin events now also compares raw values, so keys with JSON-escaped characters are caught; the copilot gain sentence now says sessions at one preset averaged N higher than sessions at another and that it is not a controlled comparison.
- Version bumped to 0.15.0 (`pyproject.toml`, `__init__.py`, README artifact names, RELEASING example).
- Docs: decision recorded not to restructure the source tree into `/core`, `/plugins` and similar folders (`docs/architecture/DELIVERY.md`).

## 0.14.0

- New: the health score uses a real dropped-frame percent (dropped / frames from ffmpeg's running totals) when a frame total is known, otherwise that signal is left out. `HealthTracker.summary()` gains `frames`; `parse_progress` reads `frame=`. Counters restart if ffmpeg restarts. Tests VERIFIED with fakes; real streams UNVERIFIED.
- New: Recording page checkbox "Keep connection alive when quality changes (persistent ingest)", off by default and remembered as `persistent_ingest`. It refuses to start with a backup server address (same rule as the CLI) and Emergency mode is declined while it is on, because that changes the picture size. Controller logic VERIFIED with fakes; real platforms and the Tk checkbox rendering UNVERIFIED.
- Dev: `tools/ui_snapshots.py gui --state offline|live|reconnecting|error` renders the banner through a fake controller (no ffmpeg). All four states were rendered at 1280x720 in light and dark and inspected: PARTIALLY VERIFIED (Linux fonts, not Windows).
- Docs: README cut from 480 to about 215 lines (hero, 3-step quick start, downloads, verification table); every moved section is in the new `docs/FEATURES.md` with its text and VERIFIED labels unchanged.
- Style: web hero has a one-line pitch, Download and Try presets buttons and an honest verification badge. Checked at 1280 and 390 px in headless Chromium. CSP unchanged, no new files or dependencies; the service worker cache name was bumped. Text assets 55,265 B to 55,450 B (20,655 to 20,728 gzip), measured in `docs/BENCHMARKS.md`. No demo GIF added (decision recorded there).
- Version bumped to 0.14.0 (`pyproject.toml`, `__init__.py`, README artifact names, RELEASING example).
- Internal: `free_udp_port` moved from `cli.py` to `runner.py` so the GUI and CLI share it.

## 0.13.0

- Fix: `--test-local` no longer adds its constant placeholder key ("test") to the crash report scrub list, so ordinary text containing "test" is no longer masked. The real key is still scrubbed in normal mode.
- Fix: with `--persistent-ingest`, a "reconnecting" report from the publisher thread that arrives after shutdown began (Ctrl-C also reaches the publisher's ffmpeg) is dropped, so it no longer adds a spurious reconnect to the session report.
- New: uncaught errors in GUI callbacks write a local, redacted `crashes/crash-*.json` (same module and rules as the CLI, current stream key and addresses hidden) and show a short message in the status line instead of a console traceback. Logic is in `gui_controller.report_gui_crash` (VERIFIED by unit tests); `on_callback_error` is covered by a display-gated test (skipped without `DISPLAY`, run under Xvfb), while the `report_callback_exception` wiring in `main()` is UNVERIFIED.
- Fix: the page-area mouse wheel ignores events from other windows and from spin boxes.
- Test: `tools/ui_snapshots.py web` makes lazy images eager and waits for them before the full-page capture, and reports images that fail to load.
- Style: desktop window polish. The page area scrolls and the first window size fits the screen (1280x720 and 1366x768 show every page and both sidebar buttons). Clear active sidebar item, cards with readable captions and values, accent buttons, START/STOP/EMERGENCY colors from palette tokens with readable disabled states, graph placeholder ("Waiting for data"), installed-font fallback (no Segoe UI needed), name shown as LightStream. No behavior or saved setting changed. Verified by unit tests (helpers, WCAG AA pairs); layout is PARTIALLY VERIFIED (screenshots read by eye on Linux); Windows and macOS look is UNVERIFIED.
- New: `tools/ui_snapshots.py` (dev only) renders the GUI under Xvfb and the web page in headless Chromium; the stack is described in `docs/DEV-RENDERING.md`.
- Style: web showcase polish. The hero glass panel no longer covers the 3D shape, the feature grid is 4, 2 or 1 columns by width, and the page uses real GUI screenshots (`web/img/*.webp`, 84,984 bytes in total) instead of illustrative mockups. Text assets: 55,632 B (20,588 gzip) to 55,265 B (20,655 gzip). The service worker cache name was bumped.
- Docs: README shows real screenshots and the verification table marks GUI rendering on Linux/Xvfb PARTIALLY VERIFIED (by eye) and web rendering in headless Chromium VERIFIED; Windows and macOS looks stay UNVERIFIED. Measured before and after in `docs/BENCHMARKS.md`.
- Version bumped to 0.13.0 (`pyproject.toml`, `__init__.py`, README artifact names, RELEASING example).

## 0.12.0 (unreleased)

- Fix: recording while streaming now works with ffmpeg 7.0.2. The tee output maps video and audio, sets `-flags +global_header`, and uses `onfail=abort` on the live slot so ffmpeg exits when the ingest dies (the reconnect loop fires) while the file slot uses `onfail=ignore`. Behavior change: the argv for `--record` differs from 0.11. VERIFIED with a real loopback RTMP listener killed mid-stream (the recording is readable, the runner continues in `name-2.mkv`); real platform disconnects are UNVERIFIED.
- Fix: `bench` tiers computed from partial data are marked `partial` (an upper bound) and the CLI says so; the docs no longer say "never guessed".
- New: recording by extension: `.mkv` (default, Matroska) or `.mp4` (fragmented MP4, readable after a crash). `.webm` is refused with a reason (it needs a second VP9 encode).
- New: `--rate-mode vbr|cbr` (config key `rate_mode`). CBR is libx264 only and pads quiet pictures up to the bitrate.
- Fix: settings that cannot apply are now reported (`Note: ...`): `--rate-mode cbr` with a non-libx264 encoder, and `--grayscale` or `--skip-static` with the VAAPI encoder or a scene. `--skip-static` (variable frame rate into FLV/RTMP) is UNVERIFIED against real ingests.
- New: Potato Stream, `--potato-stream 2000|4000`, also the `potato_2000` / `potato_4000` presets and profiles (re-exported to `web/presets.json`): 15 fps, 360p or 480p, ultrafast, one or two threads. Optional `--grayscale` and `--skip-static` (mpdecimate, variable frame rate); grayscale is NOT a CPU saver. Memory use on a 512 MB machine is UNVERIFIED.
- New: ladder tiers 240p (`tier-240p`, opt-in floor) and 1080p, `build_ladder(constant_size=True)`.
- New: opt-in `--persistent-ingest`: a long-lived `-c copy` publisher keeps the RTMP connection while the encoder restarts (auto-scale, Emergency). Output size stays fixed; incompatible with `--backup-url`. VERIFIED on loopback only. The publisher gives up after 5 quick failures in a row (rejected key, unreachable ingest) and ends the run unless `--keep-trying`; its messages are marked `[publisher]`.
- New: `srt://host:port` custom URLs (key sent as `streamid`), validated, for custom servers and relays. UNVERIFIED against any real server.
- New: end-of-session network lines (`network.py`): backpressure for RTMP, packet loss only named for SRT/UDP (not read yet), link kind and hotspot hint via `/proc`, `netsh` or `networksetup` (Windows and macOS probes UNVERIFIED, shown as `n/a` when missing).
- New: `lightstream support-bundle [--out FILE]` writes a redacted JSON file for bug reports (version, platform, encoder list, config with keys and addresses hidden, recent history rows). Opt-in, never sent anywhere. A seeded secret is asserted absent in tests (VERIFIED); there is no log file yet, so none is included.
- Test: golden ffmpeg argv files in `tests/golden/` for every performance and hardware profile (fixed config, placeholder key). Regenerate after an intended change with `LIGHTSTREAM_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_argv`.
- Test: `tools/spikes.py` runs loopback ffmpeg experiments (split publisher, tee recording, potato filters, SRT) and prints JSON; results and decisions in `docs/BENCHMARKS.md` and `docs/ARCHITECTURE-NOTES.md`. Found: with ffmpeg 7.0.2, recording while streaming (`record_to`) fails to start (tee output without `-map`), the Matroska slot needs `-flags +global_header`, and a tee slot without `onfail` keeps ffmpeg running after the RTMP server drops, so the reconnect loop never fires. Fixed below.
- New: benchmark tiers Low-End, Balanced, Performance, Creator, Power User in `bench.py`, computed from measured CPU threads, RAM and encode speed with documented inclusive thresholds (`docs/BENCHMARKS.md`). Tests cover each boundary (VERIFIED). One real run recorded; other hardware UNVERIFIED.
- New: `optimizer.performance_health()` gives a 0 to 100 score and a band (Excellent, Good, Fair, Poor, Critical) from CPU, GPU, RAM, network stability, encode speed and dropped frames with documented weights; unknown signals are left out. (0.14 update: the dropped-frames signal now uses dropped divided by the frame total when ffmpeg reports one.) Band tests VERIFIED; the weights are heuristics. Shown in the GUI and at the end of CLI sessions.
- New: congestion findings from `network.py` become network Insights in the end-of-session optimizer output (fixed 50 percent confidence, an inference; never applied).
- New: `lightstream optimize` and a GUI "Optimize" button. They detect hardware, run readiness and a short bench (skip with `--no-bench`), propose a config diff (with the potato fallback on Low-End or weak PCs) and write only after you confirm (`y`, `--yes`, or the dialog). No answer means no change. Tested; the GUI dialog itself is UNVERIFIED (no display).
- New: opt-in `lightstream key save|status|forget` and `secure_store.py`: Windows DPAPI, macOS keychain (`security`), Linux `secret-tool`. If no backend exists the save is refused; there is no plaintext fallback and the key never goes into `config.json`. `start` uses a saved key when `STREAM_KEY` is not set. Control flow VERIFIED with fakes on Linux; the DPAPI, macOS and secret-tool backends are UNVERIFIED on real systems.
- New: SRT URL options `passphrase` (10 to 79 characters) and `pbkeylen` (16, 24, 32) are validated and passed through; `passphrase=` values are hidden in logs. `rtmps://` is accepted for custom and backup URLs. Plain `rtmp://` is NOT encrypted. Whether a server accepts the options is UNVERIFIED.
- New: dashboard. Eight panels (Home, Streams, Devices, Performance, Network, Recording, Analytics, Settings) are mapped onto existing pages (`gui_pages.PANELS`). Seven sparklines (fps, bitrate, speed, drops, RAM, CPU, GPU) from fixed-size buffers, a live health line, congestion findings in the GUI suggestions, and "Compare last two saved sessions". Logic VERIFIED; rendering UNVERIFIED (no display).
- New: GUI Recording page controls: file type (MKV or MP4), bitrate mode, Potato Stream 2000 or 4000 kbps with grayscale and skip-static. Persistent ingest stays command line only.
- New: web cards use `backdrop-filter` glass with a solid fallback and `prefers-reduced-transparency`; the native window gets layered card tokens (not glass). Service worker fingerprint updated.
- New: opt-in history rows gain `health_score` and `avg_bitrate_kbps`; an opted-in session saves `last-performance.json`, which `support-bundle` includes. CLI prints a health line at the end of a session.
- New: unexpected CLI errors write a local `crashes/crash-*.json` (addresses and key hidden, exit code 70, never uploaded).
- Docs: [MULTI-DEVICE.md](docs/architecture/MULTI-DEVICE.md) (panel map, viewer and relay design, OBS-style layers, Moonlight/Parsec class feasibility) (design only, no code).
- Build: `.gitattributes` forces LF line endings and marks images and fonts binary.
- Version bumped to 0.12.0 (`pyproject.toml`, `__init__.py`, README artifact names, RELEASING example). Docs: v0.12 scorecards in `docs/ROADMAP.md`, diagrams and refactoring recommendations in `docs/ARCHITECTURE-NOTES.md`, v0.12 vs v0.11 bench in `docs/BENCHMARKS.md`.

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
