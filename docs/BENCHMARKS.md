# Benchmarks

Status: VERIFIED for the method and for the numbers below on the one machine named here. UNVERIFIED for every other machine, for hardware encoders, for Windows and macOS, and for any real game or live stream.

## Read this first

- The host is a Linux sandbox: 8 cores, 31560 MB RAM, Python 3.11.15, no GPU, no display. It is **not** representative of an MX250 laptop or an Intel i5-U.
- The only encoder available was software x264 (`libx264`) from a static ffmpeg 7.0.2 build. No hardware encoder was listed, so none was benchmarked.
- No game was running. The Gaming First comparison is a **proxy**: it shows how much CPU the encoder uses and how its speed changes with fewer threads. It is **not** game FPS and says nothing about how a game would perform.
- Each encode configuration ran once, for 10 seconds of stream time, as fast as the CPU allowed (no real-time pacing). Run-to-run variation exists: a first run of the same command gave, for example, 12.8x instead of 13.0x for `balanced`. Treat differences of a few percent as noise.
- The synthetic source is ffmpeg `testsrc2`. Its generation cost and the scaler are inside the CPU time. Audio is not encoded.
- The report date inside the JSON is the sandbox clock (2026-11-21).

## Method

Everything is produced by `lightstream bench` (`src/lightstream/bench.py`). The JSON report labels each metric `measured` or `unavailable` with a reason; this document copies the `measured` values.

```
PYTHONPATH=src python3 -m lightstream bench \
  --ffmpeg /projects/sandbox/.cache-ffmpeg/ffmpeg-7.0.2-amd64-static/ffmpeg \
  --seconds 10 --import-runs 21 \
  --compare-src <worktree of b4cbab6>/src --out bench-final.json
```

- Startup: `python -c "import lightstream.cli"` in a fresh interpreter, wall time, median of 21 runs, next to `python -c pass`. RSS is read from `/proc/self/status` in a child.
- Tick cost: mean process CPU time (`time.process_time`) per call over 1000 calls of each component.
- Memory after ticks: a child imports lightstream, then runs 1000 rounds of all six components (including a real telemetry sampler reading `/proc`) and reports RSS before and after.
- Command build: `resolve_settings` plus `build_command` for each performance profile, mean of 1000.
- Encode: `ffmpeg -f lavfi -i testsrc2=size=WxH:rate=F -t 10 -c:v libx264 ... -bf 0 -an -f null -` at each profile's geometry and Gaming First thread count. CPU seconds and peak RSS come from `os.wait4` for each ffmpeg child (user + system CPU). Speed is the last `speed=` value of `-progress`. CPU-seconds per stream-second is child CPU divided by the 10 stream seconds.
- Profiles that resolve to the same preset and thread count are run once (`low_latency` equals `balanced` here, because they differ only in keyframe interval and buffer size, which the benchmark does not vary).

## Results: cost of the code itself

Import and memory, new tree (this branch) against v0.8.0 (`b4cbab6`), same method, same machine, 21 runs each:

| Metric | v0.8.0 | this branch | Difference |
|---|---|---|---|
| `import lightstream.cli` median (ms) | 67.0 | 72.7 | +5.7 |
| import range, min to max (ms) | 65.7 to 69.1 | 70.8 to 75.5 | |
| bare interpreter median (ms) | 10.2 | 10.2 | |
| RSS after import (MiB) | 21.1 | 22.1 | +1.0 |
| RSS of bare interpreter (MiB) | 9.7 | 9.7 | |

The new features cost about 5.7 ms of startup and about 1.0 MiB of memory on this machine. The ranges do not overlap. RSS after 1000 simulated ticks: 21.72 MiB before, 21.72 MiB after (the history buffers are bounded, and no growth showed at this resolution of /proc).

Per-call CPU on this machine (microseconds, mean of 1000 calls). The per-second components run about once a second in a stream (telemetry every 2 seconds), so their cost is a tiny fraction of one core here; a slower CPU scales these numbers up.

