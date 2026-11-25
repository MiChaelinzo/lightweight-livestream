import io
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import bench, cli, wizard

Done = namedtuple("Done", "returncode stdout")


class FakeClock:
    def __init__(self, step=0.5):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


def fake_run(argv, **kw):
    code = argv[2] if len(argv) > 2 else ""
    if argv[1:] == ["-hide_banner", "-encoders"]:
        return Done(0, " V....D libx264              H.264\n V....D h264_nvenc    NVENC\n")
    if "-frames:v" in argv:  # encoder_works probe: nvenc fails
        return Done(1 if "h264_nvenc" in argv else 0, "")
    if "bench." in code:
        return Done(0, json.dumps({"rss_before_mb": 20.0, "rss_after_mb": 21.0, "ticks": 5}))
    if "rss" in code:
        return Done(0, json.dumps({"rss_mb": 20.0}))
    return Done(0, "")


def fake_spawn(argv):
    ok = "-threads" not in argv or argv[argv.index("-threads") + 1] != "99"
    return bench.EncodeResult(0 if ok else 1, 2.0, 4.0, 3.0, 50.0, None if ok else "boom")


class MetricTests(unittest.TestCase):
    def test_unavailable_has_reason(self):
        m = bench.metric(None, "needs /proc")
        self.assertEqual(m, {"value": None, "status": "unavailable", "reason": "needs /proc"})
        self.assertEqual(bench.metric(0)["status"], "measured")  # zero is a value

    def test_parse_speed(self):
        self.assertEqual(bench.parse_speed("speed=12.5x\n"), 12.5)
        self.assertIsNone(bench.parse_speed("speed=N/A\n"))
        self.assertIsNone(bench.parse_speed("fps=30\n"))

    def test_read_rss_unreadable(self):
        def broken(_path):
            raise OSError("no /proc")
        self.assertIsNone(bench.read_rss_mb(broken))
        self.assertEqual(bench.read_rss_mb(lambda p: "VmRSS:\t2048 kB\n"), 2.0)


class StartupTests(unittest.TestCase):
    def test_median_and_rss_with_injected_run(self):
        result = bench.measure_startup(python="py", runs=3, run=fake_run, clock=FakeClock())
        self.assertEqual(result["import_cli_ms_median"]["value"], 500.0)
        self.assertEqual(result["rss_after_import_mb"]["value"], 20.0)

    def test_failed_child_is_unavailable(self):
        result = bench.measure_startup(python="py", runs=2,
                                       run=lambda *a, **k: Done(1, ""), clock=FakeClock())
        self.assertEqual(result["import_cli_ms_median"]["status"], "unavailable")
        self.assertEqual(result["rss_after_import_mb"]["status"], "unavailable")


class CostTests(unittest.TestCase):
    def test_tick_cost_uses_clock_and_count(self):
        ticks = iter([0.0, 0.002])
        calls = []
        result = bench.measure_tick_costs(
            ticks=4, cpu_clock=lambda: next(ticks),
            components=(("x", lambda: calls.append(1)),))
        self.assertEqual(len(calls), 4)
        self.assertAlmostEqual(result["cpu_microseconds_per_call"]["x"]["value"], 500.0)

    def test_real_components_run(self):
        result = bench.measure_tick_costs(ticks=3)
        self.assertEqual(set(result["cpu_microseconds_per_call"]),
                         {"parse_progress", "health_tracker_update",
                          "adaptive_advisor_observe", "telemetry_sampler_tick",
                          "optimizer_build_insights", "autoscaler_update"})

    def test_command_build_covers_every_profile(self):
        from lightstream.perf_profiles import PERF_PROFILES
        result = bench.measure_command_build(repeats=2, cpu_count=4)
        self.assertEqual(set(result["cpu_microseconds_per_build"]), set(PERF_PROFILES))

    def test_workload_rss_runs(self):
        data = bench.tick_workload_rss(3)
        self.assertEqual(data["ticks"], 3)


