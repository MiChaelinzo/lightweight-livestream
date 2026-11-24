# Dashboard panels, multi-device viewing and OBS-style layers (v0.12)

Status labels follow the project convention: VERIFIED (unit tests or a real run), PARTIALLY VERIFIED (inspection or fakes), UNVERIFIED (never run), Roadmap (not built).

## 1. Dashboard panels onto existing pages

No page was added. `gui_pages.PANELS` maps each requested panel onto a page that already exists. The sidebar keeps its six labels.

| Panel | Page | What is there |
| --- | --- | --- |
| Home | Dashboard | Start, stop, Emergency, health cards, suggestions |
| Streams | Scenes | Scenes, scene import and export |
| Devices | Setup wizard | Detected hardware and capture choices |
| Performance | Dashboard | Seven graphs (fps, bitrate, speed, drops, RAM, CPU, GPU), "This PC" numbers, the health line |
| Network | Dashboard | Network insights in the suggestions list (congestion findings now reach the GUI) |
| Recording | Recording | File type (MKV or MP4), bitrate mode (VBR or CBR), Potato Stream with grayscale and skip-static |
| Analytics | Dashboard | "Compare last two saved sessions" (needs the opt-in session history) |
| Settings | Advanced | Frame rate, devices, profiles, opt-ins |

Pure logic (panel map, ring buffers, comparison, health line) is VERIFIED by unit tests. Window layout and rendering are UNVERIFIED: there is no display here, only a headless import test.

Persistent ingest stays command line only (`--persistent-ingest`). The GUI worker does not use the split publisher, and wiring it would change the run loop, which cannot be checked without a display.

### Performance panel and bottleneck rule

`gui_theme.PerformanceBuffers` keeps one fixed-size `RingBuffer` per series (60 readings, about a minute). Drops are stored as the change since the last reading. Unknown readings stay `None` and show as gaps. GPU and RAM use the telemetry sampler, so they read `n/a` where the sampler cannot read them.

The bottleneck rule is `optimizer.classify_bottleneck` (CPU, GPU, encoder, network, thermal, unknown), already used for insights. Session comparison is `analytics.compare_sessions` over the history rows: health score, speed and bitrate (higher is better), dropped frames and reconnects (lower is better). Rows from older versions lack some fields and show "no data for both sessions".

The health score is a heuristic (weights in `optimizer.HEALTH_WEIGHTS`). In the GUI and the CLI it leaves out dropped-frame percent, because the tracker keeps a count and not a frame total. The CLI and GUI show the score; the PC tier is shown only when a caller passes it (the bench is too slow to run on every session).

## 2. Look: glass on the web, layered cards natively

ttk cannot blur or draw translucent widgets, so true glassmorphism is not possible in the window. `gui_theme.card_style` gives a native equivalent (a lighter card color, a soft border, a thicker border for higher elevation); only the group box border is themed in `gui.py`. How it looks is UNVERIFIED.

`web/style.css` uses `backdrop-filter` for `.card` inside `@supports`, so browsers without it keep the solid card. `prefers-reduced-transparency: reduce` turns the effect off. Page weight went from 54896 to 55632 bytes (20379 to 20588 gzip). Rendering in real browsers is UNVERIFIED (no Chromium here); the service worker fingerprint and the contrast checks are tested.

## 3. Multi-device viewing (design only)

`viewer_models.py` holds typed models (`ViewerEndpoint`, `RelayConfig`) and validators. Nothing calls them from the streaming path and nothing listens on a port.

| Idea | Status | Notes |
| --- | --- | --- |
| LAN preview on another screen | Partial | An `srt://` custom URL already works (validated, loopback tested) when the viewer listens, for example `ffplay`. There is no dedicated option, no discovery and no latency measurement. SRT and UDP are the only transports the current ffmpeg path can send to |
| Tablet or phone viewer | Roadmap | Needs a viewer app or a page plus a transport the phone can play. Browser-playable transports (HLS, WebRTC) need a packager or relay that this project does not ship |
| Browser viewing | Roadmap | Same constraint. HLS from ffmpeg adds several seconds of delay |
| Cloud relay | Roadmap | Third-party relays (an SRT or RTMP server) can be reached today through a custom URL. A hosted LightStream relay is not planned: it needs accounts, cost and security work |
| Mobile remote control | Roadmap | See ROADMAP.md (loopback token API, not started) |

## 4. OBS-style layers

The layer model is the existing one: a scene is an ordered set of sources and overlays (`scenes.py`, `overlays.py`) saved as JSON. Collections are shared with `scene_collections` (export one scene, export all, import with a conflict check). That is the integration layer. It does not read or write OBS files and does not talk to obs-websocket; both are Roadmap. A person can use OBS to produce the picture and point LightStream at its virtual camera or window as a source (not tested here).

## 5. Moonlight, Parsec and Steam Remote Play class: feasibility only

No code or stubs exist. Notes from design inspection, UNVERIFIED:

- These tools capture, encode with a hardware encoder, and send over a UDP protocol tuned for latency under 100 ms, with input going back. LightStream sends one RTMP or SRT stream to a server and has no input channel.
- Rebuilding that needs a hardware encode path with low-latency settings, a custom or WebRTC-like transport with congestion control, input injection on the host, and a client per platform. This conflicts with stdlib-only and "drives one FFmpeg process".
- The overlap that is realistic: SRT preview (section 3), which gives a one-way view with latency in the low hundreds of milliseconds at best, not measured here.
- Decision: do not build remote play. Link to those tools in docs if a person wants it.

## 6. Telemetry and diagnostics

- Analytics, history, the performance snapshot and the support bundle are opt-in. Defaults are off in the CLI (`--analytics` or `"analytics": true`) and the GUI checkbox; a test checks that an un-opted GUI session writes nothing.
- `last-performance.json` (numbers only) is saved next to the history in an opted-in session and is added to `support-bundle` when present. It holds the tracker summary, telemetry numbers and the health score.
- Crash reports: an unexpected exception in the CLI writes `crashes/crash-*.json` next to `config.json`, with addresses (anything containing `://`) and `STREAM_KEY` replaced by `****`. Nothing is uploaded; there is no network code in `analytics.py` (tested). The CLI exits with code 70 in that case. Crashes inside the GUI window are not captured yet.
