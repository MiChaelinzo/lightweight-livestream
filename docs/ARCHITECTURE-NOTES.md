# Architecture notes

## Auto-scaling: how a quality step is applied (0.9.0)

Auto-scale is off by default. `--auto-scale`, `"auto_scale": true` in config.json, or the GUI checkbox is the approval to change quality without asking each time. With it off, the advisor stays suggestion-only as in 0.7.

A step changes width, height, fps and video bitrate together (`autoscale.py`, `LadderStep`). Lowering order: bitrate first, then fps, then resolution (sizes and bitrates come from `presets.PRESETS`, so numbers are not duplicated). The top step is what the person chose; the scaler never goes above it or below the floor preset (`potato` size).

### Chosen approach: restart through the reconnect loop

`run_with_reconnect(restart=event)` ends the running ffmpeg and starts it again at once with the settings of the new step. No backoff, no failure count, status `restarting`. Viewers see a short interruption (ffmpeg start time plus the platform reconnecting). A local recording continues in the next numbered file (`name-2.mkv`) through the existing `argv_for_attempt` path. The stream key stays in the runner argv; the messages the scaler writes contain only sizes, fps and kbps.

### Alternatives evaluated

| Option | Result |
| --- | --- |
| ffmpeg `sendcmd` or `zmq` filter commands | Can change a `scale` filter while running, but not the encoder bitrate or frame rate, so the stream would keep its old bitrate. |
| Changing x264 parameters live | Not possible; `-x264-params` is read at encoder start. |
| Two process relay (capture to a local relay, relay to RTMP) | Could switch quality without dropping the connection, but adds a second process (CPU and RAM) and a local protocol. That works against the low-end goal. |

These are design conclusions from ffmpeg's documented behavior; none were benchmarked here. The two process relay was measured in 0.12; see [Platform v2 decisions](#platform-v2-decisions-from-measured-spikes-012) below.

### Hysteresis

| Rule | Constant in `autoscale.py` |
| --- | --- |
| Step down after stress lasted | `DOWNSCALE_AFTER_SECONDS` |
| Step up one step after health lasted (longer) | `UPSCALE_AFTER_SECONDS` |
| No step up after a Gaming First CPU step down for | `GAMING_STEP_UP_HOLDOFF_SECONDS` |
| Pause after any change | `COOLDOWN_SECONDS` |
| Changes per hour | `MAX_CHANGES_PER_HOUR` |

Stress means encoding speed under `adaptive.SLOW_SPEED_BELOW` or dropped frames over the advisor threshold. A reading with unknown speed or recent reconnects is neutral and resets both timers, so alternating input cannot flap. Gaming First: with a profile that reserves cores, system CPU at or above `GAMING_CPU_STEP_DOWN_PERCENT` while ffmpeg speed is fine also counts as stress, and the message says so. The values are design choices, UNVERIFIED on real streams.

## Optimizer and network stability

`optimizer.py` turns the advisor, `HealthTracker.summary()`, telemetry samples and the stability score into `Insight(area, action, value, confidence, explanation, plain_text)`. It reuses `adaptive.py` thresholds. Confidence formula: see the `optimizer.py` docstring.

Network stability (`HealthTracker.network_stability()`, 0 to 100) is inferred from bitrate against target, speed jitter and reconnects. ffmpeg's RTMP output does not report packet loss, so this is an inference and is labelled that way. `bandwidth.measure_connect_latency` times a TCP connect to the ingest host and port (the stream key is never part of it); it is a hint, not packet loss.

Opt-in history: with `--analytics`, `reports/history.json` keeps the newest 30 rows (date, preset, bottleneck class, average speed, dropped frames, reconnect count). No key, URL, path or audience data. Matching earlier bottlenecks raise confidence by a capped bonus.

## Stream key in the ffmpeg command line (0.11.0)

