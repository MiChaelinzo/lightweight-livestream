import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import wizard

KEY = "live_SECRET_key_123"
INTEL = "Name\nIntel(R) HD Graphics 620\n"
MX = "Name\nNVIDIA GeForce MX250\nIntel(R) UHD Graphics 620\n"


class BuildTests(unittest.TestCase):
    def test_intel_hd_low_end(self):
        cfg = wizard.build_recommended_config(INTEL, 2, 4096, None, "twitch")
        self.assertEqual(cfg["hardware"], "intel_hd")
        self.assertEqual(cfg["preset"], "potato")
        self.assertEqual(cfg["noise"], "light")
        self.assertNotIn("scene", cfg)

    def test_mx250(self):
        cfg = wizard.build_recommended_config(MX, 4, 8192, None, "youtube")
        self.assertEqual(cfg["hardware"], "nvidia_mx")
        self.assertEqual(cfg["preset"], "light")

    def test_low_ram_caps_preset(self):
        cfg = wizard.build_recommended_config(MX, 8, 2048, None, "twitch")
        self.assertEqual(cfg["preset"], "light")

    def test_intel_hd_caps_strong_cpu(self):
        cfg = wizard.build_recommended_config(INTEL, 16, 16000, None, "twitch")
        self.assertEqual(cfg["preset"], "light")

    def test_upload_limits_preset_and_sets_bitrate(self):
        cfg = wizard.build_recommended_config(MX, 8, 8192, 800, "twitch")
        self.assertEqual(cfg["preset"], "potato")
        self.assertEqual(cfg["bitrate"], 496)

    def test_unknown_inputs(self):
        cfg = wizard.build_recommended_config("", None, None, None, "twitch")
        self.assertEqual(cfg["hardware"], "generic")
        self.assertEqual(cfg["preset"], "potato")
        with self.assertRaises(ValueError):
            wizard.build_recommended_config("", 4, 4096, None, "nowhere")

    def test_deterministic(self):
        a = wizard.build_recommended_config(MX, 4, 8192, 5000, "twitch")
        b = wizard.build_recommended_config(MX, 4, 8192, 5000, "twitch")
        self.assertEqual(a, b)


class RamTests(unittest.TestCase):
    def test_linux_meminfo(self):
        opener = lambda path, mode: io.StringIO("MemTotal:  4194304 kB\n")
        self.assertEqual(wizard.detect_ram_mb("linux", opener=opener), 4096)

    def test_unreadable(self):
        def opener(path, mode):
            raise OSError("no")
        self.assertIsNone(wizard.detect_ram_mb("linux", opener=opener))
        self.assertIsNone(wizard.detect_ram_mb("macos"))

    def test_windows_probe_injected(self):
        self.assertEqual(wizard.detect_ram_mb("windows", windows_probe=lambda: 8000),
                         8000)


class FakeRun:
    def __init__(self, text):
        self.text = text

    def __call__(self, cmd, **kw):
        class R:
            stdout = self.text
        return R()


class SetupTests(unittest.TestCase):
    def run_setup(self, answers=(), **kw):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "lightstream", "config.json")
        out = io.StringIO()
        answers = iter(answers)
        calls = []

        def input_fn(prompt):
            calls.append(prompt)
            return next(answers)

        code = wizard.run_setup("windows", out, input_fn=input_fn, path=path,
                                cpu_count=4, ram_mb=8192, run=FakeRun(MX), **kw)
        return code, path, out.getvalue(), calls

    def test_yes_asks_nothing_and_saves_no_key(self):
        os.environ["STREAM_KEY"] = KEY
        try:
            code, path, text, calls = self.run_setup(yes=True)
        finally:
            del os.environ["STREAM_KEY"]
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        saved = open(path, encoding="utf-8").read()
        self.assertNotIn(KEY, saved)
        self.assertNotIn(KEY, text)
        for name in json.loads(saved):
            self.assertNotIn("key", name.lower())

    def test_at_most_two_questions(self):
        code, path, text, calls = self.run_setup(answers=["youtube", "5"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.load(open(path))["platform"], "youtube")

    def test_existing_keys_preserved(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.json")
        with open(path, "w") as fh:
            json.dump({"window": "Game", "preset": "balanced"}, fh)
        wizard.save_config(path, {"preset": "light"})
        data = json.load(open(path))
        self.assertEqual(data, {"window": "Game", "preset": "light"})


if __name__ == "__main__":
    unittest.main()
