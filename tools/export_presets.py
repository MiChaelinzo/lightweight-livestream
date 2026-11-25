"""Write web/presets.json from src/lightstream/presets.py.

    python tools/export_presets.py          # regenerate web/presets.json
    python tools/export_presets.py --check  # exit 1 if the file is stale

The Python presets are the single source of truth; the web demo only reads
the generated JSON.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lightstream.presets import DEFAULT_PRESET, PRESETS, PROFILE_ONLY_PRESETS  # noqa: E402

OUTPUT = os.path.join(ROOT, "web", "presets.json")


def build_text():
    data = {
        "default": DEFAULT_PRESET,
        "presets": [dict(p._asdict(), profile_only=p.name in PROFILE_ONLY_PRESETS)
                    for p in PRESETS.values()],
    }
    return json.dumps(data, indent=2) + "\n"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    text = build_text()
    if "--check" in args:
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = None
        if current != text:
            print("web/presets.json is stale. Run: python tools/export_presets.py")
            return 1
        print("web/presets.json is up to date.")
        return 0
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("Wrote %s" % OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
