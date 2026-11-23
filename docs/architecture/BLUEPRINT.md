# Blueprint (v0.10 and later)

Design for the next releases of LightStream. Every section starts with a status line: **Done** (in code and unit tested), **Partial**, or **Roadmap** (design only, no code). A design here is an intention, not a claim that it works. Do not read Roadmap text as a feature.

Related: [AUDIT.md](../audit/AUDIT.md) (what is true today), [EVIDENCE.md](../audit/EVIDENCE.md) (measurements), [DELIVERY.md](DELIVERY.md) (tests, release plan, benchmarks), [TOP-100.md](../audit/TOP-100.md), [ROADMAP.md](../ROADMAP.md) (status table, not repeated here), [ARCHITECTURE-NOTES.md](../ARCHITECTURE-NOTES.md) (auto-scale design, not repeated here). Index: [docs/README.md](../README.md).

Fixed rules for every section: stdlib first, no Electron, no embedded Chromium, FFmpeg is not bundled, one FFmpeg process per stream, plugins are subprocesses speaking JSON, and nothing changes quality or settings unless the user opted in.

## 1. Architecture and target tiers

**Status: Partial.** The module layout exists. Tier presets in the wizard and a single low-end switch are Roadmap.

```
 tkinter window (gui.py, gui_pages.py)      CLI (cli.py)        web/ (static, no key)
            \                                 /
             StreamController (gui_controller.py)  <- one place that starts, stops, reports
                     |
   config -> presets/perf_profiles -> command.py -> runner.py -> ONE ffmpeg subprocess
                     |                                   |
   optimizer, autoscale, health, telemetry <------- progress lines (stderr)
```

Rules: logic lives in tkinter-free modules; the window only gathers input and shows results; every module takes its clock, process launcher and file system access as arguments so tests can fake them. This is how the code is written now (see [AUDIT.md](../audit/AUDIT.md) section 6, checks 2 and 4).

### Tiers

| Tier | Typical PC | Default profile | Default geometry (from `presets.py`) | Notes |
|---|---|---|---|---|
| 1 | Intel HD graphics, 4 GB RAM | `potato` | 640x360 at 24 fps, 700 kbps | software x264 with 2 threads, or QSV through the `intel_hd` hardware profile if the test encode passes |
| 2 | Intel UHD, 8 GB RAM | `balanced` | 1280x720 at 30 fps, 2500 kbps | `light` (854x480 at 30) when the game is heavy |
| 3 | MX250, Radeon Vega, Iris Xe | `balanced` or `competitive` | 720p30 or 720p60 | hardware encoder preferred (NVENC, QSV, AMF); never run on real hardware here |

The profile names and geometry exist in `perf_profiles.py` and `presets.py` (Done). Mapping a detected PC to a tier by the wizard is Roadmap. The tier boundaries are design choices and UNVERIFIED against real PCs.

## 2. Performance, memory, CPU and GPU budgets

**Status: Partial.** Budgets are targets. Only the Python process numbers were measured, on a Linux sandbox.

| Budget | Target | Measured today | Label |
|---|---|---|---|
| Total RAM (LightStream plus its FFmpeg child) | under 300 MB on every tier at the default profile | Python 22.7 MB; potato encode child 28.2 MiB peak, balanced 87.1 MiB ([BENCHMARKS.md](../BENCHMARKS.md)); a default-threads x264 test peaked at 259 MB ([EVIDENCE.md](../audit/EVIDENCE.md) section 4) | VERIFIED on sandbox, UNVERIFIED on tier hardware |
| Python process RSS | under 50 MB | 22.7 MB | VERIFIED |
| Startup (import) | under 100 ms on this sandbox, the budget scales with CPU | about 52 ms | VERIFIED on sandbox |
| LightStream CPU (ticks, parsing) | under 1 percent of one core | telemetry tick about 110 microseconds, optimizer about 51 microseconds, run about once per second | VERIFIED per call, not as a share on a low-end CPU |
| FFmpeg CPU | tier dependent; the encoder is the cost | libx264 veryfast 720p30, one thread: 3.04 CPU s per 10 s of video | VERIFIED, synthetic source, sandbox |
| GPU | zero for software path; hardware encoder uses the media engine | not measured | UNVERIFIED |

