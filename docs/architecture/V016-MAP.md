
# v0.16 map: guardian, auto-survival, profiles and honest limits

Status words: **Existing** (already in 0.15), **Extended** (0.15 code grows), **New** (new module), **Roadmap** (not built, with reason). Labels: VERIFIED, PARTIALLY VERIFIED, UNVERIFIED. Competitor (OBS, Streamlabs, XSplit) numbers are UNKNOWN everywhere. Same layout as [V015-MAP.md](V015-MAP.md).

The F numbers follow the request list for this release. Rows F1 to F3, F5, F7 and F10 were labelled by the feature they became in code; the numbering of those rows is a best reading of the request and should be checked against the original list.

## Baseline (before any v0.16 change)

Branch `feat/v0.16-guardian` off 0.15.0. Environment: Linux sandbox, 8 cores, Python 3.11, ffmpeg 7.0.2 static, no GPU.

| Suite | Result | Status |
|---|---|---|
| `python3 -m unittest discover -s tests` | 828 tests, OK (3 skipped, display-gated) | VERIFIED |
| `node --test "web/test/*.test.js"` | 42 pass, 0 fail | VERIFIED |

## Feature map

| # | Feature | Status | Existing code and what changed | Reason and decision |
|---|---|---|---|---|
| F1 | AI Performance Guardian | New (`guardian.py`), opt in | `--guardian` (config `guardian`, GUI checkbox) adds telemetry pressure (CPU, RAM, CPU temperature, GPU) as extra reasons for the existing `AutoScaler` through `assess(extra=...)`. Ladder gained 900p and 45 fps steps | One engine, not a second one. Every step restarts the encoder because ffmpeg ignores runtime bitrate changes for libx264, x265, vpx and aom (spike F). Called "Guardian", not AI: it is rules. Real machines UNVERIFIED |
| F2 | Auto-survival | New (`guardian.SurvivalMonitor`), opt in | `--auto-survival` (config `auto_survival`, GUI checkbox). CPU at or above 95 percent or RAM at or above 90 percent for 10 s enters constant-size emergency settings; leaves after both stay under 80 percent for 60 s; 60 s cooldown, 4 entries per hour | Audio has priority and is never reduced. Constant size keeps the picture size so persistent ingest keeps working. State machine VERIFIED with a fake clock; real machines UNVERIFIED |
| F3 | Bandwidth trend predictor | New (`predictor.py`) | EWMA plus least-squares slope over 40 s of ffmpeg speed, feeds `--guardian` as one more STRESSED reason | SYNTHETIC traces only: 0 false positives in 80 noisy steady traces, ramp flagged 14 to 27 s ahead, a step is flagged 9 to 10 s after it. The output queue is not available from ffmpeg, so it is not used. Real streams UNVERIFIED |
| F4 | CPU saving from lighter overlays and static-frame dropping | Measured, not a feature claim | Spike G in `tools/spikes.py`. No new runtime code | Any 10 to 25 percent figure is claimed only as measured: mpdecimate cut CPU about 75 percent on a static picture and nothing on a moving one (n=5); a pre-rendered PNG overlay showed no reliable win (overlapping ranges, n=5); `drawtext` is absent in this static build, so per-frame text cost is unmeasured. Live effect of mpdecimate UNVERIFIED |
| F5 | One-click profiles | Extended (`perf_profiles.py`, `presets.py`) | `potato_pc`, `office_laptop`, `budget_gaming` and a pure `recommend_profile()` printed by `optimize`. Details in [PROFILES.md](../PROFILES.md) | 40 fps rejected (judders on 60 Hz). New presets are profile-only and skipped by `bandwidth.recommend`, so fast uploads do not pick 1080p60 by accident. Real PCs UNVERIFIED |
| F6 | Moment detection (laughing, kill streak, chat explosion) | Existing, limited | `highlights.py` heuristics from scene change, audio bursts and motion | Laughing, kill streaks and chat explosions are NOT detected, and no code reads chat. Marked as such in docs. ML is out of scope |
| F7 | Resource timeline | New (`timeline.py`) | Bounded in-memory event log; the end-of-session output lists load spikes with events that "happened around" them | Correlation, never a cause. Nothing is persisted, so there is no `lightstream timeline` command yet |
| F8 | Stream health score | Existing | `optimizer.performance_health` (0 to 100 with a band) and `health.py` | No change needed. Weights are heuristics |
| F9 | Overlay SDK | Existing, limited | Plugin runtime v1 (`plugins.py`). Plugin name check now uses `fullmatch` (a trailing newline was accepted) | The SDK means overlay filters through the plugin protocol. A per-overlay RAM budget is measurable only for plugin subprocesses (their RSS), not for filters inside the one ffmpeg process. Plugins are not wired into `start` yet |
| F10 | Portable and idle budgets | Extended | Portable-mode audit: no path escaped the folder, no code fix. `tools/idle_budget.py` plus a display-gated budget test | Scenes collections and recordings are siblings of `data/` by existing design. Idle GUI under Xvfb: startup 0.146 to 0.149 s, RSS 37.5 to 37.9 MB, CPU 0.25 to 0.30 percent (3 runs, no GPU). Windows and macOS UNVERIFIED |
| CAE | Crowd-Assisted Encoding | Roadmap, not claimed | None | The claimed 20 to 40 percent saving is NOT claimed and nothing was measured. No design exists that works with stock RTMP ingest, so no code was started |
| S1 | Control API and phone remote | Roadmap | None | Design requirements before any code: bind 127.0.0.1 by default, token auth, LAN only by explicit opt-in, the stream key is never returned or logged |
| S2 | Cloud scene sync | Roadmap | Scene collections export and import files already exist | Needs accounts and storage, which the stdlib-only no-server design avoids. Same requirements as S1 (no stream key in synced data) |
| S3 | Companion mobile app | Roadmap | None | Depends on S1. Chat priority belongs here, not in LightStream |
| S4 | Scene composer (drag and drop) | Roadmap | `scenes.py` JSON works | A Tk canvas composer is too large for this release |

