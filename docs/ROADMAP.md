# Roadmap

Status as of 0.13.0 (polish release on top of Platform V2). 0.13 changed no streaming behavior; it adds a polished window and web page, real screenshots (rendering VERIFIED on Linux under Xvfb and in headless Chromium only; Windows and macOS looks UNVERIFIED), GUI crash capture and three fixes, see the [CHANGELOG](../CHANGELOG.md). The scorecards below answer the 15 requested areas and 6 headline features; the detailed table that follows is older and more granular. Plans for each Roadmap row are in [architecture/BLUEPRINT.md](architecture/BLUEPRINT.md); ranking in [audit/TOP-100.md](audit/TOP-100.md). Done means implemented and covered by unit tests (see the README verification table for what was never run on real hardware). Partial means some of the area exists. Roadmap means not started; the design notes are intentions, not code.

## v0.12 scorecard: the 15 areas

Status words: Done (implemented and unit tested), Partial (some of it exists), Roadmap (not built). Verification labels as in the README. Nothing here has been run on a real game, a real platform ingest, Windows or macOS, or a display.

| # | Area | Status | Reason |
| --- | --- | --- | --- |
| 1 | Adaptive streaming engine | Partial | Opt-in ladder with hysteresis (now 240p to 1080p, `constant_size` for persistent ingest) restarts ffmpeg through the reconnect loop; logic VERIFIED with fake clocks, real streams UNVERIFIED. Congestion findings are only reported at session end and are not fed into `AutoScaler` decisions. SRT loss statistics are not read |
| 2 | Potato Mode | Partial | `potato_2000` and `potato_4000` presets and profiles, `--potato-stream`, opt-in `--skip-static`; settings come from measured spikes (fps and size cuts reduce CPU, grayscale does not). Argv VERIFIED against real ffmpeg; the 512 MB target and behavior on a low-end laptop are UNVERIFIED |
| 3 | AI optimizer and health | Partial | Rule based optimizer with confidences, bottleneck classification, a 0 to 100 `performance_health` score with documented heuristic weights, `lightstream optimize` and a GUI button that ask before writing. No learned model (no real session data exists). The score is not yet used to change settings on its own |
| 4 | Dashboard | Partial | Eight panels mapped onto existing pages, health line, congestion insights, session comparison. Logic VERIFIED, window rendering VERIFIED on Linux/Xvfb only (Windows and macOS UNVERIFIED). No sidebar rename |
| 5 | Performance panel | Partial | Seven fixed-size sparkline buffers (fps, bitrate, speed, drops, RAM, CPU, GPU). GPU readings come from `nvidia-smi` only. Drawing UNVERIFIED |
| 6 | Recording | Partial | Hybrid tee fixed for ffmpeg 7.0.2 (VERIFIED on loopback), MKV or fragmented MP4, CBR option, numbered files after a reconnect. WEBM refused (second VP9 encode). No instant replay, clips or space estimate |
| 7 | Recovery | Partial | Default: reconnect with backoff and a new numbered file. Opt-in `--persistent-ingest` keeps one RTMP connection while the encoder restarts. It is CLI only, about 10 percent of frames near a restart were lost in the spike, and viewers can still see a stall, so recovery is not invisible. Platform reaction UNVERIFIED |
| 8 | Multi-device viewing | Roadmap | Design in [MULTI-DEVICE.md](architecture/MULTI-DEVICE.md). Design only, no code. LAN preview works only through a hand-typed `srt://` URL |
| 9 | Security | Partial | Opt-in secure key store (DPAPI, keychain, `secret-tool`; refuses without a backend), SRT passphrase validation and redaction, key redaction, 0600 atomic writes, local redacted crash reports and support bundle. Only the control flow is VERIFIED (fakes). The key still appears in the ffmpeg command line. No control API exists, by decision |
| 10 | OBS-style layer | Partial | Scene collections (export and import with conflict checks) are the integration layer. There is no OBS websocket client, no plugin code (protocol spec only) and no virtual camera |
| 11 | Network intelligence | Partial | `network.py` separates backpressure from loss and reads Wi-Fi or hotspot hints. Real probes on Windows and macOS UNVERIFIED. No SRT stats, no endpoint selection, no live action on findings |
| 12 | Onboarding | Done | Setup wizard, readiness score, first-run FFmpeg helper, `optimize`. Window rendering VERIFIED on Linux/Xvfb only, Windows and macOS UNVERIFIED |
| 13 | Benchmark engine | Done | `lightstream bench` with tiers (Low-End to Power User) from CPU threads, RAM and encode speed, inclusive thresholds tested. One real run (Creator on one 8-thread VM); other hardware UNVERIFIED, competitor numbers UNKNOWN |
| 14 | Telemetry and diagnostics | Done | Opt-in history and `last-performance.json`, `support-bundle` (redacted, never sent), local crash reports with exit code 70, golden argv tests. No log file; GUI crashes are not captured |
| 15 | Future roadmap | Done (this file) | Remaining items are listed below with a reason each |

## v0.12 scorecard: the 6 headline features