The ingest URL, including the key, is the last argument of the ffmpeg process. Other local users can read it from `ps` or `/proc/<pid>/cmdline` on Linux and macOS; on Windows other processes of the same user can. LightStream's redaction covers its own logs and output only. For a single-user streaming PC this is a low risk; it is documented, not solved.

| Alternative | Conclusion |
| --- | --- |
| Pass the URL on stdin or from a file | ffmpeg has no option that reads the output URL from stdin or a file. `-/option file` (ffmpeg 7) loads option values from a file, but the output URL is a positional argument, not an option. Not implemented. |
| `-protocol_whitelist` with a file-based URL | The whitelist restricts which protocols may be opened. It does not hide the URL, and an rtmp URL stored in a file would need a demuxer that reads URLs (concat, playlist) on the output side, which does not exist. Not implemented. |
| Environment variable expansion | ffmpeg does not expand environment variables in URLs, and a shell is not used (`shell=True` is avoided on purpose). Environment variables of a process are also readable by the same users on Linux through `/proc/<pid>/environ`. Not implemented. |
| Local relay process that holds the key | The relay would still need the key, so the key would show in that process's argv or need its own config file, plus an extra process on a low-end PC. Not implemented. |

These are conclusions from ffmpeg's documented behavior; none were tested with the real ffmpeg, so they are PARTIALLY VERIFIED at best. Nothing was implemented because no option was both safe and testable.

## Dual-GPU laptops: `optimus_mx250` (0.11.0)

When an NVIDIA GeForce MX250 and an Intel graphics adapter (Iris Plus, UHD, HD) are both detected, `classify_gpus` returns `optimus_mx250` instead of `mx250_streamer`. Its encoder order is Quick Sync first, NVENC second. Reasoning (a deliberate design choice, UNVERIFIED on real hardware): on an Optimus laptop the game renders on the MX250, so encoding on the idle Intel Quick Sync block keeps the MX250's video engine and power budget for the game. If Quick Sync fails to start, the existing fallback tries the next encoder and then libx264. `record_by_default` and the 4500 kbps cap match `mx250_streamer`. Single-GPU machines are unchanged. Windows detection now runs PowerShell `Get-CimInstance Win32_VideoController` first and `wmic` second, because wmic is removed from Windows 11 24H2; both paths are tested with fake command output only.

## Platform v2 decisions from measured spikes (0.12)

