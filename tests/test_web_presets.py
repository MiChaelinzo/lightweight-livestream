import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream.presets import DEFAULT_PRESET, PRESETS
from tools import export_presets


class WebPresetsParityTests(unittest.TestCase):
    def test_json_file_matches_python_presets(self):
        with open(export_presets.OUTPUT, encoding="utf-8") as f:
            on_disk = f.read()
        self.assertEqual(on_disk, export_presets.build_text(),
                         "run: python tools/export_presets.py")

    def test_json_content(self):
        data = json.loads(export_presets.build_text())
        self.assertEqual(data["default"], DEFAULT_PRESET)
        self.assertEqual([p["name"] for p in data["presets"]], list(PRESETS))

    def test_check_mode_passes_when_current(self):
        self.assertEqual(export_presets.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