| Feature | Status | Honest limits |
| --- | --- | --- |
| Network recovery | Partial | Reconnect with backoff and backup ingest failover (Done earlier, fakes only). Persistent ingest is opt-in and CLI only. Loopback VERIFIED; real platforms UNVERIFIED. Viewers can still see a stall |
| Potato Mode | Partial | See area 2. Measured CPU savings come from fps and resolution, not from grayscale |
| Hardware auto-tuning | Partial | Hardware detection, profiles and the `optimize` diff exist and are confirmed by the user. Real GPU encoders and dual-GPU choice are UNVERIFIED. Auto-scale applies changes only when opted in |
| Health score | Done (logic), shown in GUI and CLI | Weights are heuristics, not fitted to data. `session_health` never passes dropped percent (no frame total in the summary), so the dropped-frames weight is unused in real sessions; only direct callers of `performance_health` can use it |
| One-click Optimize | Partial | CLI and GUI button, write only after confirmation. The GUI dialog is UNVERIFIED, and it proposes from a short synthetic bench, not from a game |
| Offline recording plus live hybrid | Partial | One tee process writes the file and the stream. The file survives an ingest failure but is split into numbered files unless `--persistent-ingest` is used. Real platform disconnects UNVERIFIED |

## Not done in 0.12, with reasons

- Local control API and mobile remote: no client exists; a listening socket needs its own security review (decision below).
- Reading SRT statistics: needs a lossy link (netem) to test.
- Feeding congestion findings into `AutoScaler`: untested thresholds could cause restarts; reported only for now.
- Persistent ingest in the GUI: needs a display to verify the control and its stop behavior.
- Viewer, relay and remote play: no transport browsers can play without a relay this project does not ship.
- WEBM recording, instant replay: second encode or a rolling buffer costs the low-end budget.
- Sidebar rename: not started. GUI crash capture shipped in 0.13 (report logic VERIFIED, Tk hook UNVERIFIED on a display).

## Detailed table (carried from 0.9 to 0.11, updated where 0.12 changed a row)

