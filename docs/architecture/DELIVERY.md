# Delivery: testing, DevOps, release roadmap and competitive benchmarking

Covers how LightStream is tested and shipped, the plan from v0.10 to v1.0, how to measure it against OBS Studio, Streamlabs and XSplit, and what is different by design. Related: [BLUEPRINT.md](BLUEPRINT.md), [AUDIT.md](../audit/AUDIT.md), [EVIDENCE.md](../audit/EVIDENCE.md), [TOP-100.md](../audit/TOP-100.md), [ROADMAP.md](../ROADMAP.md), [RELEASING.md](../RELEASING.md), [BENCHMARKS.md](../BENCHMARKS.md). Index: [docs/README.md](../README.md).

## 1. Testing strategy

**Status: Partial.** Unit and parity tests exist and pass. Integration, soak and budget tests are Roadmap.

Today (VERIFIED, re-run for this document): 452 unittest tests across 23 files (2 skip without `LIGHTSTREAM_TEST_FFMPEG`), 25 node tests for `web/`, `tools/export_presets.py --check`, `python3 -m compileall -q src`.

| Layer | What it covers | State |
|---|---|---|
| Unit, fake clock and fake process | command building, config precedence, key handling, reconnect and backoff, auto-scale hysteresis, optimizer rules, telemetry parsing on sample text | Done |
| Real FFmpeg | bench encode, perf profile thread math against a real binary (`LIGHTSTREAM_TEST_FFMPEG`) | Done, 2 files |
| Web logic | presets parity, bandwidth maths, companion URL parsing and chat sanitizing | Done (node) |
| Golden argv per profile | exact FFmpeg argument lists stored in files, diffed on change | Roadmap |
| Local RTMP integration | run FFmpeg against a local RTMP listener (`ffmpeg -listen 1`) and check the stream arrives | Roadmap |
| Budget tests | fail if Python RSS or import time passes a ceiling | Roadmap |
| Soak | hours long run on fake input, check RSS growth is flat | Roadmap |
| GUI | pure functions (layout math, theme contrast) unit tested; window rendering by manual checklist on a real display | Roadmap |
| Security | tests that no log, file or API response holds the key; plugin and control API fuzz of malformed lines | Partial (key tests exist) |

Every feature must answer how it is verified. Output labels: VERIFIED only when a test or command was run and its output recorded; PARTIALLY VERIFIED when only read; UNVERIFIED otherwise. Flaky tests are not retried silently. Competitor benchmarks are not tests, they are runs described in the methodology below.

## 2. DevOps strategy

**Status: Partial.**

| Piece | State | Label |
|---|---|---|
| CI (`.github/workflows/ci.yml`): Ubuntu and Windows, Python 3.9 to 3.12, compileall, unittest, node tests, presets check | file exists | UNVERIFIED, billing lock means it never ran |
| Release (`.github/workflows/release.yml`): tag `v*` builds Windows, macOS, Linux with PyInstaller, publishes with `SHA256SUMS.txt` | file exists | UNVERIFIED; Linux local build VERIFIED for 0.8.0 |
| Version in two places (`__init__.py`, `pyproject.toml`) | manual bump, release workflow checks the tag | Partial |
| Web deploy on Vercel with a CSP in `web/vercel.json` | configured | UNVERIFIED deployment |

Plan: run the CI commands locally as the gate until billing is fixed (the gate is `python3 -m compileall -q src`, `python3 -m unittest discover -s tests`, `node --test "web/test/*.test.js"` and `python3 tools/export_presets.py --check`); add the budget and golden tests to CI; add a test that asserts the two version strings match; sign builds later; keep `.agents/` and generated bench JSON out of git. No new infrastructure is proposed beyond what GitHub Actions already gives.

## 3. Release roadmap v0.10 to v1.0

Ordering, not dates. Each release lists items from [TOP-100.md](../audit/TOP-100.md) and an exit check. A release is not done until its exit check is run and recorded.

| Release | Theme | Contents | Exit check |
|---|---|---|---|
| 0.10 | Audit and safety | audit docs, Facebook Live RTMPS, private atomic writes, encoded-key redaction | 452 tests pass (done at time of writing); docs index complete |
| 0.11 | Measurement guards | golden argv tests, memory and startup budget tests, version consistency test, config schema version, competitor benchmark runner in `tools/` | budget tests fail when a ceiling is raised on purpose; runner prints UNKNOWN for missing tools |
| 0.12 | Resilience | emergency mode, weak connection mode, backup endpoint, per-tier presets in the wizard | tests with fake processes for each; one real FFmpeg restart test |
| 0.13 | Window polish | design tokens, dark and compact mode, sparklines, shortcuts | contrast math tests; manual run on a real display recorded with screenshots |
| 0.14 | Integrations | plugin protocol and SDK, local control API, mobile remote page | protocol and token tests; threat review written |
| 0.15 | Creator tools | replay buffer (opt-in, disk), clip marks, recording space estimate | disk cap test; Tier 1 default stays off |
| 0.16 | Verification on real machines | Windows exe run, a real go-live on each platform, measured low-end laptop report, hardware encoder bench | results added to README verification table; failures documented |
| 1.0 | Stable | CI green on GitHub, signed builds, support bundle, soak result, competitor comparison run by someone with those tools (or the section stays UNKNOWN) | every item in the README table is VERIFIED or listed as a known limit |

1.0 does not require every Roadmap row. It requires that nothing labeled Done is unverified on Windows and that the claims in the README are measured.