class EncodeTests(unittest.TestCase):
    def test_argv_shape(self):
        argv = bench.encode_argv("ff", "libx264", "balanced", 5, 3)
        self.assertIn("testsrc2=size=1280x720:rate=30", argv)
        self.assertEqual(argv[argv.index("-t") + 1], "5")
        self.assertEqual(argv[argv.index("-threads") + 1], "3")
        self.assertEqual(argv[-3:], ["-f", "null", "-"])
        self.assertNotIn("-threads", bench.encode_argv("ff", "libx264", "balanced", 5))

    def test_measure_encodes_with_fake_spawn(self):
        section = bench.measure_encodes("ff", seconds=2, cpu_count=8, spawn=fake_spawn,
                                        run=fake_run)
        self.assertEqual(section["status"], "measured")
        first = section["software_profiles"][0]
        self.assertEqual(first["cpu_seconds_per_stream_second"]["value"], 1.5)
        self.assertEqual(section["hardware_encoders"]["listed_by_ffmpeg"], ["h264_nvenc"])
        self.assertEqual(section["hardware_encoders"]["test_encode_works"], [])
        labels = [r["label"] for r in section["gaming_first_proxy"]["runs"]]
        self.assertEqual(labels[0], "uncapped")
        self.assertIn("NOT game FPS", section["gaming_first_proxy"]["proxy_note"])

    def test_failed_encode_is_unavailable_not_zero(self):
        entry = bench._encode_entry("x", "libx264", "balanced", 2, 99,
                                    bench.encode_argv("ff", "libx264", "balanced", 2, 99),
                                    fake_spawn)
        self.assertFalse(entry["ok"])
        self.assertEqual(entry["child_cpu_seconds"]["status"], "unavailable")
        self.assertIn("boom", entry["child_cpu_seconds"]["reason"])

    def test_no_wait4_gives_unavailable_cpu(self):
        class Proc:
            pid = 1
            stdout = iter(["speed=2.0x\n"])

            def wait(self):
                return 0
        res = bench.spawn_encode(["x"], popen=lambda *a, **k: Proc(), wait4=None)
        self.assertIsNone(res.cpu_seconds)
        self.assertEqual(res.speed, 2.0)


class ReportTests(unittest.TestCase):
    def build(self, ffmpeg):
        return bench.build_report(ffmpeg=ffmpeg, seconds=2, ticks=2, import_runs=1,
                                  cpu_count=8, run=fake_run, spawn=fake_spawn)

    def test_schema_and_no_secrets(self):
        report = self.build("/secret/place/ffmpeg")
        for key in ("bench_version", "date", "caveat", "host", "startup", "tick_memory",
                    "tick_costs", "command_build", "encode"):
            self.assertIn(key, report)
        text = json.dumps(report)
        self.assertNotIn("/secret/place", text)
        self.assertNotIn(bench.SYNTHETIC_KEY, text)
        self.assertNotIn("rtmp", text)
        self.assertEqual(report["host"]["cpu_count"]["value"], 8)

    def test_without_ffmpeg_encode_unavailable(self):
        self.assertEqual(self.build(None)["encode"]["status"], "unavailable")

    def test_write_report_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = bench.write_report({"a": 1}, bench.report_path("2025-01-01", d))
            self.assertEqual(json.load(open(path)), {"a": 1})
            self.assertTrue(path.endswith("bench-2025-01-01.json"))

    def test_cli_bench_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            target = os.path.join(d, "r.json")
            args = cli.build_parser().parse_args(["bench", "--out", target])
            code = cli.cmd_bench(args, out, build=lambda **kw: {"date": "d", "caveat": "c"},
                                 find=lambda: None)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(target))
            self.assertIn("encode skipped", out.getvalue())

    def test_cli_bench_rejects_zero_seconds(self):
        args = cli.build_parser().parse_args(["bench", "--seconds", "0"])
        with self.assertRaises(ValueError):
            cli.cmd_bench(args, io.StringIO())


@unittest.skipUnless(os.environ.get("LIGHTSTREAM_TEST_FFMPEG"), "needs a real ffmpeg")
class RealFfmpegTests(unittest.TestCase):
    def test_two_second_encode(self):
        ffmpeg = os.environ["LIGHTSTREAM_TEST_FFMPEG"]
        result = bench.spawn_encode(bench.encode_argv(ffmpeg, "libx264", "potato", 2))
        self.assertEqual(result.returncode, 0, result.error)
        self.assertIsNotNone(result.speed)


