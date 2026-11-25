# Dev-only UI rendering

`tools/ui_snapshots.py` renders the Tk GUI and the web page to PNG files so visual work can be looked at, not guessed. It is never imported by the runtime, and its dependencies are optional dev tools. Without them it prints a one-line install hint and exits non-zero.

```
python3 tools/ui_snapshots.py gui --out DIR [--size 1366x768] [--theme light|dark] [--compact] [--pages all|dashboard,setup]
python3 tools/ui_snapshots.py web --out DIR [--widths 1280,390]
```

- `gui` captures the whole virtual screen at `--size`. The window keeps the size Tk requests, so a window taller than the screen shows as clipped, as it would for a user. It builds `StreamWindow` directly (not `gui.main()`), so the ffmpeg help dialog never appears, and it uses a temporary HOME so real prefs are not read or written. If `DISPLAY` is set it is used as is; otherwise Xvfb is started from `$LIGHTSTREAM_XVFB` or `PATH` on a free display number and stopped afterwards.
- `web` serves `web/` on a local port, saves full-page screenshots with headless Chromium (SwiftShader for WebGL), prints console warnings and errors, and fails on any page error.
- Output names: `gui-<theme>[-compact]-<page>-<W>x<H>.png`, `web-<width>.png`.

## How the stack was obtained in the sandbox

None of this is committed. It lives outside the repo.

| Piece | How |
|---|---|
| Xvfb | conda-forge `xorg-xvfb-server`, installed with micromamba |
| Pillow, playwright | `pip install pillow playwright` in a venv |
| Chromium | `playwright install chromium` with `PLAYWRIGHT_BROWSERS_PATH` set |
| Chromium launch fix | symlink `libatomic.so.1` into a directory on `LD_LIBRARY_PATH` |

Fonts: Segoe UI is unavailable, so screenshots are Linux renders with a DejaVu/Noto-like font. Spacing and text width differ from Windows. Treat them as layout checks, not pixel truth for Windows.
