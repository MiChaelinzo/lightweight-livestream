# v0.15 map: upgrade paths to existing code

Status words: **Existing** (already in 0.14), **Extended** (0.14 code grows), **New** (new module), **Roadmap** (not built, with reason). Labels: VERIFIED, PARTIALLY VERIFIED, UNVERIFIED. Competitor (OBS, Streamlabs, XSplit) numbers are UNKNOWN everywhere.

Path numbers and names follow the user's list: 1 Modern Glassmorphism Interface (themes), 2 AI Stream Copilot, 3 Adaptive Streaming Engine, 4 Scene Composer, 5 Ultra Low-End Mode (Potato), 6 Performance Dashboard, 7 Intelligent Recording, 8 Stream Health AI, 9 Plugin Ecosystem, 10 Beautiful Audio System, 11 Creator Dashboard, 12 Benchmarking Laboratory, plus the stretch Quantum Mode (Q).

## Baseline (before any v0.15 change)

Branch `feat/v0.15-copilot-studio` off `feat/v0.14-showcase` at 0.14.0. Environment: Linux sandbox, Python 3.11, ffmpeg 7.0.2 static.

| Suite | Result | Status |
|---|---|---|
| `python3 -m unittest discover -s tests` | 705 tests, OK (3 skipped, display-gated) | VERIFIED |
| `node --test "web/test/*.test.js"` | 42 pass, 0 fail | VERIFIED |
| `tools/export_presets.py --check` | presets.json up to date | VERIFIED |
| `python3 -m compileall -q src` | clean | VERIFIED |
| `tools/page_weight.py` | gzip total 20728 B, images 84984 B | VERIFIED |

## Path map

| # | Path | Status | Existing code and what changes | Reason |
|---|---|---|---|---|
| 1 | Modern Glassmorphism Interface (themes) | Done (0.15.0) | `gui_theme.py` has light, dark, compact, sparklines and WCAG `failing_pairs`. Six palettes, a theme picker and reduce-motion were added | Tokens already exist, only new token sets are needed |
| 2 | AI Stream Copilot | Done (0.15.0) | `optimizer.py` `build_insights` (rule insights with confidence), health score, `optimize` confirmation. Added clipping and latency insights, an `expected_gain` field filled only from measured local history, and a thin `AIStreamingAssistant` facade | No language model. Gains need measured data, otherwise direction only |
| 3 | Adaptive Streaming Engine | Existing, limited | Adaptive autoscale ladder restarts the encoder. Opt-in `--persistent-ingest` keeps the ingest connection alive (CLI and GUI). Not changed in v0.15 | See decisions: live encoder reconfiguration was rejected, see ARCHITECTURE-NOTES.md |
| 4 | Scene Composer (drag and drop) | Roadmap | `scenes.py` turns scene JSON into `filter_complex`. No visual composer | A Tk canvas composer is too large for this release. Scene JSON already works |
| 5 | Ultra Low-End Mode (Potato) | Existing | Potato Stream, `potato_2000`/`potato_4000` presets, emergency mode. v0.15 only feeds reduce-motion from it | Done in earlier releases |
| 6 | Performance Dashboard | Extended | `gui_theme.py` sparklines and compact mode. eased health-card values and a text creator dashboard were added | Native Tk cannot blur. Glass look is layered tinted cards. Real backdrop blur exists only on the web page |
| 7 | Intelligent Recording (highlights) | Done (0.15.0) | `highlights.py`: heuristic scoring from scene change, audio bursts and motion; clip cutting and 9:16 export | Nothing existed. HEURISTIC only, no semantic detection, ML out of scope |
| 8 | Stream Health AI (score) | Extended | `health.py` `HealthTracker`, `performance_health`, `session_health`. an audio clipping factor was added only when data is present | Avoids a score built on missing data |
| 9 | Plugin Ecosystem | Done as library (0.15.0) | `docs/architecture/PLUGIN-PROTOCOL.md` is spec only. `plugins.py` runtime v1 and `lightstream plugins`, off by default, not wired into `start` | Subprocess is not OS isolation, and in-process Python cannot be sandboxed |
| 10 | Beautiful Audio System | Done (0.15.0) | `audio.py` has 5 profiles. Added Teaching, Meeting and autogain (`dynaudnorm`), plus `audio_check.py` (clipping, loudness) | Echo removal is not available in ffmpeg and will not be claimed |
| 11 | Creator Dashboard | Partial (text only) | `lightstream dashboard` text summary of history, recordings, clips, free disk. No GUI page | GUI Creator page stays Roadmap |
| 12 | Benchmarking Laboratory | Extended | `bench.py` and `tools/spikes.py` exist. `tools/benchlab.py` samples CPU and RSS of any process by PID or command | Competitor columns stay UNKNOWN by default; the user runs it on their own machine |
| Q | Quantum Mode | Existing, renamed | No new engine. It is `optimize` + `bench` + `hardware` detection + analytics history, presented together | See decisions |

