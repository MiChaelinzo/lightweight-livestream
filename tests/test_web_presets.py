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


class DescribeCommandParsesTests(unittest.TestCase):
    def test_web_command_is_accepted_by_real_parser(self):
        import re
        from lightstream.cli import build_parser

        source = open(os.path.join(os.path.dirname(export_presets.OUTPUT), "js", "presets-logic.js"), encoding="utf-8").read()
        match = re.search(r'return "(lightstream start [^"]*?)" \+ preset\.name', source)
        self.assertIsNotNone(match)
        argv = (match.group(1) + "light").split()[1:]
        args = build_parser().parse_args(argv)
        self.assertEqual(args.platform, "twitch")
        self.assertEqual(args.preset, "light")


if __name__ == "__main__":
    unittest.main()
