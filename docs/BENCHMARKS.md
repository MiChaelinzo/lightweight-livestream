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

## Hardware encoders

None listed by ffmpeg in this sandbox (`hardware_encoders.listed_by_ffmpeg` is empty in the JSON), so there are no NVENC, Quick Sync, AMF, VideoToolbox or VAAPI numbers. Use `lightstream bench` on the target PC to get them; encoders that fail a test encode are skipped.

## Reproduce

Run the command above on your own machine without `--compare-src`. The report is written to `reports/bench-<date>.json` next to your config (or `--out`). It holds numbers and labels only: no stream key, no URL, no file paths. To compare with an older version, check it out in a separate folder and pass its `src` folder as `--compare-src`.

## Readiness score

`lightstream readiness` is not a benchmark. It adds points for ffmpeg present (25), a working encoder (20 hardware, 12 software), memory (15), CPU cores (15), upload speed (15, optional) and TCP connect time to the ingest host (10, optional, only with `--platform` or `--url`). Factors that were not measured are left out of the score. The tiers are design choices, UNVERIFIED against real streaming outcomes. The same score is printed at the end of `lightstream setup` and shown after the window's one-click setup.