| Area | Status | What exists or what is planned | Phase | Depends on | Why deferred |
| --- | --- | --- | --- | --- | --- |
| Core engine (profiles, threads, affinity) | Done | `perf_profiles.py`, `telemetry.py`, runner affinity. Effect on game FPS UNVERIFIED | | | |
| AI optimizer | Partial | `optimizer.py` is rule based and explains each insight with a confidence. There is no machine learning model | 2 | opt-in history | A learned model needs real session data that does not exist yet |
| Auto-scaling | Done | Opt-in ladder with hysteresis and restart. See `ARCHITECTURE-NOTES.md` for the alternatives evaluated | | | |
| Dashboard | Partial | Numeric telemetry cards every 2 seconds, seven sparklines (fps, bitrate, speed, drops, RAM, CPU, GPU), health line, session comparison, eight panels mapped onto existing pages ([MULTI-DEVICE.md](architecture/MULTI-DEVICE.md)). Window rendering VERIFIED on Linux/Xvfb only, Windows and macOS UNVERIFIED | 2 | telemetry buffers | Needs a display to verify the drawing |
| Scene system, source types | Partial | Screen, window, browser, webcam, image, text, overlays. No Game Capture, Video file or Alerts source | 2 | scene schema extension | Game Capture is Windows specific and cannot be tested here |
| Gaming first | Done | Reserved cores, thread cap, affinity, step-down under pressure. FPS impact UNVERIFIED | | | |
| Network | Partial | Stability score, connect latency helper, bandwidth advice, reconnect with backoff. No regional endpoint selection, backup ingest failover exists since 0.11.0 (logic tested with fakes, real ingest UNVERIFIED), no recovery buffering, no packet loss measurement | 2 | ingest server lists per platform | Endpoint lists change and need a network to check; buffering needs a second process (see auto-scale notes) |
| Overlays (chat boxes, donations, alerts) | Partial | Text, clock, FPS, REC, PNG overlays and the browser companion. No donation or alert feed | 3 | chat, plugin protocol | Needs platform APIs and tokens |
| Chat (Twitch, YouTube, Kick) and moderation | Roadmap | The browser companion reads Twitch chat only. Moderation is not started | 3 | token storage policy | Needs accounts, tokens and network to test; tokens must never be stored in plain config |
| Creator assistant | Partial | Plain words insights and readiness fixes. No conversational assistant | 3 | optimizer history | No data or tests to justify more |
| Audio | Done | Five audio profiles with light and full chains, noise suppression | | | |
| Recording | Partial | Local copy via tee (fixed in 0.12: explicit map, global header, `onfail`), numbered files after reconnect, `.mp4` as fragmented MP4, CBR option. WEBM rejected: needs a second VP9 encode that defeats the low-end goal. Recording is continuous across an ingest failure only with `--persistent-ingest`; otherwise the next file starts. No instant replay, clips, highlights, cleanup or space estimate | 2 | recording folder policy | Replay needs a rolling buffer, which costs RAM or disk on low-end PCs |
| Analytics | Done | Opt-in session reports and 30 session history without keys or URLs | | | |
| Stream presets | Done | Eight presets, including `facebook_live` (RTMPS ingest; real go-live UNVERIFIED) | | | |
| Facebook Live | Partial | RTMPS ingest, `--platform facebook` and `facebook_live` preset, unit tested (v0.10). Real go-live UNVERIFIED | | | |
| VP9 and AV1 output | Roadmap | Design only. Measured CPU cost on one thread: x264 3.04 s, VP9 4.84 s, AV1 6.25 s per 10 s of 720p30 (`audit/EVIDENCE.md`). H.264 stays the default; see BLUEPRINT section 3 | 3 | codec acceptance check per platform | Quality per bit was not measured and platform acceptance was not checked |
| Persistent ingest, no-reconnect scaling | Partial (0.12, opt-in) | `--persistent-ingest` split publisher, loopback VERIFIED; platform reaction to the gap UNVERIFIED, about 10 percent of frames near a restart were lost in the spike. Default scaling still restarts ffmpeg | 2 | real platform test | Needs a real ingest |
| SRT output and packet loss | Partial (0.12) | `srt://` custom URL validated and tested on loopback. Reading SRT loss statistics is not implemented (Roadmap); RTMP shows backpressure only | 2 | SRT stats parsing | Needs netem or a lossy link |
| Backup endpoints | Roadmap | Design only (BLUEPRINT section 3) | 2 | `backup_url` config, restart path | Needs a network and a real ingest to test |
| Emergency mode and weak connection mode | Done (0.11.0), PARTIALLY VERIFIED | `emergency.py`; `--emergency`, `--weak-connection`, GUI Emergency button with Restore. Argv accepted by real ffmpeg; effect on real streams UNVERIFIED. Reuses the auto-scale floor and restart path | 2 | auto-scale restart path | Needs a real stream to validate triggers |
| Low-end super mode | Partial | Potato Stream 2000k/4000k (0.12, fps/size/threads from measurements; grayscale rejected as a CPU saver), `potato` profile, hardware profiles, auto-scale. Not a single switch and not measured on a low-end laptop | 2 | real low-end benchmark | No such hardware here |
| Multi-device viewing, OBS layer | Roadmap (design only, 0.12) | [MULTI-DEVICE.md](architecture/MULTI-DEVICE.md). LAN preview works through an `srt://` custom URL. No remote play (Moonlight, Parsec class): decision recorded | 3 | viewer app, relay | Needs devices and a transport browsers can play |
| Mobile remote | Roadmap (v0.12 decision: not started) | Design: stdlib `http.server` bound to 127.0.0.1 by default, random token per run, off by default, never exposes stream keys. LAN binding only by explicit option | 3 | start/stop controller API | Network exposure needs a security review and a phone to test |
| Plugin architecture | Partial (spec only, 0.11.0) | Protocol spec in [architecture/PLUGIN-PROTOCOL.md](architecture/PLUGIN-PROTOCOL.md), no code. Design: each plugin is a subprocess that talks a narrow JSON protocol over stdin and stdout. In-process Python cannot be sandboxed, so in-process plugins are rejected | 3 | protocol spec, event list | A protocol should follow real use cases, not precede them |
| Onboarding | Done | Setup wizard, readiness score, first-run FFmpeg helper. Window rendering VERIFIED on Linux/Xvfb only, Windows and macOS UNVERIFIED | | | |
| UI/UX (dark mode, compact mode, shortcuts) | Done (0.11.0), polished in 0.13; rendering VERIFIED on Linux/Xvfb only | Dark and light themes, compact mode, shortcuts, sparkline graphs; contrast tested to WCAG AA. On-screen rendering never run | 2 | none | Cannot be checked without a display |
| Web site (accessibility, offline) | Done (0.11.0), polished in 0.13; layout VERIFIED in headless Chromium only | Landmarks, 44px targets, light scheme, reduced motion, offline service worker; static checks in node tests | | | Headless browser does not run in the dev sandbox |
| Architecture refactor | Partial | Incremental: logic stays in tkinter-free modules. No DI container or event bus this round | 3 | | A container adds indirection for no current need; injected callables already make tests possible |
| Adaptive Creator Intelligence | Partial | Phase 1 done: opt-in local history raises optimizer confidence. Later phases: deterministic rules that compare sessions (same game, same hour) and suggest a profile. No cloud, no learning model | 2 | history from real users | Rules need real data to avoid guessing thresholds |

Phase 2 is the next release, phase 3 is after that. These are ordering notes, not dates.

## Local control API (decision for v0.12)

Not implemented. Reason: the plugin protocol in `docs/architecture/PLUGIN-PROTOCOL.md` is stdio only, so no consumer needs a network port yet, and a listening socket adds attack surface that needs its own review (bind to 127.0.0.1 only, random token from `secrets`, constant-time compare, nonce replay protection, off by default). Building it without a client would be infrastructure for a hypothetical need. It stays Roadmap until a concrete client exists.