class ReadinessTests(unittest.TestCase):
    def facts(self, **kw):
        base = dict(ffmpeg_found=True, encoder="libx264", encoder_is_hardware=False,
                    ram_mb=16000, cpu_count=8, upload_kbps=10000, latency_ms=20.0,
                    latency_checked=True)
        base.update(kw)
        return wizard.ReadinessFacts(**base)

    def test_perfect_hardware_is_100(self):
        report = wizard.readiness_report(
            self.facts(encoder="h264_nvenc", encoder_is_hardware=True))
        self.assertEqual(report.score, 100)

    def test_factor_points_sum_to_100_possible(self):
        report = wizard.readiness_report(self.facts())
        self.assertEqual(sum(f.max_points for f in report.factors), 100)

    def test_missing_ffmpeg_loses_points_and_explains(self):
        report = wizard.readiness_report(self.facts(ffmpeg_found=False, encoder=None))
        self.assertLess(report.score, 60)
        ff = next(f for f in report.factors if f.name == "ffmpeg")
        self.assertEqual(ff.points, 0)
        self.assertIn("Install ffmpeg", ff.fix)

    def test_unmeasured_factors_are_skipped_not_zero(self):
        report = wizard.readiness_report(self.facts(upload_kbps=None, latency_checked=False,
                                                    latency_ms=None))
        skipped = [f.name for f in report.factors if not f.known]
        self.assertEqual(skipped, ["upload speed", "connection"])
        self.assertEqual(report.score, round(100 * 67 / 75))

    def test_failed_connection_scores_zero_for_it(self):
        report = wizard.readiness_report(self.facts(latency_ms=None))
        conn = next(f for f in report.factors if f.name == "connection")
        self.assertTrue(conn.known)
        self.assertEqual(conn.points, 0)

    def test_deterministic_and_lines(self):
        a = wizard.readiness_lines(wizard.readiness_report(self.facts()))
        b = wizard.readiness_lines(wizard.readiness_report(self.facts()))
        self.assertEqual(a, b)
        self.assertTrue(a[0].startswith("Stream readiness: "))

    def test_gather_uses_injected_socket_and_run(self):
        class Sock:
            def close(self):
                pass
        clock_values = iter([1.0, 1.05])
        import lightstream.bandwidth as bw
        real = bw.measure_connect_latency
        bw.measure_connect_latency = lambda host, port, connect: real(
            host, port, connect=connect, clock=lambda: next(clock_values))
        try:
            facts = wizard.gather_readiness_facts(
                "linux", 4, 8192, 5000, ffmpeg="ff", latency_target=("h", 1935),
                run=fake_run, connect=lambda addr, timeout: Sock())
        finally:
            bw.measure_connect_latency = real
        self.assertTrue(facts.latency_checked)
        self.assertAlmostEqual(facts.latency_ms, 50.0)
        self.assertEqual(facts.encoder, "libx264")
        self.assertFalse(facts.encoder_is_hardware)

    def test_gather_failed_connect_and_no_ffmpeg(self):
        def refuse(addr, timeout):
            raise OSError("refused")
        facts = wizard.gather_readiness_facts(
            "linux", 4, 8192, None, latency_target=("h", 1), find=lambda: None,
            connect=refuse)
        self.assertFalse(facts.ffmpeg_found)
        self.assertIsNone(facts.encoder)
        self.assertTrue(facts.latency_checked)
        self.assertIsNone(facts.latency_ms)

    def test_cli_readiness_output_has_no_url_path(self):
        class Sock:
            def close(self):
                pass
        out = io.StringIO()
        args = cli.build_parser().parse_args(
            ["readiness", "--ffmpeg", "ff", "--url", "rtmp://ingest.example:1935/app/KEY123",
             "--upload-mbps", "5"])
        code = cli.cmd_readiness(args, out, run=fake_run,
                                 connect=lambda a, t: Sock(), find=lambda: None)
        self.assertEqual(code, 0)
        self.assertIn("Stream readiness:", out.getvalue())
        self.assertNotIn("KEY123", out.getvalue())

    def test_setup_prints_score(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            wizard.run_setup("linux", out, yes=True, cpu_count=4, ram_mb=8192,
                             run=fake_run, path=os.path.join(d, "c.json"),
                             find=lambda: None)
            self.assertIn("Stream readiness:", out.getvalue())

    def test_one_click_setup_message_has_score(self):
        from lightstream import gui_controller as gc
        facts = self.facts()
        _fields, message = gc.one_click_setup(os_name="linux", cpu_count=4, ram_mb=8192,
                                              gpu_text="", facts=facts)
        self.assertIn("Stream readiness: %d/100" % wizard.readiness_report(facts).score,
                      message)


if __name__ == "__main__":
    unittest.main()
