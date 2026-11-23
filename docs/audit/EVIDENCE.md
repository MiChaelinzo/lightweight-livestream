# Audit evidence (v0.10)

Raw, measured evidence for the v0.10 audit. Nothing here is estimated. Labels:
**VERIFIED** (command run in this session, output recorded), **PARTIALLY VERIFIED**
(read from source only), **UNVERIFIED** (not run, cannot be run in this environment).

Environment: Linux x86_64, Intel Xeon Platinum 8488C, 8 logical cores (`nproc`),
Python 3.11.15, static FFmpeg 7.0.2 (`ffmpeg-7.0.2-amd64-static`), no GPU, no display.
This is a CPU-only Linux sandbox. It is not representative of the low-end Windows
target tier, so absolute numbers must not be quoted as target-hardware results.

## 1. Baseline test suites (VERIFIED)

Commands (run from the repo root, with `FF=/projects/sandbox/.cache-ffmpeg/ffmpeg-7.0.2-amd64-static/ffmpeg`):

```
LIGHTSTREAM_TEST_FFMPEG=$FF python3 -m unittest discover -s tests
python3 -m unittest discover -s tests            # without ffmpeg
node --test "web/test/*.test.js"
python3 tools/export_presets.py --check
python3 -m compileall -q src
```

| Suite | Result |
|---|---|
| unittest with real ffmpeg | Ran 444 tests, OK (about 4.4 s) |
| unittest without ffmpeg | Ran 444 tests, OK (skipped=2) |
| node --test | 25 tests, 25 pass, 0 fail |
| export_presets --check | `web/presets.json is up to date.` |
| compileall src | no errors |

`tools/validate_repo.py` and `dotnet test` named in the project steering do not
exist in this repository and were not run.

## 2. Size and startup (VERIFIED)

`wc -l src/lightstream/*.py`: 6135 lines in 29 modules. Largest: `cli.py` 506,
`gui.py` 505, `gui_controller.py` 486, `bench.py` 460, `scenes.py` 309,
`gui_pages.py` 294, `wizard.py` 264, `config.py` 266, `optimizer.py` 272,
`telemetry.py` 245, `autoscale.py` 240, `scene_collections.py` 238, `runner.py` 225.
Runtime dependencies: none (stdlib only). `tkinter` is imported lazily and guarded
(`cli.py:484`, `gui.py:16-17`).

Import cost of the CLI module (3 runs of `cd src && python3 -X importtime -c "import lightstream.cli"`,
cumulative of the last line): 52.8 ms, 51.5 ms, 51.7 ms.

Peak RSS after importing `lightstream.cli` and `lightstream.gui_controller`
(`resource.getrusage(RUSAGE_SELF).ru_maxrss`): 22684 KB. This includes the Python
interpreter itself. `/usr/bin/time` is not installed here, so `resource` was used.

## 3. FFmpeg capabilities (VERIFIED)

```
$FF -hide_banner -protocols     # rtmp rtmpe rtmps rtmpt rtmpte rtmpts ffrtmpcrypt ffrtmphttp tls
$FF -hide_banner -buildconf     # enable-gnutls enable-libaom enable-libvpx enable-libx264
```

`rtmps` and `tls` are present with GnuTLS, so `rtmps://` ingest URLs (for example
Facebook Live) can be handled by this build. Only protocol support was verified.
No connection to any live ingest was made (UNVERIFIED). `libsvtav1` is not built in.

## 4. Codec CPU cost (VERIFIED, Linux CPU-only, not target-tier hardware)

Source: synthetic `lavfi testsrc2` 1280x720 at 30 fps, 10 s (300 frames), output to
the null muxer, `-benchmark`. All three at `-b:v 4500k -g 60 -pix_fmt yuv420p`.
Host: 8 logical cores. Script: `codec_measure.py` below. Run once per row, so these
are single samples with no variance estimate.

