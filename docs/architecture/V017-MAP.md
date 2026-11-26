
# v0.17 map: phone remote, session timeline and honest limits

Status words: **Existing** (already in 0.16), **Extended** (0.16 code grows), **New** (new module), **Roadmap** (not built, with reason). Labels: VERIFIED, PARTIALLY VERIFIED, UNVERIFIED. Competitor (OBS, Streamlabs, XSplit) numbers are UNKNOWN everywhere. Same layout as [V016-MAP.md](V016-MAP.md).

## Baseline (before any v0.17 change)

Branch `feat/v0.17-live-studio` off 0.16.0. Environment: Linux sandbox, Python 3.11, ffmpeg 7.0.2 static, no GPU.

| Suite | Result | Status |
|---|---|---|
| `python3 -m unittest discover -s tests` | 943 tests, OK (4 skipped with `LIGHTSTREAM_TEST_FFMPEG` set; current run) | VERIFIED |

## Feature map

| # | Feature | Status | Code | Reason and decision |
|---|---|---|---|---|
| R1 | Phone remote (local control API) | New (`remote.py`), opt in | `RemoteServer` on stdlib `http.server`, daemon thread. `GET /` phone page, `GET /api/status`, `POST /api/emergency`, `/api/restore`, `/api/stop` | Start is not exposed: it needs the stream key, which must not pass through a network endpoint. GUI only; no CLI `--remote`, because the CLI has no controller with emergency and restore |
| R2 | GUI wiring | Extended (`gui.py`, `remote.RemoteSession`) | Advanced page boxes "Phone remote (this PC network only, off by default)" and "Allow my home network", read-only link, Copy link. Server runs only while a stream runs | Pref `remote` is saved; `remote_lan` and the token never are. Window timer drives `sync`, so no new tkinter thread |
| R3 | Session timeline in the window | Extended (`StreamController.timeline_lines`) | Read-only Dashboard box, themed | Same event lines as the end-of-session output. Not persisted. Correlation, never a cause |
| R4 | Emergency vs auto-survival race test | Test only | 8-thread test in `tests/test_gui.py` and a 15-round barrier test | Asserts both modes are never active together |
| S1 | Cloud scene sync | Roadmap | None | Unchanged since 0.16 (accounts and storage) |
| S2 | Companion native app | Roadmap | None | The phone page is a web page only |
| S3 | Scene composer | Roadmap | None | Unchanged |
| CAE | Crowd-Assisted Encoding | Roadmap, not claimed | None | Nothing measured, no savings claimed |

## Security design of the phone remote

Assets: the stream key, control of a live stream, the user's PC network. Attackers considered: another local user or process, another device on the same network (only if LAN is enabled), a malicious web page open in the owner's browser.

| Threat | Mitigation | Status |
|---|---|---|
| Guessing the token | Random token from `secrets`, compared with `hmac.compare_digest`. After 5 failures from one address, further requests from it get a 30 s lockout (injected clock) | VERIFIED by loopback tests (lockout with a fake clock). Strength against a real attacker not assessed |
| Token leaking through URL logs or history | Token is in the `#` fragment, which browsers do not send. The page script reads it and sends `Authorization: Bearer`. Not written to prefs or logs; the server's request log is silenced | VERIFIED for prefs and server log by tests. Browser history and screenshots of the link are the user's responsibility |
| DNS rebinding and malicious web pages | `Host` header must be `127.0.0.1`, `localhost`, `[::1]`, the bound host or an IP literal (DNS names cannot be IP literals, so rebinding stays blocked); other hostnames are refused. No CORS headers are sent, so other origins cannot read responses. Bearer header in a custom header makes simple cross-site POSTs fail | VERIFIED for the Host check on loopback and on a `0.0.0.0` bind with IP-literal and hostname Host headers (sockets on this machine); browser behavior with a real cross-site page UNVERIFIED |
| Network exposure | Binds `127.0.0.1` by default. `0.0.0.0` only when the user ticks "Allow my home network", which shows a warning. The link shows this PC's LAN address (found without sending packets) and is never remembered between sessions; the tick is not saved. Handler sockets time out after 10 s. Traffic is plain HTTP, so on a home network the token can be sniffed by someone on that network | LAN bind UNVERIFIED on a real network (only a local socket test with a spoofed Host). HTTPS is not provided |
| Stream key disclosure | Backend does not expose the key. The real protection is that the controller redacts the key before text reaches its log; the remote's own redact call only masks SRT passphrases. A test seeds the key into the backend log and checks no response contains it | VERIFIED |
| Starting a stream remotely | Not exposed | By design |
| Abuse by large or odd requests | Body cap of 1024 bytes, wrong method gives 405, bad token gives 401 with no detail | VERIFIED |
| Leftover server | Started only while streaming; stopped on stream end, untick and window close. Bind failure returns no server and the GUI continues | VERIFIED with fakes; real port conflicts partly |
| Replay | Not addressed. A captured token works until the run ends. Actions are idempotent in effect (emergency, restore, stop) | Accepted risk |

## Decisions

1. **Smallest useful surface.** Three actions and a status. No start, no settings, no key.
2. **GUI only.** Avoids a second controller in the CLI.
3. **Off by default, local by default.** Both boxes are unticked at first run.
4. **Tests use real loopback sockets** and a fake backend, so the HTTP layer is exercised without a stream.

## Final status (0.17.0)

| Area | Status | Evidence |
|---|---|---|
| HTTP server auth, Host check, lockout, key never in responses | VERIFIED | `tests/test_remote.py`, loopback sockets |
| Prefs round trip, no token saved, lifecycle | VERIFIED | `RemotePrefsTests` and session tests with a fake server |
| Emergency vs survival race | VERIFIED (threads, 8 and 15 rounds) | tests |
| GUI widgets rendering | VERIFIED on Linux under Xvfb; Windows and macOS UNVERIFIED | rendered with `tools/ui_snapshots.py`; screenshots are dev-only in `.devtools/shots-v017/` and not committed |
| Idle budget | VERIFIED (Linux, Xvfb, 2 runs per side) | [BENCHMARKS.md](../BENCHMARKS.md): startup 0.21 to 0.35 s before, 0.16 s after; RSS 38.4 to 38.7 MB before, 38.8 MB after; CPU 0.3% before, 0.2 to 0.3% after |
| Real phone, real home network, non-loopback bind | UNVERIFIED | never run |
| Remote cost while serving | UNVERIFIED | not measured |
| OBS Studio and Streamlabs comparison | UNKNOWN | not measured |

## Remaining limitations

- Plugins are not wired into `start`.
- Copilot live inputs are not collected during a stream.
- SRT statistics are not read.
- Images are not precached.
- The timeline is not persisted; it shows in the GUI only while running and at the end.
- `dropped_messages` is not shown.
- `lightstream bench` skips the encode test when ffmpeg is not on PATH.
- Long Advanced-page checkbox labels are clipped at the right edge (pre-existing).
- Plain HTTP on the LAN; no replay protection.
- The stream key is still visible in the ffmpeg argv while streaming.
- The dependabot workflow question from 0.16 is open.

## Final suite (0.17.0)

| Suite | Result | Status |
|---|---|---|
| `python3 -m unittest discover -s tests` | 943 tests, OK (4 skipped with `LIGHTSTREAM_TEST_FFMPEG` set; 0 skipped under Xvfb earlier run, not repeated) | VERIFIED |
| `node --test "web/test/*.test.js"` | 44 pass, 0 fail | VERIFIED |
| `tools/export_presets.py --check` | up to date | VERIFIED |
| `python3 -m compileall -q src` | clean | VERIFIED |
