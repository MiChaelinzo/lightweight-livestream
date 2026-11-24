import io
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import bench, cli, optimizer, secure_store, wizard
from lightstream.network import Congestion
from lightstream.platforms import validate_srt_url
from lightstream.runner import redact

Done = namedtuple("Done", "returncode stdout stderr")
KEY = "live_SECRET_key_123"


class TierTests(unittest.TestCase):
    def test_every_boundary(self):
        for name, cpu, ram, speed in bench.TIERS[1:]:
            self.assertEqual(name, bench.compute_tier(cpu, ram, speed)["name"])
            below = [(cpu - 1, ram, speed), (cpu, ram - 1, speed), (cpu, ram, speed - 0.01)]
            for args in below:
                self.assertNotEqual(name, bench.compute_tier(*args)["name"], args)

    def test_floor_and_weakest_metric_wins(self):
        self.assertEqual("Low-End", bench.compute_tier(1, 512, 0.3)["name"])
        self.assertEqual("Balanced", bench.compute_tier(32, 65536, 2.0)["name"])
        self.assertEqual("Power User", bench.compute_tier(16, 32768, 10)["name"])

    def test_unmeasured_skipped_and_all_unknown_is_floor(self):
        t = bench.compute_tier(8, 16384, None)
        self.assertEqual("Creator", t["name"])
        self.assertEqual(["encode_speed"], t["skipped_metrics"])
        self.assertTrue(t["partial"])
        self.assertFalse(bench.compute_tier(8, 16384, 6.0)["partial"])
        self.assertEqual("Low-End", bench.compute_tier(None, None, None)["name"])

    def test_report_tier_reads_uncapped_speed(self):
        report = {"host": {"cpu_count": bench.metric(4), "ram_mb": bench.metric(4096)},
                  "encode": {"gaming_first_proxy": {"runs": [
                      {"label": "uncapped", "ok": True, "ffmpeg_speed": bench.metric(2.5)}]}}}
        self.assertEqual(2.5, bench.encode_speed_of(report))
        self.assertEqual("Balanced", bench.tier_of_report(report)["name"])


class HealthScoreTests(unittest.TestCase):
    def test_bands(self):
        h = optimizer.performance_health
        best = h(cpu=40, gpu=50, ram=50, network=100, encode_speed=1.2, dropped_percent=0)
        self.assertEqual((100, "Excellent"), (best.score, best.band))
        worst = h(cpu=100, gpu=100, ram=100, network=0, encode_speed=0.3, dropped_percent=9)
        self.assertEqual((0, "Critical"), (worst.score, worst.band))
        self.assertEqual("Good", h(network=80).band)       # 80
        self.assertEqual("Fair", h(network=60).band)
        self.assertEqual("Poor", h(network=40).band)
        self.assertEqual("Excellent", h(network=90).band)  # boundary
        self.assertEqual("Good", h(network=89).band)
        self.assertEqual("Critical", h(network=34).band)

    def test_unknown_left_out_and_deterministic(self):
        a = optimizer.performance_health(cpu=80, network=100)
        self.assertEqual(a, optimizer.performance_health(cpu=80, network=100))
        self.assertIn("gpu", a.skipped)
        self.assertEqual((None, None), optimizer.performance_health()[:2])


class CongestionInsightTests(unittest.TestCase):
    def test_finding_becomes_unapplied_network_insight(self):
        from lightstream.adaptive import AdaptiveAdvisor
        out = optimizer.build_insights(AdaptiveAdvisor(), {}, congestion=[
            Congestion("backpressure", "ffmpeg is slow")])
        self.assertEqual("congestion_backpressure", out[0].action)
        self.assertEqual(optimizer.AREA_NETWORK, out[0].area)


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.saved = None

    def save(self, secret):
        self.saved = secret

    def load(self):
        if self.saved is None:
            raise secure_store.NotFound("none")
        return self.saved

    def delete(self):
        self.saved = None