## Decisions

1. **One engine.** Guardian only supplies extra signals to the existing AutoScaler, so hysteresis, cooldown and the hourly cap stay in one place.
2. **Every step restarts the encoder.** Spike F showed `sendcmd` reaches filters but libx264, libx265, libvpx, libvpx-vp9 and libaom-av1 silently ignore it, and `zmq` is absent in the static build. Hardware encoders were not testable here. Persistent ingest keeps the connection alive; about 10 percent of frames were lost near a restart on loopback.
3. **GUI Emergency with persistent ingest** now runs the constant-size variant instead of being declined.
4. **Opt in everywhere.** `guardian` and `auto_survival` default to off; nothing changes settings unless enabled, and the tests check that nothing runs with the flags off.
5. **Nothing invented.** No competitor numbers, no CPU-saving figures beyond the spike tables, predictor results labelled synthetic.
6. **Dependabot workflow observation (needs the user's decision).** `.github/workflows/dependabot-auto-merge.yml` was added by the user and is untouched. It uses `pull_request_target` with `contents: write`, approves dependabot PRs and enables auto-merge. There is no `.github/dependabot.yml`, so dependabot has no configured ecosystem to update, and the project has no runtime dependencies (stdlib Python, no npm in `web/`). GitHub Actions is billing-locked, so the workflow cannot run now. Recommendation: either add `dependabot.yml` for the `github-actions` ecosystem only and require CI checks before merge, or remove the workflow. Auto-merge waits for required checks only if branch protection requires them; without it the merge happens at once.

## Final status (0.16.0)

| Area | Status | Evidence |
|---|---|---|
| Guardian pressure rules, ladder steps, survival state machine, timeline | VERIFIED | unit tests with fake clocks and samplers |
| Predictor accuracy | PARTIALLY VERIFIED | synthetic traces only |
| Guardian and survival on a real overloaded machine or live stream | UNVERIFIED | never run |
| Idle GUI budgets | VERIFIED (Linux, Xvfb, 3 runs) | `tools/idle_budget.py` |
| GUI checkboxes rendering | UNVERIFIED | not run under Xvfb |
| Runtime bitrate change for software encoders | VERIFIED as not possible | spike F |
| Runtime bitrate change for hardware encoders | UNVERIFIED | none available |
| Overlay cost, mpdecimate on static picture | VERIFIED (synthetic) | spike G, n=5 |
| `drawtext` cost | UNMEASURED | filter absent in the static build |
| mpdecimate on a real stream | UNVERIFIED | |
| New profiles on real PCs | UNVERIFIED | argv checked by golden files |
| Portable audit | VERIFIED (Linux) | tests |
| OBS Studio and Streamlabs comparison | UNKNOWN | not measured |
| Windows and macOS behavior | UNVERIFIED | never run |

## Remaining limitations

- Every guardian or survival step restarts the encoder; viewers can notice it.
- Output queue length is not available, so the predictor uses speed and bitrate only.
- The timeline is not persisted; there is no `lightstream timeline` command.
- Laughing, kill streaks and chat explosions are not detected.
- No control API, phone remote, cloud scene sync, companion app or scene composer.
- The stream key is visible in the ffmpeg argv (process list) while streaming.
- Plugins are not wired into `start`.
- The dependabot workflow question above is open.

## Final suite (0.16.0)

| Suite | Result | Status |
|---|---|---|
| `python3 -m unittest discover -s tests` | 911 tests, OK (4 skipped, display-gated; the idle GUI test needs DISPLAY) | VERIFIED |
| `node --test "web/test/*.test.js"` | 43 pass, 0 fail | VERIFIED |
| `tools/export_presets.py --check` | up to date | VERIFIED |
| `python3 -m compileall -q src` | clean | VERIFIED |
| `tools/page_weight.py` | gzip total 20869 B, images 84984 B | VERIFIED |
