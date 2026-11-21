# Roadmap

Status after 0.9.0. Done means implemented and covered by unit tests (see the README verification table for what was never run on real hardware). Partial means some of the area exists. Roadmap means not started; the design notes are intentions, not code.

| Area | Status | What exists or what is planned | Phase | Depends on | Why deferred |
| --- | --- | --- | --- | --- | --- |
| Core engine (profiles, threads, affinity) | Done | `perf_profiles.py`, `telemetry.py`, runner affinity. Effect on game FPS UNVERIFIED | | | |
| AI optimizer | Partial | `optimizer.py` is rule based and explains each insight with a confidence. There is no machine learning model | 2 | opt-in history | A learned model needs real session data that does not exist yet |
| Auto-scaling | Done | Opt-in ladder with hysteresis and restart. See `ARCHITECTURE-NOTES.md` for the alternatives evaluated | | | |
| Dashboard | Partial | Numeric telemetry cards every 2 seconds. No graphs | 2 | telemetry buffers | Needs a Tk canvas drawing layer that cannot be tested without a display |
| Scene system, source types | Partial | Screen, window, browser, webcam, image, text, overlays. No Game Capture, Video file or Alerts source | 2 | scene schema extension | Game Capture is Windows specific and cannot be tested here |
| Gaming first | Done | Reserved cores, thread cap, affinity, step-down under pressure. FPS impact UNVERIFIED | | | |
| Network | Partial | Stability score, connect latency helper, bandwidth advice, reconnect with backoff. No regional endpoint selection, no recovery buffering, no packet loss measurement | 2 | ingest server lists per platform | Endpoint lists change and need a network to check; buffering needs a second process (see auto-scale notes) |
| Overlays (chat boxes, donations, alerts) | Partial | Text, clock, FPS, REC, PNG overlays and the browser companion. No donation or alert feed | 3 | chat, plugin protocol | Needs platform APIs and tokens |
| Chat (Twitch, YouTube, Kick) and moderation | Roadmap | The browser companion reads Twitch chat only. Moderation is not started | 3 | token storage policy | Needs accounts, tokens and network to test; tokens must never be stored in plain config |
| Creator assistant | Partial | Plain words insights and readiness fixes. No conversational assistant | 3 | optimizer history | No data or tests to justify more |
| Audio | Done | Five audio profiles with light and full chains, noise suppression | | | |
| Recording | Partial | Local copy via tee, numbered files after reconnect. No instant replay, clips, highlights, cleanup or space estimate | 2 | recording folder policy | Replay needs a rolling buffer, which costs RAM or disk on low-end PCs |
| Analytics | Done | Opt-in session reports and 30 session history without keys or URLs | | | |
| Stream presets | Done | Seven presets | | | |
| Low-end super mode | Partial | `potato` profile, hardware profiles, auto-scale. Not a single switch and not measured on a low-end laptop | 2 | real low-end benchmark | No such hardware here |
| Mobile remote | Roadmap | Design: stdlib `http.server` bound to 127.0.0.1 by default, random token per run, off by default, never exposes stream keys. LAN binding only by explicit option | 3 | start/stop controller API | Network exposure needs a security review and a phone to test |
| Plugin architecture | Roadmap | Design: each plugin is a subprocess that talks a narrow JSON protocol over stdin and stdout. In-process Python cannot be sandboxed, so in-process plugins are rejected | 3 | protocol spec, event list | A protocol should follow real use cases, not precede them |
| Onboarding | Done | Setup wizard, readiness score, first-run FFmpeg helper. Window rendering UNVERIFIED | | | |
| UI/UX (dark mode, compact mode, shortcuts) | Roadmap | Not started | 2 | none | Cannot be checked without a display |
| Architecture refactor | Partial | Incremental: logic stays in tkinter-free modules. No DI container or event bus this round | 3 | | A container adds indirection for no current need; injected callables already make tests possible |
| Adaptive Creator Intelligence | Partial | Phase 1 done: opt-in local history raises optimizer confidence. Later phases: deterministic rules that compare sessions (same game, same hour) and suggest a profile. No cloud, no learning model | 2 | history from real users | Rules need real data to avoid guessing thresholds |

Phase 2 is the next release, phase 3 is after that. These are ordering notes, not dates.
