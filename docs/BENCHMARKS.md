# Benchmarks

Status: VERIFIED for the method and for the numbers below on the one machine named here. UNVERIFIED for every other machine, for hardware encoders, for Windows and macOS, and for any real game or live stream.

## v0.15 sections index

Measured in the same sandbox, nothing invented: [GUI animation tick](#v015-gui-animation-tick-health-card-easing), [audio chain CPU cost](#v015-audio-chain-cpu-cost-spike-e), [highlights analysis](#v015-highlights-analysis), [Benchmark Lab harness check](#v015-benchmark-lab-harness-check). OBS Studio and Streamlabs Desktop numbers are UNKNOWN.

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

## v0.12 spikes: split publisher, tee recording, potato filters, SRT

Status: VERIFIED for the numbers below on this one sandbox (8 cores, Python 3.11.15, static ffmpeg 7.0.2, no GPU, sandbox clock 2026-11-24). Every connection went to an ffmpeg listener on 127.0.0.1. No real platform (Twitch, YouTube, Kick) was contacted, so platform behavior is UNVERIFIED throughout.

```
LIGHTSTREAM_TEST_FFMPEG=<static ffmpeg 7.0.2> python3 tools/spikes.py --all --repeats 3 --out spikes.json
python3 tools/spikes.py --spike b      # one spike at a time: a, b, c, d or e
```

Method common to all spikes: `tools/spikes.py` starts ffmpeg children, reads CPU (user plus system) and peak RSS from `os.wait4` (psutil is not used), and checks received or recorded streams by re-reading them with ffmpeg `-f framecrc` (ffprobe is not in this build). Timestamp continuity means: every video dts is greater than the one before (`non_monotonic` = 0), and forward jumps of 500 ms or more are listed. The JSON is printed to stdout; raw JSON files are not committed. Sample counts are given per table. Spike B was run a second time after the `onfail=abort` row was added; all other tables come from the `--all` run.

### A: split publisher (encoder -> MPEG-TS over UDP -> `-c copy` publisher -> RTMP)

Setup: encoder `testsrc2` with `-re` (real time), libx264 ultrafast zerolatency, 1 s GOP, MPEG-TS to `udp://127.0.0.1` (pkt_size 1316). Publisher: `-f mpegts -i udp://...?fifo_size=1000000&overrun_nonfatal=1 -c copy -f flv rtmp://127.0.0.1/...`, `-analyzeduration 1000000 -probesize 200000`. Receiver: `ffmpeg -listen 1 -i rtmp://...` writing framecrc and an MPEG-TS copy. The first encoder ran 5 s, was killed with SIGKILL, the gap followed, a second encoder ran 5 s. One run per scenario.

| Scenario | RTMP session alive after kill / at end | Frames received (about 300 sent) | dts non-monotonic | Forward gaps >= 500 ms | Received span | Decoded resolutions |
|---|---|---|---|---|---|---|
| same 640x360 1000k, gap 1 s | yes / yes | 268 | 0 | none | 8.9 s | 268 at 640x360 |
| same 640x360 1000k, gap 5 s | yes / yes | 268 | 0 | none | 8.9 s | 268 at 640x360 |
| 640x360 1000k then 960x540 1500k, gap 1 s | yes / yes | 268 | 0 | none | 8.9 s | 105 at 640x360, 163 at 960x540, 0 decode errors |

Readings:

- The publisher and the RTMP connection survived the encoder being killed and a 5 s silence. The publisher logged `DTS ... out of order` and `timestamp discontinuity ... new offset`, i.e. ffmpeg's MPEG-TS demuxer shifted the second encoder's timestamps to follow the first. The received timeline has **no gap**: the 1 s and 5 s silences were both collapsed. A platform would see data stop and resume with continuous timestamps; whether Twitch or YouTube accept this, or a 5 s silence, is UNVERIFIED.
- About 30 of 300 frames were not received in each run. The per-resolution count of scenario 3 shows the first segment lost most of them (105 of about 150), which fits the publisher's probe at start plus frames in flight at the kill. This was not broken down further.
- A resolution change inside one FLV stream decoded without errors in ffmpeg. Platform transcoders and players were not tested (UNVERIFIED).

Extra cost of the second process (1280x720@30, 2000k, 10 s paced with `-re`, n = 3, medians with min to max):

| Layout | Encoder CPU (s) | Encoder peak RSS (MiB) | Publisher CPU (s) | Publisher peak RSS (MiB) |
|---|---|---|---|---|
| direct, encoder -> RTMP | 1.128 (1.117 to 1.173) | 49.3 (49.2 to 49.3) | n/a | n/a |
| split, encoder -> UDP TS -> publisher -> RTMP | 1.068 (1.028 to 1.099) | 49.2 (49.2 to 49.2) | 0.105 (0.101 to 0.106) | 19.1 (19.1 to 19.1) |

The publisher used about 0.105 CPU seconds per 10 s, roughly 1 percent of one core here, and 19.1 MiB. The encoder cost did not change measurably. On a slow laptop CPU the percentage will be higher (UNVERIFIED).

### B: tee, killed RTMP server, containers after kill -9, numbered files

Setup: 640x360@30, 1000k, `-re`, video only, `-map 0:v -flush_packets 1 -flags +global_header -f tee "[f=flv...]rtmp://127.0.0.1/...|[f=matroska]rec.mkv"`, 10 s, receiver killed with SIGKILL after 4 s. One run per row.

| flv slot option | ffmpeg exit | Exit after server kill | Recording |
|---|---|---|---|
| `onfail=ignore` | 0 | 5.52 s (at the end of `-t 10`) | 300 frames, 9.97 s, 0 decode errors |
| `onfail=abort` | 224 | 0.0 s | 136 frames, 4.5 s, 0 decode errors |
| none | 0 | 5.52 s | 300 frames, 9.97 s, 0 decode errors |
| none, matroska `onfail=ignore` (LightStream's current spec) | 0 | 5.52 s | 300 frames, 9.97 s, 0 decode errors |

Readings:

- With ffmpeg 7.0.2, a tee slave **without** an `onfail` option did not abort when its RTMP server died. ffmpeg logged `Slave muxer #0 failed: Broken pipe, continuing with 1/2 slaves` and kept running. LightStream's reconnect loop waits for ffmpeg to exit, so with today's tee spec a dropped stream would not reconnect while the recording carries on. Only an explicit `onfail=abort` made ffmpeg exit at once. Two separate runs of the "none" case gave the same result.
- Without `-flags +global_header` the matroska slave failed to write its header (`error writing header: Invalid data found when processing input`), left a 291 byte file, and `onfail=ignore` hid the failure while ffmpeg exited 0. With the flag: 147854 bytes for 2 s of 320x180.
- A tee output with no `-map` fails to open: `Output file does not contain any stream`, exit 234.
- The argv that `command.build_command` produces today for a stream with `record_to` (no scene), with only the x11grab and pulse inputs swapped for lavfi sources, failed the same way: exit 234, 0 RTMP packets, no recording file. Recording while streaming without a scene is therefore broken with ffmpeg 7.0.2 (scene streams add `-map` but would still hit the missing global header). Not fixed in this spike; FEAT-003 fixes it.

Containers after SIGKILL (encoder killed 5 s into an 8 s run, 640x360@30 1000k, one run per row):

| Container | No `-flush_packets` | With `-flush_packets 1` |
|---|---|---|
| Matroska | readable, 110 frames (3.63 s), 1 warning `File ended prematurely` | readable, 150 frames (4.97 s), 0 errors |
| MP4 | unreadable, `moov atom not found` | unreadable, `moov atom not found` |
| fragmented MP4 (`frag_keyframe+empty_moov`) | readable, 110 packets, 109 frames decoded, 4 error lines (`partial file`) | readable, 150 frames (4.97 s), 0 errors |

Numbered files across a reconnect: attempt 1 wrote `b-reconnect.mkv` and was killed with SIGKILL after 3 s (readable, 53 frames covering 1.73 s of the 3 s run, warning `File ended prematurely`; the startup time of ffmpeg and the RTMP handshake account for part of the difference, not measured separately). Attempt 2 used `numbered_recording_path`, wrote `b-reconnect-2.mkv` (120 frames, 3.97 s, 0 errors), and the first file was still present.

### C: potato filters and x264 rate control

Setup: `-t 10 -f lavfi -i <source>=size=1280x720:rate=30`, not paced (as fast as possible), no audio, libx264 ultrafast zerolatency, `-bf 0 -g 30`, 4 threads unless the row sets threads, CRF 28 unless the row says CBR, MPEG-TS file output. Bitrate is file size over 10 s (includes MPEG-TS overhead). The source generator and filters are inside the CPU time. n = 3 per row; CPU is the median with min to max; kbps varied by under 0.1 percent between runs.

| Config | testsrc2 (moving) CPU s | testsrc2 kbps | smptebars (static) CPU s | smptebars kbps |
|---|---|---|---|---|
| baseline | 1.108 (1.093 to 1.125) | 5834.9 | 0.575 (0.572 to 0.587) | 111.7 |
| `format=gray` (yuv400 encode) | 1.340 (1.298 to 1.344) | 3786.5 | 0.942 (0.921 to 0.951) | 101.2 |
| `format=gray,format=yuv420p` | 2.017 (2.005 to 2.030) | 3594.1 | 1.506 (1.499 to 1.520) | 105.6 |
| `fps=15` | 0.646 (0.628 to 0.663) | 3449.6 | 0.299 (0.298 to 0.305) | 66.2 |
| `fps=10` | 0.471 (0.459 to 0.482) | 2480.1 | 0.210 (0.200 to 0.213) | 62.9 |
| `mpdecimate` (`-fps_mode vfr`) | 1.047 (1.033 to 1.057) | 5834.9 | 0.137 (0.136 to 0.144) | 4.2 |
| scale 640x360 | 0.768 (0.752 to 0.777) | 1165.3 | 0.464 (0.449 to 0.467) | 108.7 |
| scale 480x270 | 0.627 (0.620 to 0.643) | 788.5 | 0.407 (0.404 to 0.419) | 109.5 |
| scale 640x360 + fps=15 | 0.579 (0.577 to 0.585) | 800.6 | 0.366 (0.365 to 0.383) | 65.4 |
| scale 480x270 + fps=10 + gray to yuv420p | 0.535 (0.522 to 0.566) | 251.0 | 0.337 (0.330 to 0.346) | 56.4 |
| threads 1 | 0.835 (0.833 to 0.852) | 5751.4 | 0.405 (0.402 to 0.410) | 108.4 |
| threads 2 | 0.951 (0.941 to 0.959) | 5805.7 | 0.472 (0.467 to 0.481) | 109.9 |
| threads 4 | 1.093 (1.052 to 1.104) | 5834.9 | 0.577 (0.569 to 0.599) | 111.7 |
| CBR 2000k (`nal-hrd=cbr`) | 1.081 (1.052 to 1.092) | 2185.5 | 0.628 (0.624 to 0.646) | 2088.2 |
| CBR 4000k (`nal-hrd=cbr`) | 1.085 (1.085 to 1.127) | 4308.2 | 0.658 (0.656 to 0.684) | 4098.4 |

Readings:

- Grayscale does **not** reduce CPU here: +21 percent (yuv400) and +82 percent (gray then yuv420p) on testsrc2, +64 and +162 percent on smptebars. It lowered CRF bitrate on the moving source only (5835 to 3787 kbps).
- Frame rate and size are what cut CPU: `fps=10` -57 percent, `fps=15` -42 percent, 640x360 -31 percent, 640x360 at 15 fps -48 percent against baseline on testsrc2.
- `mpdecimate` did nothing on a source where every frame changes and cut CPU by 76 percent and bitrate to 4.2 kbps on a static picture. Its output has a variable frame rate; how platforms handle that is UNVERIFIED: `-fps_mode vfr` into FLV/RTMP was only tested against loopback listeners, never a real ingest.
- Fewer threads used less total CPU but took longer (wall median 0.65 s with 1 thread, 0.42 s with 4). Whether 1 thread keeps up in real time on a weak CPU is UNVERIFIED.
- CBR padded the static source up to the target (2088 and 4098 kbps for a picture CRF encodes at 112 kbps). CPU was close to the CRF baseline.

### D: SRT on loopback

Setup: listener `ffmpeg -i "srt://127.0.0.1:P?mode=listener&latency=L"`, caller sends 6 s of 640x360@30 MPEG-TS with `-re`. One run per row.

| latency option | Sender exit | Sender CPU (s) | Packets received (about 180 sent) | non-monotonic |
|---|---|---|---|---|
| 120000 us (120 ms) | 0 | 0.280 | 178 | 0 |
| 500000 us (500 ms) | 0 | 0.301 | 167 | 0 |

A caller with no listener failed after 3.04 s (`connect_timeout` default 3000 ms), exit 251. The lower count at 500 ms was not investigated (one run; likely the listener stopping before the receive buffer drained, not loss). Not measured: packet loss and retransmission (ARQ) behavior, because loopback has no loss and no `tc netem` was used. libsrt options in this build include `latency`, `rcvlatency`, `peerlatency`, `tlpktdrop`, `nakreport`, `maxbw`, `oheadbw`, `inputbw`, `passphrase`, `pbkeylen`, `enforced_encryption`, `streamid`, `connect_timeout`, `mode`, `transtype`, `payload_size`, `pkt_size`, `lossmaxttl` and others (full list in the JSON).

## v0.12.0 against v0.11.0

Method: the same command as the v0.11 section, `lightstream bench --seconds 10 --import-runs 21` with static ffmpeg 7.0.2, run once on the 0.12.0 tree (same Linux x86_64 VM, 8 threads). The "0.11.0" column is the "After" column of the v0.11 section above, taken on an earlier day, so machine noise applies. One run each, no repeats.

| Metric | 0.11.0 | 0.12.0 | Reading |
|---|---|---|---|
| `import lightstream.cli` median (ms) | 73.5 | 63.8 | Bare interpreter was 10.7 vs 9.1 ms, so the machine was faster in this run; no regression shown |
| RSS after import (MiB) | 22.0 | 22.5 | Within noise; about 0.4 MiB more is plausible from new modules but was not isolated |
| RSS before to after 1000 ticks (MiB) | 21.74 to 21.74 | 21.66 to 21.92 | Growth of 0.26 MiB, not investigated, single run |
| `TelemetrySampler.tick` (us) | 107.6 | 94.6 | Noise |
| `build_insights` (us) | 49.6 | 44.3 | Noise |
| `AutoScaler.update` (us) | 1.42 | 1.20 | Noise |

| Profile | 0.11.0 speed (x) | 0.12.0 speed (x) | 0.11.0 CPU s per stream s | 0.12.0 CPU s per stream s | 0.12.0 peak RSS (MiB) |
|---|---|---|---|---|---|
| potato 640x360@24 | 65.6 | 75.1 | 0.028 | 0.025 | 27.3 |
| balanced 1280x720@30 | 12.8 | 14.2 | 0.276 | 0.244 | 86.2 |
| quality 1280x720@60 | 7.22 | 7.97 | 0.525 | 0.473 | 88.0 |
| competitive 1280x720@60 | 6.24 | 7.06 | 0.506 | 0.442 | 83.8 |
| potato_2000 640x360@15 (new) | n/a | 94.8 | n/a | 0.015 | 27.2 |
| potato_4000 854x480@15 (new) | n/a | 64.0 | n/a | 0.027 | 39.2 |

The 0.12 changes do not touch the encode settings of the four existing profiles, so the speed differences are machine noise, not a speedup. The two new Potato Stream profiles are cheaper per stream second than `potato` (0.015 and 0.027 vs 0.025) on this machine; behavior on a weak CPU is UNVERIFIED. Web page weight: 54256 to 55632 bytes (20190 to 20588 gzip), from the glass cards and the service worker fingerprint (`tools/page_weight.py`). Competitor numbers are UNKNOWN.

## Benchmark tier (v0.12)

`lightstream bench` now prints and stores a `tier`. A machine earns the highest tier whose three minimums it meets: CPU threads, RAM (MiB) and the ffmpeg speed (times real time) of the uncapped software `balanced` encode. Boundaries are inclusive. A metric that could not be measured is not checked and is listed under `skipped_metrics`, and the tier is marked `partial`: it is then an upper bound, not a measured result (for example 8 threads and 16 GiB with no ffmpeg gives Creator). `lightstream optimize` shows no tier when ffmpeg is missing. Low-End has no minimum. These thresholds are heuristics chosen for this project, not an industry standard; they only rank results from this harness.

| Tier | CPU threads | RAM MiB | Speed |
|---|---|---|---|
| Low-End | any | any | any |
| Balanced | 4 | 4096 | 2.0x |
| Performance | 6 | 8192 | 4.0x |
| Creator | 8 | 16384 | 6.0x |
| Power User | 12 | 32768 | 10.0x |

Real run (VERIFIED on this machine only): `lightstream bench --ffmpeg ffmpeg-7.0.2-static`, 10 stream-seconds per encode, Linux x86_64 cloud sandbox, Intel Xeon Platinum 8488C (model string from `/proc/cpuinfo`), 8 threads, 31560 MiB RAM, Python 3.11. Uncapped software balanced encode ran at 14.4x real time, 0.26 CPU-seconds per stream-second. Result: tier **Creator** (stopped there because 8 threads is below the 12 needed for Power User). This is a shared virtual machine, a single run, no game running, and says nothing about a real laptop. The raw JSON is written to `reports/bench-DATE.json` and not committed.

## v0.13.0 against v0.12.0 (polish release)

Method: `python -c "import lightstream.cli"` and `python -c "import lightstream.gui"` in a fresh interpreter, wall time via `time.perf_counter` around `subprocess.run`, median of 21 runs after one warm-up run (so `.pyc` files exist), next to `python -c pass`. RSS is `VmRSS` from `/proc/self/status` read after the import in a separate child. Before is commit `0969294` (checked out as a temporary git worktree, removed afterwards), after is the 0.13.0 tree. The whole comparison was run twice, alternating base and head. Same Linux x86_64 VM, tkinter available, no display needed for the import. These numbers are about the cost of importing the code; they do not measure a running window.

| Metric | Before run 1 | After run 1 | Before run 2 | After run 2 |
|---|---|---|---|---|
| bare interpreter median (ms) | 10.3 | 10.3 | 10.4 | 10.5 |
| `import lightstream.cli` median (ms) | 74.3 | 73.9 | 74.7 | 74.8 |
| `import lightstream.gui` median (ms) | 85.6 | 86.3 | 87.2 | 87.0 |
| RSS after `import lightstream.cli` (MiB) | 22.68 | 22.44 | 22.43 | 22.26 |
| RSS after `import lightstream.gui` (MiB) | 27.48 | 27.60 | 27.64 | 27.65 |

Reading: no measurable change in import time or memory. The differences between runs (up to 1.6 ms, 0.25 MiB) are as large as the differences between trees, so the GUI polish costs nothing at import that this method can see. Window creation time and memory of a running GUI were not measured.

A first attempt used `PYTHONDONTWRITEBYTECODE=1` with no warm-up, which made the base tree look 40 ms slower on `import lightstream.cli` (about 112 ms against 75 ms) only because it had no cached `.pyc` files while the head tree did. That run is discarded as a method error; the table above is the fair comparison.

Web page weight (`tools/page_weight.py`):

| Item | Before (0.12.0) | After (0.13.0) |
|---|---|---|
| Text assets, bytes | 55,632 | 55,265 |
| Text assets, gzip bytes | 20,588 | 20,655 |
| Images, bytes | none (no files in `web/img/`) | 84,984 (three `.webp` files in `web/img/`) |

The text assets are 367 bytes smaller raw and 67 bytes larger gzipped. The three real GUI screenshots add 84,984 bytes, loaded lazily. Before, `web/img/` did not exist. Load time was not measured.

## v0.15 GUI animation tick (health card easing)

Method: `StreamWindow` under Xvfb at 1366x768, dashboard page open, 2000 calls of `_animate_cards()` each followed by `root.update()`, with the three eased targets changed every call so every label repaints. CPU time from `time.process_time()`, three runs, Linux sandbox (Python 3.11). A real Windows or macOS desktop was not measured: UNVERIFIED there.

| Case | CPU time per tick |
|---|---|
| tick + repaint of 3 labels (worst case, always moving) | 0.72 to 0.74 ms |
| `root.update()` alone | 0.06 ms |

At the 50 ms tick that is about 1.5 percent of one core while values are moving, and zero when settled or when Reduce motion is on (no tick is scheduled). The sandbox has no GPU and Xvfb draws in software, so this is a rough upper bound for the Tk side only. PARTIALLY VERIFIED.

## v0.15 audio chain CPU cost (spike E)

Status: VERIFIED for these numbers on this one sandbox (8 cores, Python 3.11.15, static ffmpeg 7.0.2, no GPU, sandbox clock 2026-11-24). Real microphones, real voices and other CPUs are UNVERIFIED.

Method: `python3 tools/spikes.py --spike e --repeats 5 --ffmpeg <static ffmpeg 7.0.2>`. Each audio profile chain (`light` and `full`, from `audio_profile_chain`, including the new `teaching` and `meeting` profiles) is run over 120 seconds of synthetic audio (a 440 Hz sine mixed with white noise of amplitude 0.05, 48000 Hz, generated by lavfi) as fast as ffmpeg can, to the null muxer. CPU is user plus system time from `os.wait4`, five runs per row. The baseline row has no filter, so it is the cost of generating, mixing and discarding the audio. "Share of one core at real time" is median CPU seconds divided by the 120 audio seconds: what a live stream would need for that chain on this machine, before video.

| Chain | CPU seconds, median (min to max), n=5 | Wall seconds, median | Share of one core at real time |
|---|---|---|---|
| baseline (no filter) | 0.246 (0.239 to 0.257) | 0.10 | 0.21% |
| gaming/light | 0.348 (0.335 to 0.368) | 0.14 | 0.29% |
| gaming/full | 0.950 (0.932 to 0.961) | 0.62 | 0.79% |
| podcast/light | 0.541 (0.538 to 0.563) | 0.30 | 0.45% |
| podcast/full | 1.163 (1.149 to 1.166) | 0.83 | 0.97% |
| music/light | 0.295 (0.289 to 0.308) | 0.10 | 0.25% |
| music/full | 0.384 (0.366 to 0.420) | 0.16 | 0.32% |
| commentary/light | 0.550 (0.542 to 0.560) | 0.30 | 0.46% |
| commentary/full | 1.152 (1.146 to 1.162) | 0.83 | 0.96% |
| asmr/light | 0.861 (0.855 to 0.876) | 0.54 | 0.72% |
| asmr/full | 0.952 (0.941 to 0.968) | 0.62 | 0.79% |
| teaching/light | 0.221 (0.207 to 0.235) | 0.10 | 0.18% |
| teaching/full | 1.131 (1.100 to 1.153) | 0.81 | 0.94% |
| meeting/light | 0.674 (0.668 to 0.705) | 0.50 | 0.56% |
| meeting/full | 0.839 (0.827 to 0.851) | 0.67 | 0.70% |

Reading the numbers: every chain costs under 1 percent of one core at real time on this machine. Chains with the FFT denoiser `afftdn` and a compressor (the `full` chains of gaming, podcast, commentary, teaching) measured about 0.8 to 1.0 percent, against 0.2 to 0.5 percent for their light chains. `music/full` has no denoiser and measured 0.32 percent. `teaching/light` measured below the no-filter baseline in two separate runs (0.221 s here); the cause was not investigated, so do not read differences among the cheap rows as real. A synthetic sine plus noise is not speech, and these numbers say nothing about video encoding cost, which is far larger (see the potato filter tables above).

## v0.14.0 (showcase release)

Web page weight with `python3 tools/page_weight.py` (sums bytes and gzip level 9 bytes of the text assets in `web/`, and image bytes separately), run before and after the hero change:

| Item | Before (0.13.0) | After (0.14.0) |
|---|---|---|
| Text assets, bytes | 55,265 | 55,450 |
| Text assets, gzip bytes | 20,655 | 20,728 |
| Images, bytes | 84,984 | 84,984 |

The hero gained a one-line pitch, Download and Try presets buttons and a verification badge: 185 bytes raw, 73 bytes gzipped. Load time was not measured.

Demo GIF or WebM: not added. A screen capture of the window would exceed the 150 KB budget set for this release at any useful size, and the three real screenshots already show the app. Decision: skip.

Rendering check: the web page was rendered in headless Chromium at 1280 and 390 px and read by eye. The Recording page of the Tk window was rendered under Xvfb in light and dark at 1280x720 with the persistent-ingest checkbox and its caption visible and unclipped (PARTIALLY VERIFIED, Linux fonts). One 1280 px capture showed the first lazy screenshot still blank, which is a capture timing artifact of the tool; at 390 px all three loaded.

## v0.15 highlights analysis

Method: a synthetic 300 s 1280x720 30 fps H.264 file (`testsrc2` video with `-preset ultrafast -g 60`, plus a 440 Hz sine in AAC; 285,831,035 bytes, which is a much higher bitrate than a typical recording) was analysed with `highlights.analyze_file` three times on this 8-core machine, ffmpeg 7.0.2 static. Wall time is `time.perf_counter()`; CPU time is user plus system from `resource.getrusage(RUSAGE_CHILDREN)` before and after. A plain decode (`-f null -`) of the same file was measured once as a baseline.

| Run | Wall (s) | CPU (s) |
|---|---|---|
| analysis 1 | 2.87 | 18.15 |
| analysis 2 | 2.89 | 18.31 |
| analysis 3 | 2.86 | 18.08 |
| decode only (1 run) | 2.46 | 14.93 |

Reading the numbers: analysing 300 s of this file took about 2.9 s wall, roughly 100 times faster than real time, and about 18.2 s of CPU summed over ffmpeg's threads (CPU exceeds wall because decoding is multithreaded). About 14.9 s of that is decoding, so the scoring filters add about 3.2 CPU seconds per 300 s. This file is a high-bitrate synthetic one, so decode cost dominates and real recordings will differ; sine audio is not speech. Clip cutting was not timed: `-c copy` does not decode, and vertical re-encoding cost depends on the machine and was not measured.

## v0.15 Benchmark Lab harness check

Method: `tools/benchlab.py --command ... --duration 10 --interval 1` on this 8-core Linux sandbox, one target per run, ffmpeg 7.0.2 static. These check that the harness works on this repository's own tools. They are not a comparison with any other product, and no OBS or Streamlabs run was possible here (those columns are UNKNOWN).

| Target | Startup (s) | CPU avg (% of one core) | CPU max | RSS avg (MB) | RSS peak (MB) |
|---|---|---|---|---|---|
| idle Python process (`time.sleep`), ready text `ready` | 0.009 | 0.0 | 0.0 | 7.67 | 8.23 |
| ffmpeg `testsrc` 1280x720 30 fps, libx264 ultrafast 4500k, `-f null`, ready text `frame=` | 0.506 | 508.21 | 512.83 | 170.6 | 187.26 |

Reading the numbers: the ffmpeg run is not real time; it encodes as fast as it can, so it uses several cores and the CPU figure is not what a live 30 fps stream costs. One run each, no repeats, so run-to-run spread is unknown. Startup here means time to the first output containing the ready text, not time to a usable window.

## v0.16 evidence (idle budgets, runtime bitrate change, overlay cost)

Status: VERIFIED for these numbers on this one sandbox (8 cores, Python 3.11.15, static ffmpeg 7.0.2 from johnvansickle.com, no GPU, Xvfb 1280x800x24, sandbox clock 2026-11-25). Real desktops, real GPUs, Windows and macOS are UNVERIFIED. Nothing here compares against OBS Studio or Streamlabs Desktop; those stay UNKNOWN.

### Idle budgets of the GUI window

Method: `DISPLAY=:97 python3 tools/idle_budget.py --duration 20` (Xvfb started by hand, see `docs/DEV-RENDERING.md`). The tool starts a child Python that builds `StreamWindow` on the display with a throw-away HOME, draws it once (`root.update()`), and prints a marker. `startup_s` is the wall time from launch to that marker (it includes interpreter start and imports). After a 2 s settle, `/proc/PID/stat` and `/proc/PID/status` are sampled once a second for 20 s with the `tools/benchlab.py` code. Idle CPU is the mean over the 20 s (100 is one full core). Only the GUI process itself is sampled; no stream was running.

| Run | startup_s | rss_mb (end) | idle CPU mean | idle CPU max of 1 s samples |
|---|---|---|---|---|
| 1 | 0.146 | 37.66 | 0.30% | 2.0% |
| 2 | 0.146 | 37.54 | 0.25% | 1.0% |
| 3 | 0.149 | 37.88 | 0.30% | 2.0% |

Budgets enforced by `tests/test_idle_budget.py` (skipped without DISPLAY): startup under 2 s, RSS under 150 MB, idle CPU under 5%. Measured values are far inside them. CPU values come from 1/100 s clock ticks, so a 1 s sample can only be 0, 1, 2 percent and so on; do not read the means as more precise than about 0.1 point. The earlier figure of about 87 ms and 27.6 MiB for importing the GUI module is a different quantity (import only, no window) and is not comparable.

CLI import: `python -c "import lightstream.cli"` with `PYTHONPATH=src`, 21 fresh interpreters, wall time median 74.0 ms (min 72.6, max 78.7), against 10.3 ms for `python -c pass` (min 9.6, max 10.8).

### Runtime bitrate change (spike F)

Method: `python3 tools/spikes.py --spike f`. A synthetic 640x360@30 stream is encoded for 8 s at `-b:v 3000k`. At 4 s a `sendcmd` line tries to set 500 kbit/s on the encoder (`<encoder> b_v 500000` and `<encoder> bit_rate 500000`). The output (Matroska) is read back with `-f framecrc` and the packet bytes before and after 4 s are converted to kbit/s. One run per row. A control run puts a `hue=s=1` filter in the graph and sends `4 hue s 0;`.

Findings:

- This ffmpeg build has `sendcmd` and `asendcmd`. It has no `zmq` or `azmq` filter (filters present: zmq false, azmq false).
- `sendcmd` reaches filters. Control: `hue` saturation to 0 at 4 s lowered the bitrate from 3146.8 to 2034.9 kbit/s (ratio 0.647), against 3146.8 to 3090.8 (0.982) with no command.
- `sendcmd` does not reach any encoder. For libx264, libx265, libvpx, libvpx-vp9 and libaom-av1, a command aimed at the encoder name gave exit code 0, no message and a bitrate identical to the run without a command. Aimed output stays at about the start rate:

| Encoder | kbit/s before 4 s, no command | after 4 s, no command | after 4 s, command to encoder |
|---|---|---|---|
| libx264 | 3146.8 | 3090.8 | 3090.8 |
| libx265 | 2681.8 | 3033.6 | 3033.6 |
| libvpx | 2664.7 | 2827.8 | 2825.0 |
| libvpx-vp9 | 2030.9 | 2004.5 | 2004.5 |
| libaom-av1 | 2541.7 | 3010.7 | 3010.7 |

  The command is silently ignored, so a bitrate change that must work cannot rely on it. Differences between before and after without a command are rate control warming up on a synthetic picture, not a setting change.
- Hardware encoders: the build lists only `*_v4l2m2m` wrappers (h263, h264, hevc, mpeg4, vp8), which need a Video4Linux device that this sandbox does not have. NVENC, QSV, AMF, VAAPI and VideoToolbox are not in this build. Whether any hardware encoder accepts a live bitrate change through ffmpeg is UNVERIFIED.
- Conclusion: for software encoders, no live bitrate change through ffmpeg commands. The restart path (`run_with_reconnect(restart=event)`, see `docs/ARCHITECTURE-NOTES.md`) stays the only supported way to change encoder bitrate.

### Overlay cost at 720p30 (spike G)

Method: `python3 tools/spikes.py --spike g --repeats 5`. Synthetic 1280x720@30 `testsrc2`, 10 s of stream time, libx264 ultrafast zerolatency, 4 threads, no audio, as fast as the CPU allows, MPEG-TS to a file. CPU is user plus system time from `os.wait4` of the ffmpeg child, 5 runs per row. The overlay PNG (400x80) is generated by ffmpeg at run time.

| Config | CPU seconds, median (min to max), n=5 | Container kbit/s, median |
|---|---|---|
| baseline, moving picture | 1.160 (1.106 to 1.179) | 7898 |
| PNG overlay, `-loop 1 -framerate 1` | 1.282 (1.237 to 1.323) | 7864 |
| 400x80 overlay changing at 30 fps | 1.313 (1.294 to 1.348) | 8484 |
| mpdecimate, moving picture | 1.161 (1.087 to 1.184) | 7898 |
| baseline, static picture (SMPTE bars) | 0.597 (0.553 to 0.616) | 114 |
| mpdecimate, static picture | 0.147 (0.144 to 0.149) | 4.4 |

Findings:

- `drawtext` per frame is UNMEASURED: this static ffmpeg build reports `Unknown filter 'drawtext'` although it lists libfreetype in its configuration. A text clock rendered by drawtext on every frame therefore has no number here. The 30 fps changing overlay is only a stand-in for the compositing part, not for text rendering.
- Adding any overlay cost about 0.12 to 0.15 CPU seconds per 10 stream seconds (about 1.2 to 1.5 percent of one core at real time) on this machine. The pre-rendered PNG input (1.282) against the 30 fps changing overlay (1.313) differs by 0.03 s per 10 s (about 0.3 percent of a core), and the min to max ranges overlap (1.237 to 1.323 against 1.294 to 1.348). This is NOT a reliable win; with five runs it is within noise.
- `mpdecimate` is neutral on a moving picture (1.161 against 1.160) and cuts CPU on a static picture by about 75 percent (0.597 to 0.147 s) because most frames are dropped (bitrate 114 to 4.4 kbit/s). Dropping frames changes the output frame rate, which a live platform may treat as a stalled feed; the effect on a real stream is UNVERIFIED.

## v0.16 bandwidth trend predictor (SYNTHETIC traces only)

`tests/test_predictor.py` feeds generated one-per-second ffmpeg speed and bitrate readings (deterministic noise) to `predictor.TrendPredictor` (EWMA plus least-squares slope over 40 s, slope must be 5 standard errors below zero, 5 degrading readings in a row, 30 s extrapolation horizon). These are synthetic traces, not real streams. They say nothing about accuracy on a real connection, which is UNVERIFIED.

| Synthetic trace | Result (measured by running the tests) |
|---|---|
| steady speed 1.0, noise of 2 percent and 5 percent, 40 seeds each | 0 false positives in 80 traces |
| ramp down, 1.10 falling 0.003 per second, crossing 0.95 at 50 s, noise 2 percent, 20 seeds | flagged 14 to 27 s before the crossing (the test requires at least 10 s) |
| step from 1.0 to 0.6 at 90 s | flagged 9 to 10 s after the step: a step is not predicted ahead |

The output queue length is not available from ffmpeg progress lines or `network.py`, so it is not used.