How the budget is enforced (Roadmap): a memory budget test and a startup budget test in `tests/` that fail when the Python process crosses a ceiling (see [DELIVERY.md](DELIVERY.md#1-testing-strategy)); the 300 MB total is checked by the user's own `lightstream bench`, because FFmpeg memory depends on settings. If the default-threads x264 result (259 MB) is what a Tier 1 PC sees, the 300 MB target would be at risk, so Tier 1 keeps `-threads 2` through the `potato` thread cap (Done).

## 3. Streaming engine

**Status: Partial.** Twitch, YouTube, Facebook Live (RTMPS) and custom RTMP exist. Backup endpoints, regional ingest choice and VP9 or AV1 output are Roadmap.

Today: `command.py` builds one FFmpeg command; `runner.py` runs it with reconnect and backoff capped at 30 s; `platforms.py` holds `INGEST_URLS` for `twitch`, `youtube`, `facebook` and a `custom` URL.

### Platforms

Adding a platform means one entry in `INGEST_URLS` and `PLATFORMS`, one stream preset in `perf_profiles.py` and one test. Facebook Live was added that way in v0.10 (`rtmps://live-api-s.facebook.com:443/rtmp/`, PARTIALLY VERIFIED: URL and redaction tested, FFmpeg's TLS tried a closed local port, no real go-live). Ingest URLs and limits change over time, so each must be re-checked against the platform's current documentation before a release; that check has not been done here.

### Backup endpoints (Roadmap)

- Config: `backup_url` (same format as `url`); the key still comes from the environment, never from a file.
- Trigger: after `FALLBACK`-style quick failures on the primary (the same counting used for encoder fallback in `runner.py`), switch to the backup and restart through the existing reconnect path (`restart` event, as the auto-scaler does). Return to the primary only on a manual action, to avoid flapping.
- Messages and logs use the redaction already in `runner.py`; the new URL must pass through `redact` too, with a test for it.
- Not designed: sending to both at once (needs twice the upload; listed as a separate Roadmap item).

### VP9 and AV1 strategy, from measured evidence

Measured (one sample each, synthetic 720p30, 4500 kbps, one thread, sandbox; [EVIDENCE.md](../audit/EVIDENCE.md) section 4):

| Encoder | CPU s per 10 s of video | Relative to x264 |
|---|---|---|
| libx264 veryfast | 3.04 | 1.0 |
| libvpx-vp9 realtime, cpu-used 5 | 4.84 | about 1.6 |
| libaom-av1 realtime, cpu-used 8 | 6.25 | about 2.1 |

Quality per bit was not measured, so any claim that VP9 or AV1 saves bandwidth is UNVERIFIED here. Decision:

1. H.264 stays the default on every tier. The target audience is low-end PCs, and the software alternatives cost 1.6 to 2.1 times the CPU at these settings.
2. VP9 and AV1 are opt-in, off by default, and only offered when (a) the user picks them, and (b) the destination is known to accept the codec. Whether Twitch, YouTube or Facebook accept VP9 or AV1 over RTMP at ingest must be read from their current documentation; that was not checked here. Local recording to Matroska works with FFmpeg's native encoders and is the safest first use.
3. AV1 only through hardware encoders when detected (Roadmap), because software AV1 at 6.25 CPU s per 10 s is not suited to Tier 1 or Tier 2. This build had no `libsvtav1`.
4. Before shipping, run the codec table on target hardware with a bitrate and quality measurement, and replace this table.

## 4. Performance plan: emergency mode and weak connection mode

**Status: Done in 0.11.0 (`src/lightstream/emergency.py`), PARTIALLY VERIFIED.** Tests cover the settings, the CLI flags, the controller action and restore, and ffmpeg 7.0.2 accepting the resulting argv (test source, file output). Not run: a real stream, real network trouble, the Tk button. Implemented on top of what existed: the auto-scale ladder floor (`DEFAULT_FLOOR_PRESET = "potato"` in `autoscale.py`), the restart path, `AdaptiveAdvisor` thresholds (`SLOW_SPEED_BELOW = 0.90`), the light audio chain and the bandwidth advisor.

### As built (0.11.0)

- `emergency_settings`: potato size, fps, bitrate and x264 preset (never above the current value), thread cap of 2, scene (overlays, webcam) dropped, noise and audio filter off, 0.5 second buffer. Recording is kept.
- `weak_connection_settings`: 0.6 times the bitrate (lower still when `--upload-mbps` is given, via `bandwidth.recommend`), keyframe every second, 2 second buffer. With both flags, the weak buffer wins. It is a mechanism; its benefit on a real bad link is UNVERIFIED.
- CLI: `start --emergency`, `--weak-connection`, `--upload-mbps`. Only at launch; never triggered automatically.
- GUI: one Emergency button (no confirmation) on the dashboard. It sets `current_settings` and the runner restart event; auto-scale is paused so it cannot undo the step. The same button then reads Restore and brings back the previous settings and auto-scale choice. Viewers see one short interruption.
- Backup ingest: `--backup-url rtmp://host/app` (or `backup_url` in config, GUI Advanced). Validated by `validate_backup_url`: rtmp or rtmps, no embedded key. The same stream key is appended at launch. After 3 consecutive quick non-encoder failures `run_with_reconnect` reports status `failover` and launches the backup argv; 3 quick failures there switch back. A healthy run resets the count. A recording continues in the next numbered file (`name-N.mkv`) because each launch builds its own argv. Not done: choosing the backup by latency, pre-checking it, failing back to the primary after it recovers while the backup stays healthy.

### Emergency mode workflow (original design)

Goal: one user action to the safest stream, when the PC or network is failing mid-stream.

1. Trigger: a button, a CLI flag, or (only when the user opted into auto changes) sustained stress that auto-scale cannot fix at the floor step.
2. Apply, in one restart: floor preset (`potato` geometry and bitrate), light audio chain, no webcam or overlays, no noise suppression, recording kept as is.
3. Say what changed in plain words, with the old and new numbers.
4. Stay in the mode until the user leaves it; no automatic step up, to avoid flapping.
5. Record the event in the opt-in history (no key or URL).

Failure conditions to test: restart fails, FFmpeg exits during the switch, user triggers it twice. Viewers see one short interruption (ffmpeg restart), same as an auto-scale step.

### Weak connection mode

Goal: keep a stream alive on bad upload. Inputs: the bandwidth advice (`bandwidth.py`), the stability score (`HealthTracker.network_stability`), the TCP connect time. Actions: cap video bitrate at the advised value, keep a short keyframe interval, and keep the reconnect loop. Recovery buffering needs a second process and is rejected for now ([ARCHITECTURE-NOTES.md](../ARCHITECTURE-NOTES.md)). Packet loss is not reported by FFmpeg RTMP output, so the mode must use the inferred score, and say so.

## 5. Scene system

**Status: Partial.** Done: screen, window, browser, webcam, image and text sources with overlays, scene files, collection export and import (`scenes.py`, `scene_collections.py`). Roadmap: Game Capture, video file and alerts sources, switching while live.

Design: scenes stay data (JSON) validated at load with clear errors (already the pattern in `scenes.py`). A scene is compiled to a filter graph at start (`compile_scene`). FFmpeg cannot change its graph while running, so mid-stream switching needs one of: restart (short interruption), or a second process (rejected). The honest plan is restart-based switching, announced in the window, and a "scene cost" estimate before going live (Roadmap) so the user sees what an overlay costs on their tier.

## 6. Audio subsystem

**Status: Partial.** Done: five profiles (`gaming`, `podcast`, `music`, `commentary`, `asmr`), light and full chains, `--noise off|light|ai` (ai needs a user supplied `.rnnn` model). The ten chains were run through FFmpeg 7.0.2 (VERIFIED, README). Roadmap: level meter and clipping warning, per-source mixing and ducking, sync offset.

Design: keep audio in one FFmpeg filter chain. A meter needs a second reading path (the `astats` or `ebur128` filter output parsed from stderr, which would add log volume; measure before adopting). Mixing multiple sources raises input count and CPU; Tier 1 gets the light chain only.

## 7. Smart optimization engine

**Status: Partial.** Done: rule based `optimizer.py` with `Insight(area, action, value, confidence, explanation, plain_text)`, opt-in history raising confidence, opt-in auto-scale. Roadmap: learned model, cross-session rules.

Design: stay deterministic and explainable. Next step (Roadmap) is rules that compare sessions of the same game and hour from `history.json`, with thresholds read from data, not guessed. A learned model is deferred until real sessions exist; there is no data now. Nothing is applied without opt-in, and each change prints its reason.

## 8. AI assistant (local and cloud)

**Status: Partial** for the rule based plain-words assistant; **Roadmap** for any language model.

| Option | Design | Rules |
|---|---|---|
| Rule based (today) | Insights and readiness fixes in plain words | works offline, no data leaves the PC |
| Local model (Roadmap) | The user points to their own local model server or binary; LightStream sends only the insight rows (numbers and class names), never the key, URL or paths | subprocess or `127.0.0.1` HTTP; off by default; not bundled |
| Cloud (Roadmap) | Same payload, explicit consent, user supplied API key kept in an environment variable | off by default; payload previewed before sending; no chat or audience data |

The assistant may explain and suggest. It may not apply changes. Applying stays with the opt-in auto-scale and explicit user action. Cost and latency per request are UNVERIFIED because no adapter exists.

## 9. Plugin ecosystem and SDK

**Status: Roadmap.** Matches [ROADMAP.md](../ROADMAP.md): each plugin is a subprocess talking a narrow JSON protocol over stdin and stdout. In-process Python plugins are rejected because they cannot be sandboxed.

Design sketch (to be finalized with real use cases, not before):

- Transport: one JSON object per line, UTF-8. Host sends `{"v":1,"event":"stream_started"}`, `stream_stopped`, `insight`, `status`. Plugin sends `{"v":1,"action":"log","text":"..."}` or `{"v":1,"action":"overlay_text","text":"..."}`.
- The host never sends the stream key or URL. Plugins declare needed events in a manifest; unknown events are dropped.
- Limits: line length cap, timeout per message, one restart then disabled, a kill switch in the window and CLI.
- SDK: a single stdlib Python file (about 100 lines) with a read loop and helpers, plus one sample plugin. No package to install.
- Test plan: protocol round trips with fake pipes, a malformed line test, a plugin that hangs, a plugin that floods.

## 10. UI modernization and design system

**Status: Partial for the window; Roadmap for dark mode, compact mode, shortcuts and tokens.** The window uses tkinter and ttk only. Rendering was never run in this environment (no display), so layout claims are UNVERIFIED.

Design: one `theme` module holding named tokens (colors, spacing, font sizes) with a light and a dark set, consumed by `gui.py` and `gui_pages.py`. Contrast ratios between token pairs are pure math and can be unit tested without a display. Keep the three step flow. No web view inside the app.

## 11. Dashboard

**Status: Partial.** Numeric telemetry cards every 2 seconds (Done, logic tested, rendering UNVERIFIED). Roadmap: sparklines.

Design: draw sparklines on a `tk.Canvas` from the bounded sample buffers that `telemetry.py` and `health.py` already keep (no new data store). Pure functions turn a buffer into canvas coordinates, so they can be tested without a display. Redraw at most every 2 seconds to keep the dashboard cost near zero.

## 12. Mobile companion API

**Status: Roadmap.** Per [ROADMAP.md](../ROADMAP.md): stdlib `http.server` on `127.0.0.1` by default, a random token per run, off by default, never exposes stream keys; LAN binding only by explicit option.

Endpoints (design): `GET /status` (state, speed, dropped frames, stability), `POST /stop`, `POST /emergency`. No `/start` with a key. Token in an `Authorization` header, compared with `hmac.compare_digest`. A phone page is a static file under `web/`. Before shipping: threat review for LAN binding, a test for token failure, a test that no response contains the key. The existing browser companion (`web/companion/`, Twitch chat and timer, VERIFIED logic, UNVERIFIED rendering) is a different thing: an OBS browser-source overlay, not a remote.

## 13. Creator tools

**Status: Partial.** Done: local recording through tee, numbered files after reconnects, opt-in session reports, overlays (text, clock, FPS, REC, PNG). Roadmap: replay buffer, clip marks, recording space estimate, chat moderation, alerts.

Design rule: a rolling replay buffer costs RAM or disk, so it is off on Tier 1 and, when enabled, writes segments to disk with a fixed cap that the user sees. Chat tokens are stored only through environment variables or the OS keyring, never in `config.json`.

## 14. Network optimization

**Status: Partial.** Done: stability score (an inference), TCP connect latency, bandwidth advice, reconnect backoff. Roadmap: ingest server lists, regional choice, RTT trend, packet loss measurement.

Design: a per-platform list of ingest hosts, measured with `measure_connect_latency` (key never part of it), shown as a hint. True loss needs a probe outside the RTMP stream, which means extra traffic and code; only add it if the inferred score proves too coarse in real sessions.

## 15. Security hardening

**Status: Partial.** The review is in [EVIDENCE.md](../audit/EVIDENCE.md) section 5. Fixed in v0.10: private atomic writes (mode 0600 on POSIX), percent-encoded key redaction. Still open:

| Item | Plan | Label |
|---|---|---|
| Key visible in the process list | Documented limit. FFmpeg has no stdin or env input for the ingest URL | Open, by design |
| Custom `url` with a key in `config.json` | Warn at load when the URL path looks like a key | Roadmap |
| Redaction only for exact and percent-encoded forms | Add forms as they are observed in real FFmpeg output | Open |
| Plugin and remote API surfaces | Threat review before shipping either | Roadmap |
| Signed builds, checksums | `SHA256SUMS` exist for the Linux build; signing is Roadmap | Partial |
| Support bundle | Export without keys, URLs or paths | Roadmap |