class SecureStoreTests(unittest.TestCase):
    def test_refuses_without_backend_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            backend = secure_store.select_backend("linux", d, which=lambda _n: None)
            self.assertIsNone(backend)
            store = secure_store.SecureKeyStore(backend)
            with self.assertRaises(secure_store.SecureStoreUnavailable):
                store.save(KEY, opt_in=True)
            self.assertEqual([], os.listdir(d))
        self.assertIsNone(secure_store.select_backend("macos", "/x", which=lambda _n: None))
        self.assertIsNone(secure_store.select_backend("plan9", "/x"))

    def test_requires_opt_in(self):
        backend = FakeBackend()
        with self.assertRaises(secure_store.OptInRequired):
            secure_store.SecureKeyStore(backend).save(KEY)
        self.assertIsNone(backend.saved)

    def test_roundtrip_and_validation(self):
        store = secure_store.SecureKeyStore(FakeBackend())
        store.save(KEY, opt_in=True)
        self.assertEqual(KEY, store.load())
        store.forget()
        with self.assertRaises(secure_store.NotFound):
            store.load()
        for bad in ("", "  ", "a\nb"):
            with self.assertRaises(ValueError):
                store.save(bad, opt_in=True)

    def test_secret_tool_uses_stdin_not_argv(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return Done(0, KEY + "\n", "")
        backend = secure_store.SecretToolBackend(run)
        backend.save(KEY)
        argv, kw = calls[0]
        self.assertNotIn(KEY, " ".join(argv))
        self.assertEqual(KEY + "\n", kw["input"])
        self.assertEqual(KEY, backend.load())
        self.assertEqual("secret-tool", secure_store.select_backend(
            "linux", "/x", which=lambda _n: "/usr/bin/secret-tool").name)

    def test_secret_tool_failure_is_error_without_secret(self):
        backend = secure_store.SecretToolBackend(lambda a, **k: Done(1, "", ""))
        with self.assertRaises(secure_store.SecureStoreError) as ctx:
            backend.save(KEY)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_mac_keychain_stdin_script(self):
        calls = []
        backend = secure_store.MacKeychainBackend(
            lambda a, **k: calls.append((a, k)) or Done(0, KEY, ""))
        backend.save(KEY)
        self.assertNotIn(KEY, " ".join(calls[0][0]))
        self.assertIn(KEY, calls[0][1]["input"])
        with self.assertRaises(ValueError):
            backend.save('a"b')

    def test_dpapi_blob_is_private_and_not_plaintext(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "blob")
            backend = secure_store.DpapiBackend(
                path, protect=lambda b: b[::-1], unprotect=lambda b: b[::-1])
            backend.save(KEY)
            with open(path) as fh:
                self.assertNotIn(KEY, fh.read())
            if os.name == "posix":
                self.assertEqual(0o600, os.stat(path).st_mode & 0o777)
            self.assertEqual(KEY, backend.load())
            backend.delete()
            with self.assertRaises(secure_store.NotFound):
                backend.load()

    def test_cli_key_save_refuses_and_never_touches_config(self):
        class Args:
            action = "save"
            yes = True
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "config.json")
            store = secure_store.SecureKeyStore(None)
            self.assertEqual(1, cli.cmd_key(Args, out, store=store, prompt=lambda _p: KEY))
            self.assertFalse(os.path.exists(cfg))
        self.assertNotIn(KEY, out.getvalue())
        self.assertIn("NOT saved", out.getvalue())
        Args.yes = False
        out = io.StringIO()
        fake = FakeBackend()
        self.assertEqual(1, cli.cmd_key(Args, out, store=secure_store.SecureKeyStore(fake),
                                        prompt=lambda _p: KEY))
        self.assertIsNone(fake.saved)


class SrtOptionTests(unittest.TestCase):
    def test_passphrase_validated(self):
        validate_srt_url("srt://h:9000?passphrase=" + "a" * 10)
        for bad in ("short", "a" * 80):
            with self.assertRaises(ValueError):
                validate_srt_url("srt://h:9000?passphrase=" + bad)
        with self.assertRaises(ValueError):
            validate_srt_url("srt://h:9000?pbkeylen=20")
        validate_srt_url("srt://h:9000?passphrase=" + "a" * 10 + "&pbkeylen=32")

    def test_passphrase_redacted_in_logs(self):
        text = redact("srt://h:9000?passphrase=hunter2hunter2&x=1", None)
        self.assertNotIn("hunter2", text)
        self.assertIn("x=1", text)

    def test_passphrase_reaches_argv(self):
        from lightstream.platforms import ingest_url
        url = ingest_url("custom", "k", "srt://h:9000?passphrase=" + "a" * 10)
        self.assertIn("passphrase=" + "a" * 10, url)


class OptimizeTests(unittest.TestCase):
    FACTS = wizard.ReadinessFacts(True, "libx264", False, 4096, 2, None, None, False)

    def _run(self, answer, yes=False, cpu=2, ram=2048, tier=None):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as fh:
            json.dump({"platform": "youtube", "preset": "balanced"}, fh)
        before = open(path).read()
        out = io.StringIO()
        wizard.run_optimize(
            "linux", out, input_fn=lambda _p: answer, yes=yes, cpu_count=cpu,
            ram_mb=ram, run=lambda *a, **k: Done(1, "", ""), path=path,
            find=lambda: None, tier_fn=lambda: tier)
        return before, open(path).read(), out.getvalue()

    def test_no_change_without_confirmation(self):
        for answer in ("", "n", "no"):
            before, after, out = self._run(answer)
            self.assertEqual(before, after)
            self.assertIn("Config unchanged", out)

    def test_applies_after_yes_and_potato_fallback(self):
        before, after, out = self._run("y")
        self.assertNotEqual(before, after)
        self.assertEqual("potato_2000", json.loads(after)["profile"])
        self.assertIn("Potato fallback", out)

    def test_yes_flag_confirms_and_key_never_written(self):
        _, after, _ = self._run("", yes=True)
        self.assertNotIn("key", " ".join(json.loads(after)).lower().replace("keyint", ""))

    def test_strong_pc_no_potato(self):
        _, after, _ = self._run("y", cpu=16, ram=32768, tier="Creator")
        self.assertNotIn("profile", json.loads(after))

    def test_low_end_tier_forces_potato(self):
        prop = wizard.propose_optimization({}, "", 8, 16384, None, "twitch",
                                           self.FACTS, tier="Low-End")
        self.assertEqual("potato", prop.config["profile"])

    def test_gui_proposal_does_not_write(self):
        from lightstream import gui_controller as gc
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            prop, message = gc.optimize_proposal(
                cpu_count=2, ram_mb=1024, gpu_text="", facts=self.FACTS, current={})
            self.assertFalse(os.path.exists(path))
            self.assertIn("profile", message)
            gc.apply_optimization(prop, path=path)
            self.assertEqual("potato_2000", json.load(open(path))["profile"])


if __name__ == "__main__":
    unittest.main()