## Competitive benchmark methodology

**Status: Roadmap (method only).** No competitor was installed or run here. Every competitor result below is **UNKNOWN**. The tools named for measuring were not run in this environment, so the commands are UNVERIFIED and may need adjusting. Do not copy numbers from forums into this table; if public numbers are cited later they need a source, a version and a hardware description.

### Principles

- Same machine, same scene, same encoder settings, same destination, one product at a time, nothing else running.
- Fix the settings: libx264 `veryfast` (or the same hardware encoder on both), 1280x720 at 30 fps, 3000 kbps CBR, 2 second keyframes, AAC 128 kbps. Record each product's version and the actual encoder it used.
- Send to a local sink so the network does not change results. Example sink: `ffmpeg -listen 1 -i rtmp://127.0.0.1:1935/live/test -f null -` (UNVERIFIED here). Run a second round to a real ingest only for dropped-frame behavior.
- A fixed, repeatable load: a game with a built-in benchmark or a looped capture video, same resolution, same graphics settings.
- Five runs per product, 10 minutes each after a 1 minute warm-up. Report median and min to max. Reboot or idle the PC to a stated baseline between products.
- Record: OS build, CPU, RAM, GPU and driver, power plan, background apps.

### Metrics and how to read them

| Metric | How | Notes |
|---|---|---|
| Idle RAM (app open, not streaming) | private working set of the app process tree | Windows: Task Manager details or `Get-Process`; Linux: `ps -o rss`. Count child processes (the encoder, any web view) |
| Streaming RAM | same, median over the run | include FFmpeg or encoder children, since the total matters on 4 GB PCs |
| CPU share | process tree CPU time divided by wall time and core count | Windows `typeperf "\Process(*)\% Processor Time"`; Linux `pidstat -p ALL`. Report per core and total |
| GPU use | vendor tool or Task Manager GPU columns | name the engine (3D, video encode) |
| Game FPS and frame time | PresentMon or the game's benchmark output | this is the metric that tells if Gaming First helps; average and 1 percent low |
| Startup time | wall time from launch to ready to stream | stopwatch or scripted window detection; five runs, cold and warm |
| Dropped frames and stability | the product's own stats plus the sink's received frame count | do not compare dropped counts across products without checking each definition |
| Encode speed headroom | FFmpeg `speed=` for LightStream; the product's encoder overload indicator | definitions differ, state them |

### LightStream side (runnable now, on the target PC)

```
python3 -m lightstream bench --ffmpeg <path-to-ffmpeg> --seconds 30 --import-runs 21 --out bench-<pc>.json
python3 -m lightstream readiness --ffmpeg <path-to-ffmpeg>
```

The bench report labels each metric `measured` or `unavailable`. It does not include game FPS. Do not commit the generated JSON to the repo.

### Result table (to be filled by whoever runs it)

| Metric | LightStream | OBS Studio | Streamlabs | XSplit |
|---|---|---|---|---|
| Idle RAM | not measured on target PC | UNKNOWN | UNKNOWN | UNKNOWN |
| Streaming RAM | not measured on target PC | UNKNOWN | UNKNOWN | UNKNOWN |
| CPU share | not measured on target PC | UNKNOWN | UNKNOWN | UNKNOWN |
| Game FPS (avg, 1 percent low) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Startup time | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Dropped frames | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

Only the sandbox figures in [EVIDENCE.md](../audit/EVIDENCE.md) exist for LightStream (Python process 22.7 MB RSS, about 52 ms import). They are not comparable to a full streaming app's memory because FFmpeg is a separate process and the sandbox is not a low-end PC. A Roadmap item adds a runner script under `tools/` that automates the LightStream side and prints UNKNOWN for tools it cannot find.

## Competitive advantages derived from design facts

These follow from how LightStream is built. They are design properties, not measured wins, and none claims better performance than any other product.

| Design fact (where) | What it means for a user | Trade-off, stated |
|---|---|---|
| One external FFmpeg process, no relay, no embedded browser (`runner.py`, ARCHITECTURE-NOTES) | fewer processes and less memory to account for on a 4 GB PC | no browser source engine; overlays are FFmpeg filters, the companion runs in OBS or a browser |
| Stdlib only, `dependencies = []` | nothing to install, small attack surface, 22.7 MB Python process measured | features that need libraries (graphics, rich UI) are out of reach or must be written by hand |
| Quality changes only with `--auto-scale` and each change states its reason | no surprise changes for people who want control | a quality step restarts FFmpeg, so viewers see a short interruption |
| Explained insights with confidence (`optimizer.py`) | the user sees why, in plain words | rule based, not learned, thresholds unvalidated on real streams |
| Key from environment or hidden prompt, redacted in logs, never saved | low risk of leaking a key through files or screenshots of logs | key remains in the process list while FFmpeg runs |
| Dry run prints the exact redacted command | easy to inspect and reproduce | users must read FFmpeg arguments to benefit |
| Built-in `bench` and `readiness` | the user can measure their own PC in minutes | it measures LightStream and FFmpeg, not competitors |
| Open hardware profiles for Intel HD and MX250 | defaults aimed at weak PCs | flags never run on real hardware |

What competitors do that LightStream does not (today): RTMP only; no mid-stream scene switching; no browser source engine; no plugin ecosystem; no alerts, no moderation, no game capture source; window not run on real Windows in this environment. These gaps are listed in [ROADMAP.md](../ROADMAP.md) and [TOP-100.md](../audit/TOP-100.md).