```
import os, subprocess, sys, time
F = sys.argv[1]
TH = ["-threads", "1"] if os.environ.get("ONE") else []
SRC = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "10"]
COMMON = ["-b:v", "4500k", "-g", "60", "-pix_fmt", "yuv420p"]
ENC = {
 "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-maxrate", "4500k", "-bufsize", "9000k"],
 "libvpx-vp9": ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "5", "-row-mt", "1"],
 "libaom-av1": ["-c:v", "libaom-av1", "-usage", "realtime", "-cpu-used", "8", "-row-mt", "1"],
}
for name, enc in ENC.items():
    argv = [F, "-hide_banner", "-nostdin", "-benchmark"] + SRC + TH + enc + COMMON + ["-f", "null", "-"]
    t = time.perf_counter()
    r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    wall = time.perf_counter() - t
    lines = r.stderr.replace("\r", "\n").splitlines()
    print(name, "rc", r.returncode, "wall %.2fs" % wall,
          [l for l in lines if "speed=" in l][-1].split("speed=")[1].strip(),
          [l for l in lines if "bench: utime" in l][-1], [l for l in lines if "bench: maxrss" in l][-1])
```

Run as `python3 codec_measure.py $FF` (all cores) and `ONE=1 python3 codec_measure.py $FF`
(`-threads 1`, a rough proxy for a 1 to 2 core PC; it is not the same as a slow CPU).

| Encoder | Threads | Wall | Speed | CPU time (user+sys) | Max RSS |
|---|---|---|---|---|---|
| libx264 veryfast | default | 0.73 s | 13.5x | 4.29 s | 259036 KiB |
| libvpx-vp9 realtime cpu-used 5 | default | 2.06 s | 4.85x | 7.66 s | 236672 KiB |
| libaom-av1 realtime cpu-used 8 | default | 4.40 s | 2.27x | 8.25 s | 105072 KiB |
| libx264 veryfast | 1 | 2.82 s | 3.52x | 3.04 s | 128032 KiB |
| libvpx-vp9 realtime cpu-used 5 | 1 | 4.63 s | 2.16x | 4.84 s | 194552 KiB |
| libaom-av1 realtime cpu-used 8 | 1 | 6.03 s | 1.66x | 6.25 s | 97528 KiB |

Reading: at this setting, one thread of libx264 uses about 3.0 CPU seconds per 10 s
of 720p30 video, VP9 about 4.8 and AV1 about 6.3. The ratio (x264 cheapest) is the
useful part. The bitrate each encoder actually produced was not measured (null
muxer reports N/A), so quality per bit is UNVERIFIED. The synthetic source is
easier than real game capture. Run-to-run variance was not measured.

## 5. Security review (source grep, PARTIALLY VERIFIED unless noted)

Commands: `grep -nE "shell=True|os\.system|eval\(|exec\(|pickle|chmod|stream_key" src/lightstream/*.py`
and manual reads of `config.py`, `runner.py`, `analytics.py`, `cli.py`, `command.py`,
`wizard.py`, `telemetry.py`, `health.py`, `gui_controller.py`.