| Component | us per call |
|---|---|
| `parse_progress` | 2.24 |
| `HealthTracker.update` | 0.72 |
| `AdaptiveAdvisor.observe` | 0.59 |
| `TelemetrySampler.tick` (reads /proc) | 110.39 |
| `build_insights` (optimizer) | 50.68 |
| `AutoScaler.update` with `assess` | 1.33 |

Command build per profile (us): potato 14.9, balanced 14.7, quality 13.4, competitive 14.5, low_latency 14.2.

## Results: synthetic encode (libx264, software)

| Profile | Geometry | Threads | Wall (s) | ffmpeg speed (x) | Child CPU (s) | Peak RSS (MiB) | CPU s per stream s |
|---|---|---|---|---|---|---|---|
| potato | 640x360@24 | 2 | 0.14 | 72.60 | 0.26 | 28.2 | 0.026 |
| balanced (same as low_latency) | 1280x720@30 | 7 | 0.78 | 13.00 | 2.69 | 87.1 | 0.269 |
| quality | 1280x720@60 | all | 1.38 | 7.30 | 5.22 | 88.9 | 0.522 |
| competitive | 1280x720@60 | 6 | 1.58 | 6.36 | 4.97 | 84.7 | 0.497 |

Speed above 1x means the encoder finished faster than real time on this 8-core CPU, so these runs show how much headroom exists here, not whether a weak laptop could keep up.

## Results: Gaming First proxy (balanced geometry, 1280x720@30)

| Threads | Wall (s) | ffmpeg speed (x) | Child CPU (s) | Peak RSS (MiB) | CPU s per stream s |
|---|---|---|---|---|---|
| uncapped | 0.75 | 13.40 | 2.82 | 89.2 | 0.282 |
| 2 threads | 1.18 | 8.55 | 2.02 | 76.4 | 0.202 |
| 7 threads | 0.77 | 13.10 | 2.72 | 87.1 | 0.272 |
| 6 threads | 0.85 | 11.90 | 2.63 | 84.9 | 0.263 |

What this does show: capping encoder threads leaves cores free (the thread count is the cap) and lowers peak memory a little, and with 2 threads the encode ran slower (lower speed) while using less total CPU. What it does not show: any change in game frame rate. That needs a real game on real hardware and is UNVERIFIED.

## v0.11.0 before and after

Method: the same `lightstream bench` command (without `--compare-src`), run once on the tree before the v0.11 changes ("before", reported as version 0.9.0, because the version string was not yet bumped) and once on the v0.11.0 tree ("after"), on the same Linux sandbox (8 cores, 31560 MB, Python 3.11.15, no GPU). Both runs used `--seconds 10`. Only the "after" run used `--import-runs 21`; the "before" run was taken earlier in the session and I did not record its run count, so its median is less certain. Each number is a single run. Competitor numbers stay UNKNOWN.

```
HOME=<writable dir> XDG_CONFIG_HOME=<writable dir> PYTHONPATH=src python3 -m lightstream bench \
  --ffmpeg <static ffmpeg 7.0.2> --seconds 10 --import-runs 21 --out bench-after.json
```

| Metric | Before | After | Reading |
|---|---|---|---|
| `import lightstream.cli` median (ms) | 79.8 | 73.5 | Within run to run noise; no regression shown. The before run was taken at a different time and may have had a busier machine |
| Bare interpreter median (ms) | 11.3 | 10.7 | Noise |
| RSS after import (MiB) | 22.1 | 22.0 | Same |
| RSS bare interpreter (MiB) | 9.6 | 9.8 | Same |
| RSS before to after 1000 ticks (MiB) | 21.6 to 21.8 | 21.74 to 21.74 | No growth at this resolution |
| `parse_progress` (us per call) | 2.4 | 2.13 | Noise |
| `HealthTracker.update` (us) | 0.75 | 0.78 | Noise |
| `AdaptiveAdvisor.observe` (us) | 0.61 | 0.62 | Noise |
| `TelemetrySampler.tick` (us) | 115.0 | 107.6 | Noise |
| `build_insights` (us) | 52.3 | 49.6 | Noise |
| `AutoScaler.update` (us) | 1.39 | 1.42 | Noise |

