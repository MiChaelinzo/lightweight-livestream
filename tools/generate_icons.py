"""Generate LightStream desktop and web icons using only the Python stdlib.

The artwork is defined here so Windows ICO, macOS ICNS, Linux SVG, and PWA
PNGs stay reproducible. Run with --check in tests; no release binary is built.
"""

import argparse
import binascii
from functools import lru_cache
import math
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP_DIR = os.path.join(ROOT, "assets", "icons")
WEB_DIR = os.path.join(ROOT, "web", "icons")

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="LightStream broadcast mark">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#17234a"/><stop offset="1" stop-color="#070a14"/></linearGradient><linearGradient id="wave" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#29e0ff"/><stop offset="1" stop-color="#c04dff"/></linearGradient></defs>
<rect x="2" y="2" width="96" height="96" rx="22" fill="url(#bg)"/>
<path d="M27 25v50h25" fill="none" stroke="#f4f7ff" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="47" cy="50" r="6" fill="#29e0ff"/>
<path d="M56 39a16 16 0 0 1 0 22M64 30a29 29 0 0 1 0 40M73 21a42 42 0 0 1 0 58" fill="none" stroke="url(#wave)" stroke-width="6" stroke-linecap="round"/>
</svg>
"""


def _chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data +
            struct.pack(">I", binascii.crc32(kind + data) & 0xffffffff))


def _shape_color(x, y):
    """Return foreground RGB at normalized coordinates, or None."""
    # White L, kept inside the maskable safe area.
    vertical = 0.255 <= x <= 0.345 and 0.25 <= y <= 0.75
    horizontal = 0.255 <= x <= 0.52 and 0.66 <= y <= 0.75
    if vertical or horizontal:
        return (244, 247, 255)

    cx, cy = 0.47, 0.5
    distance = math.hypot(x - cx, y - cy)
    if distance <= 0.06:
        return (41, 224, 255)
    angle = abs(math.atan2(y - cy, x - cx))
    if x > cx and angle <= 0.78:
        for index, radius in enumerate((0.16, 0.29, 0.42)):
            if abs(distance - radius) <= 0.03:
                blend = index / 2.0
                return (round(41 + (192 - 41) * blend),
                        round(224 + (77 - 224) * blend), 255)
    return None


def _rounded_square(x, y, radius=0.2):
    inner = 0.5 - radius
    dx = max(abs(x - 0.5) - inner, 0.0)
    dy = max(abs(y - 0.5) - inner, 0.0)
    return math.hypot(dx, dy) <= radius


def _sample(x, y, maskable):
    if not maskable and not _rounded_square(x, y):
        return (0, 0, 0, 0)
    # A stable diagonal/radial background without image-library dependencies.
    glow = max(0.0, 1.0 - math.hypot(x - 0.32, y - 0.28) / 0.9)
    r = round(7 + 16 * glow)
    g = round(10 + 25 * glow)
    b = round(20 + 54 * glow)
    foreground = _shape_color(x, y)
    if foreground:
        r, g, b = foreground
    return (r, g, b, 255)


@lru_cache(maxsize=None)
def png_bytes(size, maskable=False):
    """Render an antialiased RGBA icon and return deterministic PNG bytes."""
    rows = bytearray()
    samples = (0.25, 0.75)
    for py in range(size):
        rows.append(0)  # PNG filter: None
        for px in range(size):
            colors = [_sample((px + sx) / size, (py + sy) / size, maskable)
                      for sy in samples for sx in samples]
            rows.extend(round(sum(color[channel] for color in colors) / len(colors))
                        for channel in range(4))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) +
            _chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _chunk(b"IEND", b""))


def ico_bytes():
    sizes = (16, 32, 48, 64, 128, 256)
    images = [(size, png_bytes(size)) for size in sizes]
    offset = 6 + 16 * len(images)
    entries = []
    payload = []
    for size, image in images:
        byte_size = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", byte_size, byte_size, 0, 0,
                                   1, 32, len(image), offset))
        payload.append(image)
        offset += len(image)
    return struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries + payload)


def icns_bytes():
    images = {
        b"ic11": png_bytes(32),
        b"ic12": png_bytes(64),
        b"ic07": png_bytes(128),
        b"ic13": png_bytes(256),
        b"ic08": png_bytes(256),
        b"ic14": png_bytes(512),
        b"ic09": png_bytes(512),
        b"ic10": png_bytes(1024),
    }
    chunks = [kind + struct.pack(">I", len(data) + 8) + data
              for kind, data in images.items()]
    body = b"".join(chunks)
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def generated_files():
    svg = SVG.encode("utf-8")
    return {
        os.path.join(DESKTOP_DIR, "lightstream.svg"): svg,
        os.path.join(DESKTOP_DIR, "lightstream.ico"): ico_bytes(),
        os.path.join(DESKTOP_DIR, "lightstream.icns"): icns_bytes(),
        os.path.join(WEB_DIR, "lightstream.svg"): svg,
        os.path.join(WEB_DIR, "icon-192.png"): png_bytes(192),
        os.path.join(WEB_DIR, "icon-512.png"): png_bytes(512),
        os.path.join(WEB_DIR, "maskable-512.png"): png_bytes(512, maskable=True),
        os.path.join(WEB_DIR, "apple-touch-icon-180.png"): png_bytes(180),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if tracked icons differ from generated bytes")
    args = parser.parse_args(argv)
    files = generated_files()
    stale = []
    for path, expected in files.items():
        if args.check:
            try:
                with open(path, "rb") as handle:
                    actual = handle.read()
            except OSError:
                actual = None
            if actual != expected:
                stale.append(os.path.relpath(path, ROOT))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(expected)
            print("wrote %s (%d bytes)" % (os.path.relpath(path, ROOT), len(expected)))
    if stale:
        print("icon files are stale: %s" % ", ".join(stale), file=sys.stderr)
        print("run: python3 tools/generate_icons.py", file=sys.stderr)
        return 1
    if args.check:
        print("icon files are reproducible and up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
