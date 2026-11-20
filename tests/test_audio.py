import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import audio
from lightstream.command import build_command
from lightstream.config import resolve_settings


class NoiseFilterTests(unittest.TestCase):
    def test_off_adds_nothing(self):
        self.assertEqual([], audio.noise_filter_args("off"))

    def test_light_chain_has_no_model(self):
        self.assertEqual(["-af", "highpass=f=80,afftdn=nr=10:nf=-45"],
                         audio.noise_filter_args("light"))

    def test_ai_uses_arnndn_with_escaped_windows_path(self):
        self.assertEqual(["-af", "arnndn=m=C\\:/models/bd.rnnn"],
                         audio.noise_filter_args("ai", "C:\\models\\bd.rnnn"))

    def test_ai_needs_model_and_safe_path(self):
        with self.assertRaises(ValueError):
            audio.noise_filter_args("ai")
        with self.assertRaises(ValueError):
            audio.noise_filter_args("ai", "/tmp/a,b.rnnn")

    def test_unknown_level(self):
        with self.assertRaises(ValueError):
            audio.noise_filter_args("loud")

    def test_require_model_file(self):
        with tempfile.NamedTemporaryFile(suffix=".rnnn") as fh:
            audio.require_model_file(fh.name)
        with self.assertRaises(ValueError):
            audio.require_model_file("/nonexistent/model.rnnn")
        with self.assertRaises(ValueError):
            audio.require_model_file(None)

    def test_settings_validate_noise(self):
        with self.assertRaises(ValueError):
            resolve_settings({"noise": "loud"}, {})
        with self.assertRaises(ValueError):
            resolve_settings({"noise": "ai", "noise_model": "/nonexistent.rnnn"}, {})
        with tempfile.NamedTemporaryFile(suffix=".rnnn") as fh:
            s = resolve_settings({"noise": "ai", "noise_model": fh.name}, {})
            argv = build_command(s, "K", "linux", "libx264")
            self.assertIn("arnndn=m=" + fh.name, argv)

    def test_noise_in_command_precedes_encoder(self):
        s = resolve_settings({"noise": "light"}, {})
        argv = build_command(s, "K", "linux", "libx264")
        self.assertLess(argv.index("-af"), argv.index("-c:v"))


if __name__ == "__main__":
    unittest.main()
