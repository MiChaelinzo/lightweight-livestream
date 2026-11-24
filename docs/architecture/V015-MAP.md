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
| 1 | Modern Glassmorphism Interface (themes) | Extended | `gui_theme.py` has light, dark, compact, sparklines and WCAG `failing_pairs`. FEAT-002 adds six palettes, a theme picker, reduce-motion | Tokens already exist, only new token sets are needed |
| 2 | AI Stream Copilot | Extended | `optimizer.py` `build_insights` (rule insights with confidence), health score, `optimize` confirmation. FEAT-003 adds clipping and latency insights, an `expected_gain` field filled only from measured local history, and a thin `AIStreamingAssistant` facade | No language model. Gains need measured data, otherwise direction only |
| 3 | Adaptive Streaming Engine | Existing, limited | Adaptive autoscale ladder restarts the encoder. Opt-in `--persistent-ingest` keeps the ingest connection alive (CLI and GUI). Not changed in v0.15 | See decisions: live encoder reconfiguration was rejected, see ARCHITECTURE-NOTES.md |
| 4 | Scene Composer (drag and drop) | Roadmap | `scenes.py` turns scene JSON into `filter_complex`. No visual composer | A Tk canvas composer is too large for this release. Scene JSON already works |
| 5 | Ultra Low-End Mode (Potato) | Existing | Potato Stream, `potato_2000`/`potato_4000` presets, emergency mode. v0.15 only feeds reduce-motion from it | Done in earlier releases |
| 6 | Performance Dashboard | Extended | `gui_theme.py` sparklines and compact mode. FEAT-002 adds eased health-card values; FEAT-004 adds a text creator dashboard | Native Tk cannot blur. Glass look is layered tinted cards. Real backdrop blur exists only on the web page |
| 7 | Intelligent Recording (highlights) | New | `highlights.py` (FEAT-004): heuristic scoring from scene change, audio bursts and motion; clip cutting and 9:16 export | Nothing existed. HEURISTIC only, no semantic detection, ML out of scope |
| 8 | Stream Health AI (score) | Extended | `health.py` `HealthTracker`, `performance_health`, `session_health`. FEAT-003 adds an audio clipping factor only when data is present | Avoids a score built on missing data |
| 9 | Plugin Ecosystem | New | `docs/architecture/PLUGIN-PROTOCOL.md` is spec only. FEAT-005 adds `plugins.py` runtime v1, off by default | Subprocess is not OS isolation, and in-process Python cannot be sandboxed |
| 10 | Beautiful Audio System | Extended | `audio.py` has 5 profiles. FEAT-003 adds Teaching, Meeting and autogain (`dynaudnorm`), plus `audio_check.py` (clipping, loudness) | Echo removal is not available in ffmpeg and will not be claimed |
| 11 | Creator Dashboard | New | `lightstream dashboard` text summary of history, recordings, clips, free disk (FEAT-004). A GUI page only if low risk | Text first, GUI is optional |
| 12 | Benchmarking Laboratory | Extended | `bench.py` and `tools/spikes.py` exist. FEAT-005 adds `tools/benchlab.py` to sample CPU and RSS of any process by PID or command | Competitor columns stay UNKNOWN by default; the user runs it on their own machine |
| Q | Quantum Mode | Existing, renamed | No new engine. It is `optimize` + `bench` + `hardware` detection + analytics history, presented together | See decisions |

## Decisions

1. **No folder restructure.** A move to `/core`, `/plugins` and similar was rejected: it would rewrite imports in `src/`, tests, PyInstaller spec and docs for no behavior gain. Work lands as incremental flat modules in `src/lightstream/`.
2. **"Restart-free" means persistent ingest.** The viewer-facing RTMP connection stays up through `--persistent-ingest` while the encoder restarts. Live encoder reconfiguration (sendcmd, zmq) was rejected, see ARCHITECTURE-NOTES.md. A restart still loses about 10 percent of frames near it in the spike.
3. **Copilot gains only from measured data.** `expected_gain` is filled from local history or bench rows and shows sample size n. Without data the text states direction only. No invented numbers.
4. **Echo removal is not available in ffmpeg.** Docs say so. No echo-cancel profile is shipped.
5. **Quantum Mode is not a new engine.** It is the existing optimize, bench, hardware and history modules under one name. Any claim of quantum computing is out of scope.
6. **Competitor numbers are UNKNOWN.** Benchlab ships a method and empty columns.
7. **Highlights are heuristic.** No game-event detection, no ML.
