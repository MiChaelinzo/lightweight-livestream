"""Print the size of every file under web/ (raw and gzip -9), as JSON.

Usage: python3 tools/page_weight.py [--web DIR]

The totals cover text assets only; images are reported as image_total_bytes.
Only the files are measured. No network, no transfer overhead, no headers.
Skips web/test and web/package.json (not served to visitors in a useful way).
"""
import argparse
import gzip
import json
import os
import sys

SKIP_DIRS = {"test"}
SKIP_FILES = {"package.json"}
IMAGE_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg")


def measure(web_dir):
    files = {}
    for root, dirs, names in os.walk(web_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name in SKIP_FILES:
                continue
            path = os.path.join(root, name)
            with open(path, "rb") as handle:
                data = handle.read()
            rel = os.path.relpath(path, web_dir).replace(os.sep, "/")
            files[rel] = {"bytes": len(data), "gzip_bytes": len(gzip.compress(data, 9, mtime=0))}
    text = {n: f for n, f in files.items() if not n.lower().endswith(IMAGE_EXTENSIONS)}
    images = {n: f for n, f in files.items() if n.lower().endswith(IMAGE_EXTENSIONS)}
    return {
        "files": files,
        "total_bytes": sum(f["bytes"] for f in text.values()),
        "total_gzip_bytes": sum(f["gzip_bytes"] for f in text.values()),
        "image_total_bytes": sum(f["bytes"] for f in images.values()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--web", default=os.path.join(os.path.dirname(__file__), "..", "web"))
    args = parser.parse_args(argv)
    json.dump(measure(args.web), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
