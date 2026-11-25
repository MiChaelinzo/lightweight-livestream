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

These are design conclusions from ffmpeg's documented behavior; none were benchmarked here.

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
