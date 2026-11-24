import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import analytics, cli

SECRET = "live_SEEDED_SECRET_123"
TOKEN = "tok_SEEDED_TOKEN_456"


class SupportBundleTests(unittest.TestCase):
    def test_config_redacts_keys_and_addresses(self):
        cfg = {"platform": "twitch", "url": "rtmp://host/app/" + SECRET,
               "backup_url": "rtmp://b/app", "api_token": TOKEN,
               "preset": "720p30", "fps": None, "note": "see " + "rtmps://x/" + SECRET}
        out = analytics.redact_config(cfg)
        text = json.dumps(out)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(TOKEN, text)
        self.assertEqual(out["preset"], "720p30")
        self.assertIsNone(out["fps"])

    def test_known_secret_is_scrubbed_from_any_field(self):
        bundle = analytics.build_support_bundle(
            "0.0", "linux", {"libx264"}, {"window": "title " + SECRET},
            [{"preset": SECRET}], known_secrets=(SECRET,))
        self.assertNotIn(SECRET, json.dumps(bundle))
        self.assertEqual(bundle["encoders"], ["libx264"])

    def test_cli_writes_bundle_without_seeded_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_file = os.path.join(tmp, "config.json")
            with open(cfg_file, "w") as fh:
                json.dump({"url": "rtmp://h/app/" + SECRET, "api_token": TOKEN,
                           "platform": "custom", "window": "Game " + SECRET}, fh)
            out_file = os.path.join(tmp, "bundle.json")
            args = cli.build_parser().parse_args(["support-bundle", "--out", out_file])
            buf = io.StringIO()
            with mock.patch.object(cli, "config_path", return_value=cfg_file):
                code = cli.cmd_support_bundle(
                    args, buf, find=lambda: "ffmpeg", probe=lambda f: {"libx264"},
                    environ={"STREAM_KEY": SECRET})
            self.assertEqual(code, 0)
            with open(out_file) as fh:
                text = fh.read()
            for secret in (SECRET, TOKEN):
                self.assertNotIn(secret, text)
                self.assertNotIn(secret, buf.getvalue())
            data = json.loads(text)
            self.assertEqual(data["encoders"], ["libx264"])
            self.assertEqual(data["config"]["platform"], "custom")

    def test_cli_survives_missing_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = os.path.join(tmp, "b.json")
            args = cli.build_parser().parse_args(["support-bundle", "--out", out_file])
            with mock.patch.object(cli, "config_path",
                                   return_value=os.path.join(tmp, "none.json")):
                code = cli.cmd_support_bundle(args, io.StringIO(), find=lambda: None,
                                              environ={})
            self.assertEqual(code, 0)
            self.assertEqual(json.load(open(out_file))["encoders"], [])


if __name__ == "__main__":
    unittest.main()