| Check | Result |
|---|---|
| `shell=True`, `os.system`, `eval`, `exec`, `pickle` in `src/` | none found (VERIFIED by grep) |
| Subprocess calls | all take an argv list, no shell: `runner.py:157`, `encoders.py:52,81`, `hardware.py:108`, `cli.py:243`, `portable.py:104`, `telemetry.py:205`, `bench.py:132,142,309` |
| Key source | `config.py:258-266` `resolve_key`: `STREAM_KEY` env or hidden `getpass` prompt, never from a file |
| Key in saved files | `gui_controller.py:131-142` `save_prefs` whitelists fields and drops any value containing the key; `wizard.py:84-91` merges only recommended fields; `analytics.build_session_report` and `history_entry` hold numbers and class names only |
| Key in logs | `runner.py:47-49` `redact` replaces the exact key with `****` on both the progress and plain stderr paths (`runner.py:172,174`); `gui_controller.py:304,309` redacts the GUI log. `format_command` redacts per argument |
| Key in `rtmp_host_port` | path (key) dropped before any logging (`bandwidth.py:88-94`) |
| Companion tokens | `web/companion/companion-logic.js:28-39` reads `clientId` and `token` from the URL fragment only, ignores them in the query string; rendering uses `textContent` (`companion.js:11-20`) and `sanitizeChatText` |
| `web/vercel.json` CSP | site: `default-src 'self'; ... script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'`. companion adds only `wss://irc-ws.chat.twitch.tv https://api.twitch.tv` to `connect-src`. Also `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. No inline script or style allowed |

### Findings (real issues and limits)

1. **Key visible in the process list (limit, by design). Status: open, documented here, in CHANGELOG and in `docs/ARCHITECTURE-NOTES.md`.** This is an OS-level exposure that cannot be removed without an stdin or config-file ingest, which FFmpeg's output URL does not offer (alternatives evaluated in `docs/ARCHITECTURE-NOTES.md`). `command.py:113-114`
   and `platforms.py:13-20` put the full ingest URL with the key into the FFmpeg
   argv (`runner.py:157`). On Linux and macOS other local users can read it from
   `ps` or `/proc/<pid>/cmdline`; on Windows other processes of the same user can
   read it. Redaction protects logs only. FFmpeg has no stdin or env option for
   the URL, so this is hard to remove. Document it. Severity: low for a
   single-user streaming PC.
2. **Config, prefs and history files are created with default umask. Status: FIXED in v0.10 (`fileio.py`, mode 0600, tested).**
   `config.py:96`, `wizard.py:90`, `gui_controller.py:139`, `analytics.py:76,115`
   open with plain `open(...)`. VERIFIED: `save_prefs` produced a file with mode
   `0o644` under umask `0o022`. None holds the key, but `config.json` may hold a
   custom `url` (see 3). Severity: low. A 0600 mode on POSIX would be cheap.
3. **A custom `url` may contain the key. Status: FIXED in v0.11 for detection, warning and redaction (`platforms.embedded_key_in_url`, `cli.py`, tested); never saved. Shell history for `--url` stays the user's responsibility.** `platforms.py:18` appends the key to
   `custom_url`, so a user who stores `rtmp://host/app/KEY` as `"url"` in
   `config.json` stores the key in plain text. `save_prefs` guards the GUI
   path (`gui_controller.py:134-138`), but a hand-edited config file or `--url`
   on the command line (shell history) is not guarded. `wizard.py:263` states the
   key is never saved, which is true of LightStream's own writes only.
4. **Non-atomic writes. Status: FIXED in v0.10 (temp file + `os.replace`, tested).** `wizard.py:89-92`, `gui_controller.py:139-142`,
   `analytics.py:115-117` open with `"w"` and write directly, so a crash mid-write
   leaves a truncated JSON file. `load_file_config` (`config.py:79-89`) then raises
   `ValueError` for `config.json`, while `load_history` returns `[]`. Severity: low.
   Scope: private atomic writes cover only config, prefs, history, wizard config and
   report files. `scene_collections.py`, `portable.py` (ffmpeg path) and `bench.py`
   output still use plain `open(..., "w")`; none holds a stream key. `fileio.py`
   does not fsync, so writes survive a process crash, not power loss. Report
   creation removes its partial file if the write fails.
5. **Redaction is exact-substring only. Status: partly fixed (percent-encoded and `quote_plus` forms redacted, several secrets supported, tested in v0.11); other transforms open.** `runner.py:47-49` will not hide a
   percent-encoded or otherwise transformed form of the key if FFmpeg echoes one
   (UNVERIFIED whether FFmpeg ever does). Very short keys also redact unrelated
   text (cosmetic).
6. **Companion token on disk (limit).** Tokens in the URL fragment are not sent
   to a server, but the full URL is stored in the OBS browser-source setting in
   plain text. The Twitch token should be minimal scope. Documented limit, not a
   code defect.
7. **Speed test accepts `http://`. Status: FIXED in v0.11 (`bandwidth.measure_upload` accepts only `https://`, tested).** Originally: `bandwidth.py:74-75` allows plain HTTP for
   the opt-in upload test. It sends random data only, so no secret is exposed.
   Informational.

No remote code execution, injection or shell-quoting defect was found in the
files read. This is a source review plus targeted greps, not a penetration test.
Hosting headers beyond those in `web/vercel.json` (for example HSTS added by the
host) are UNVERIFIED.

## 6. Not verifiable here (UNVERIFIED)

- Windows, macOS, tkinter GUI rendering, GPU encoders (NVENC, QSV, AMF, VideoToolbox).
- Any live ingest connection, including rtmps to a real service.
- OBS, Streamlabs or XSplit numbers. No competitor figure is given in this file.
- Behaviour of the packaged `.exe` (PyInstaller builds were not run).