## Decisions

1. **No folder restructure.** A move to `/core`, `/plugins` and similar was rejected: it would rewrite imports in `src/`, tests, PyInstaller spec and docs for no behavior gain. Work lands as incremental flat modules in `src/lightstream/`.
2. **"Restart-free" means persistent ingest.** The viewer-facing RTMP connection stays up through `--persistent-ingest` while the encoder restarts. Live encoder reconfiguration (sendcmd, zmq) was rejected, see ARCHITECTURE-NOTES.md. A restart still loses about 10 percent of frames near it in the spike.
3. **Copilot gains only from measured data.** `expected_gain` is filled from local history or bench rows and shows sample size n. Without data the text states direction only. No invented numbers.
4. **Echo removal is not available in ffmpeg.** Docs say so. No echo-cancel profile is shipped.
5. **Quantum Mode is not a new engine.** It is the existing optimize, bench, hardware and history modules under one name. Any claim of quantum computing is out of scope.
6. **Competitor numbers are UNKNOWN.** Benchlab ships a method and empty columns.
7. **Highlights are heuristic.** No game-event detection, no ML.

## Final status (0.15.0)

| Area | Status | Evidence |
|---|---|---|
| Palette contrast (WCAG AA) for eight themes | VERIFIED | unit tests |
| GUI themes rendered | PARTIALLY VERIFIED | Xvfb screenshots read by eye, Linux fonts only |
| Audio-check, highlights parsing and scoring | VERIFIED | unit tests and real-ffmpeg tests |
| Highlights quality on real gameplay | UNVERIFIED | only injected sine bursts were tested |
| Plugin runtime on Linux | VERIFIED | tests with real subprocess plugins |
| Plugin runtime on Windows and macOS | UNVERIFIED | never run |
| Benchlab harness | VERIFIED (Linux `/proc`) | harness check in BENCHMARKS.md |
| OBS Studio and Streamlabs comparison | UNKNOWN | not measured |
| GUI look on Windows and macOS | UNVERIFIED | never run |
| Real platform ingest behavior | UNVERIFIED | loopback only |

## Remaining limitations

- SRT packet loss statistics are not read yet.
- The stream key is visible in the ffmpeg argv (process list) while streaming.
- There is no control API and no phone remote.
- Images are not precached for offline use on the web page.
- The GUI persistent-ingest option declines Emergency mode.
- Windows and macOS looks are UNVERIFIED.
- Scene composer (drag and drop), a Creator GUI page, plugin wiring into `start` and live collection of copilot inputs remain Roadmap.

## Final suite (0.15.0)

| Suite | Result | Status |
|---|---|---|
| `python3 -m unittest discover -s tests` | 823 tests, OK (3 skipped, display-gated; not re-run under Xvfb for the release commit) | VERIFIED |
| `node --test "web/test/*.test.js"` | 42 pass, 0 fail | VERIFIED |
| `tools/export_presets.py --check` | up to date | VERIFIED |
| `tools/page_weight.py` | gzip total 20728 B, images 84984 B (web unchanged) | VERIFIED |