Encode (libx264, synthetic 10 s):

| Profile | Before speed (x) | After speed (x) | Before CPU s per stream s | After CPU s per stream s | Before peak RSS (MiB) | After peak RSS (MiB) |
|---|---|---|---|---|---|---|
| potato 640x360@24 | 54.4 | 65.6 | 0.035 | 0.028 | 27.2 | 27.2 |
| balanced 1280x720@30 | 11.6 | 12.8 | 0.299 | 0.276 | 86.0 | 86.0 |
| quality 1280x720@60 | 6.35 | 7.22 | 0.578 | 0.525 | 87.9 | 87.9 |
| competitive 1280x720@60 | 6.02 | 6.24 | 0.534 | 0.506 | 83.6 | 83.6 |

The v0.11 changes do not touch the encode path for these profiles, so the speed differences are machine noise, not a speedup. The same potato profile ran at 62.9x in another before run, which shows the spread. Conclusion: the new emergency, weak connection, failover, theme and graph code did not measurably change startup, memory or per-tick cost on this machine. That says nothing about low-end laptops, hardware encoders, Windows or macOS (UNVERIFIED). Raw JSON files are not committed.

### Web page weight

Method: `python3 tools/page_weight.py` sums the size of every served file under `web/` (excluding `web/test` and `package.json`) and its gzip -9 size. It measures file bytes only, not headers, transfer overhead, or load time. "Before" is the tree at the start of v0.11 work.

| File | Before bytes | After bytes | Before gzip | After gzip |
|---|---|---|---|---|
| index.html | 14003 | 14296 | 4576 | 4671 |
| style.css | 4021 | 5408 | 1552 | 1973 |
| js/app.js | 2716 | 3067 | 1180 | 1342 |
| js/sw-logic.js | (new) | 1478 | (new) | 703 |
| sw.js | (new) | 1522 | (new) | 613 |
| companion/companion.css | 641 | 759 | 377 | 437 |
| companion/index.html | 775 | 834 | 402 | 418 |
| vercel.json | 1537 | 1774 | 400 | 435 |
| All files | 48811 | 54256 | 18085 | 20190 |

The accessibility, light color scheme and offline shell added about 5.4 KB raw (about 2.1 KB gzip), a 11 percent increase. The service worker, caching and page behavior in a real browser are UNVERIFIED here (headless Chromium does not run in this sandbox); only the pure cache rules and the static HTML and CSS checks are tested in node.

## Hardware encoders

None listed by ffmpeg in this sandbox (`hardware_encoders.listed_by_ffmpeg` is empty in the JSON), so there are no NVENC, Quick Sync, AMF, VideoToolbox or VAAPI numbers. Use `lightstream bench` on the target PC to get them; encoders that fail a test encode are skipped.

## Reproduce

Run the command above on your own machine without `--compare-src`. The report is written to `reports/bench-<date>.json` next to your config (or `--out`). It holds numbers and labels only: no stream key, no URL, no file paths. To compare with an older version, check it out in a separate folder and pass its `src` folder as `--compare-src`.

## Readiness score

`lightstream readiness` is not a benchmark. It adds points for ffmpeg present (25), a working encoder (20 hardware, 12 software), memory (15), CPU cores (15), upload speed (15, optional) and TCP connect time to the ingest host (10, optional, only with `--platform` or `--url`). Factors that were not measured are left out of the score. The tiers are design choices, UNVERIFIED against real streaming outcomes. The same score is printed at the end of `lightstream setup` and shown after the window's one-click setup.
