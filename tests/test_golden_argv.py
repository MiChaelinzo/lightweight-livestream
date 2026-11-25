"""Golden ffmpeg argv per performance profile and hardware profile.

Each file in tests/golden/ holds the exact argv build_command returns for a
fixed config, so an accidental change to a command shows up as a diff. The key
is a placeholder, never a real one. After an intended change, regenerate with:

    LIGHTSTREAM_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden_argv

and review the diff in git before committing.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream.command import build_command
from lightstream.config import resolve_settings
from lightstream.hardware import PROFILES
from lightstream.perf_profiles import PERF_PROFILES

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
UPDATE_ENV = "LIGHTSTREAM_UPDATE_GOLDEN"
FAKE_KEY = "FAKE-KEY-PLACEHOLDER"
CPU_COUNT = 8        # fixed so thread math does not depend on the test machine
OS_NAME = "linux"


def _argv(cli, encoder):
    settings = resolve_settings(cli, {}, cpu_count=CPU_COUNT)
    return build_command(settings, FAKE_KEY, OS_NAME, encoder, ffmpeg="ffmpeg")


def _cases():
    for name in sorted(PERF_PROFILES):
        yield "perf_%s" % name, {"profile": name}, "libx264"
    for name in sorted(PROFILES):
        yield "hardware_%s" % name, {"hardware": name}, PROFILES[name].encoder_order[0]


class GoldenArgvTests(unittest.TestCase):
    def _check(self, label, cli, encoder):
        argv = _argv(cli, encoder)
        path = os.path.join(GOLDEN_DIR, label + ".json")
        if os.environ.get(UPDATE_ENV):
            os.makedirs(GOLDEN_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(argv, fh, indent=2)
                fh.write("\n")
        self.assertTrue(os.path.exists(path),
                        "missing %s; regenerate with %s=1" % (path, UPDATE_ENV))
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), argv,
                             "argv drifted for %s; if intended, regenerate with %s=1"
                             % (label, UPDATE_ENV))

    def test_every_profile_matches_its_golden_file(self):
        for label, cli, encoder in _cases():
            with self.subTest(label):
                self._check(label, cli, encoder)

    def test_every_profile_has_a_case(self):
        labels = {label for label, _, _ in _cases()}
        for name in PERF_PROFILES:
            self.assertIn("perf_%s" % name, labels)
        for name in PROFILES:
            self.assertIn("hardware_%s" % name, labels)

    def test_no_stray_golden_files(self):
        expected = {label + ".json" for label, _, _ in _cases()}
        self.assertEqual(set(os.listdir(GOLDEN_DIR)), expected)


if __name__ == "__main__":
    unittest.main()