Evidence: `tools/spikes.py`, numbers and method in [BENCHMARKS.md](BENCHMARKS.md#v012-spikes-split-publisher-tee-recording-potato-filters-srt). One Linux sandbox, static ffmpeg 7.0.2, loopback only, mostly one run per scenario (n = 3 for the CPU tables). Anything involving a real platform is UNVERIFIED.

| Candidate | Decision | Evidence | Open risk |
| --- | --- | --- | --- |
| Split publisher: encoder -> MPEG-TS over local UDP -> long-lived `-c copy` publisher -> RTMP | Adopt as an opt-in path for quality changes (auto-scale, Emergency) on top of the existing restart; the restart through the reconnect loop stays the default | RTMP session to a local ffmpeg listener survived encoder SIGKILL with 1 s and 5 s gaps; received dts strictly increasing; publisher costs about 0.105 CPU s per 10 s and 19.1 MiB (n = 3) | ffmpeg collapses the gap in the timeline; about 30 of 300 frames lost per run (mostly at publisher start); platform reaction to a silence and to collapsed timestamps UNVERIFIED |
| Resolution change after an encoder restart vs constant output resolution | Keep the output resolution constant inside one publisher session (scale to the top step size, change bitrate and fps only); a size change goes through the normal restart | A 640x360 to 960x540 switch decoded with 0 errors in ffmpeg | Platform transcoders and players with a mid-stream size change UNVERIFIED, so not relied on |
| `sendcmd` / `zmq` live filter commands | Still rejected | Not measured; the 0.9.0 reason stands (cannot change encoder bitrate or rate control) | none new |
| Earlier "two process relay costs too much" rejection | Revised: the measured cost is small (about 1 percent of one core here, 19.1 MiB). Kept opt-in because the gap and platform behavior are unverified | spike A overhead table | slow CPUs may show a higher share (UNVERIFIED) |
| Tee recording spec | Must change (FEAT-003): add explicit `-map` for video and audio, `-flags +global_header`, flv slot `onfail=abort`, matroska slot `onfail=ignore` | Today's `build_command` argv with `record_to` exits 234 (`Output file does not contain any stream`); without global header the mkv slot writes 291 bytes and the failure is hidden; a slot without `onfail` keeps ffmpeg running after the RTMP server dies (so reconnect never fires), `onfail=abort` exits at once and leaves a readable mkv | Real platform disconnect may surface differently than a killed local listener (UNVERIFIED) |
| Recording container | Keep Matroska with `-flush_packets 1`; reject plain MP4; fragmented MP4 not adopted (no gain over Matroska) | After SIGKILL: MKV readable (150 of 150 frames with flush), MP4 `moov atom not found`, fragmented MP4 readable | none new |
| Numbered recording files across a reconnect | Keep `numbered_recording_path` | `name.mkv` kept and readable after kill -9, `name-2.mkv` written by the next attempt | none new |
| Potato filters | Use fps and size reduction (`fps=10..15`, 640x360 or 480x270); reject `format=gray` as a CPU saver; `mpdecimate` not by default (possible opt-in for static scenes later) | fps=10 -57 percent CPU, 640x360 -31 percent, 640x360 at 15 fps -48 percent; gray +21 to +162 percent CPU; mpdecimate -76 percent on a static picture, 0 on moving content | Variable frame rate output from mpdecimate on platforms UNVERIFIED; synthetic sources, not a game or desktop |
| Thread limits for potato | Keep low thread counts (1 to 2) as the potato default | 1 thread 0.835 CPU s vs 4 threads 1.093 (testsrc2) | Real-time keep-up on a weak CPU UNVERIFIED |
| x264 CBR (`nal-hrd=cbr`) | Not the default; keep capped VBR (`-maxrate`, `-bufsize`) | CBR pads a static picture to 2088 / 4098 kbps where CRF needs 112; CPU close to baseline | Platforms that require strict CBR were not checked |
| SRT | Offer only as a custom URL or a local relay transport, not as a platform preset. Twitch and YouTube presets stay RTMP(S) | Loopback listener and caller work (178 of 180 packets at 120 ms latency, one run), caller without listener fails after 3.04 s; option list from this build | Loss and ARQ behavior not measured (no netem); whether any platform accepts SRT ingest was not checked here |

## Hybrid recording semantics (0.12, implemented)

Default (one ffmpeg, tee): the live slot has `onfail=abort`, the file slot `onfail=ignore`. When the ingest dies ffmpeg exits, the runner reconnects with backoff, and the recording continues in the next numbered file (`name-2.mkv`). The first file stays readable (Matroska). This is not one continuous file: the gap while ffmpeg restarts is not recorded. Tested with a real loopback RTMP listener killed mid-stream (`tests/test_hybrid_recording.py`, needs `LIGHTSTREAM_TEST_FFMPEG`).

Continuous file (opt-in `--persistent-ingest`): the encoder tees MPEG-TS to a local UDP port and to the file; a separate `-c copy` publisher sends to RTMP and reconnects on its own. An ingest failure never stops the encoder, so the file stays continuous. Cost: a second process, about 19 MiB and about 1 percent of a core in the spike. Encoder restarts (auto-scale, Emergency) still begin a new numbered file, and the output size must stay constant (the ladder uses `constant_size`). Tested on loopback (`tests/test_persistent_ingest.py`); real platforms UNVERIFIED. Rejected: `onfail=ignore` on the live slot in the single process design, because the reconnect loop would never fire and the stream would silently stay down.
