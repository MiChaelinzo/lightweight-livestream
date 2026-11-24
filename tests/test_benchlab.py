"""tools/benchlab.py: pure parsers, fake-clock sampling and real processes."""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import benchlab  # noqa: E402

FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")
HAVE_PROC = benchlab.proc_available()
BUSY = ("import sys, time\n"
        "print('ready', flush=True)\n"
        "end = time.time() + 30\n"
        "while time.time() < end:\n"
        "    sum(range(10000))\n")

STAT = "4242 (my (odd) app) S 1 4242 4242 0 -1 4194560 100 0 0 0 70 30 0 0 20 0 1 0 1 1000 50"
STATUS = "Name:\tapp\nVmPeak:\t 9000 kB\nVmRSS:\t 2048 kB\nThreads:\t1\n"


class ParserCase(unittest.TestCase):
    def test_stat_ticks_with_parentheses_in_name(self):
        self.assertEqual(benchlab.parse_stat_ticks(STAT), 100)

    def test_status_rss(self):
        self.assertEqual(benchlab.parse_status_rss_bytes(STATUS), 2048 * 1024)
        self.assertIsNone(benchlab.parse_status_rss_bytes("Name:\tkthread\n"))

    def test_cpu_percent(self):
        self.assertEqual(benchlab.cpu_percent(0, 100, 2.0, 100), 50.0)
        self.assertEqual(benchlab.cpu_percent(0, 100, 0, 100), 0.0)

    def test_summarize(self):
        samples = [{"cpu_percent": None, "rss_bytes": 1048576},
                   {"cpu_percent": 10.0, "rss_bytes": 3145728},
                   {"cpu_percent": 30.0, "rss_bytes": 2097152}]
        self.assertEqual(benchlab.summarize(samples), {
            "samples": 3, "cpu_percent_avg": 20.0, "cpu_percent_max": 30.0,
            "rss_mb_avg": 2.0, "rss_mb_peak": 3.0})
        self.assertIsNone(benchlab.summarize([])["cpu_percent_avg"])

    def test_parse_target(self):
        self.assertEqual(benchlab.parse_target("OBS Studio:12", False), ("OBS Studio", 12))
        self.assertEqual(benchlab.parse_target("ff:ffmpeg -i 'a b'", True),
                         ("ff", ["ffmpeg", "-i", "a b"]))
        for bad in ("nolabel", ":5", "x:", "x:abc"):
            with self.assertRaises(ValueError):
                benchlab.parse_target(bad, False)


class SamplingCase(unittest.TestCase):
    def test_fake_clock_sampling(self):
        now = [0.0]
        reads = iter([(0, 1048576), (100, 2097152), (300, 3145728), None])

        def sleep(seconds):
            now[0] += seconds

        samples = benchlab.sample_pid(1, duration=10, interval=1, read=lambda pid: next(reads),
                                      clock=lambda: now[0], sleep=sleep, ticks_per_second=100)
        self.assertEqual([s["cpu_percent"] for s in samples], [None, 100.0, 200.0])
        self.assertEqual(samples[-1]["rss_bytes"], 3145728)

    def test_missing_pid_gives_no_samples(self):
        self.assertEqual(benchlab.sample_pid(1, 1, 1, read=lambda pid: None), [])


class ReportCase(unittest.TestCase):
    def report(self, system="Linux"):
        target = {"label": "dummy", "kind": "pid", "pid": 1, "startup_s": benchlab.UNKNOWN,
                  "result": benchlab.summarize([{"cpu_percent": 5.0, "rss_bytes": 1048576}])}
        return benchlab.build_report([target], 2.0, 1.0, system, 4)

    def test_competitors_are_unknown_by_default(self):
        report = self.report()
        for name in ("OBS Studio", "Streamlabs Desktop"):
            self.assertEqual(set(report["competitors"][name].values()), {"UNKNOWN"})

    def test_measured_competitor_replaces_unknown_column(self):
        target = {"label": "obs studio", "kind": "pid", "pid": 1, "startup_s": "UNKNOWN",
                  "result": benchlab.summarize([])}
        report = benchlab.build_report([target], 2.0, 1.0, "Linux", 4)
        self.assertNotIn("OBS Studio", report["competitors"])
        self.assertIn("Streamlabs Desktop", report["competitors"])

    def test_markdown_table(self):
        text = benchlab.build_markdown(self.report())
        self.assertIn("| Metric | dummy | OBS Studio | Streamlabs Desktop |", text)
        self.assertIn("| CPU avg (% of one core) | 5.0 | UNKNOWN | UNKNOWN |", text)
        self.assertNotIn("—", text)

    def test_non_linux_is_labelled_unverified(self):
        self.assertTrue(any("UNVERIFIED" in n for n in self.report("Windows")["notes"]))


@unittest.skipUnless(HAVE_PROC, "needs /proc")
class RealProcessCase(unittest.TestCase):
    def test_sample_own_process(self):
        result = benchlab.measure_pid("self", os.getpid(), 0.5, 0.1)["result"]
        self.assertTrue(result["pid_found"])
        self.assertGreater(result["rss_mb_peak"], 1)

    def test_unknown_pid(self):
        target = benchlab.measure_pid("none", 2 ** 22 + 12345, 0.2, 0.1)
        self.assertFalse(target["result"]["pid_found"])

    def test_dummy_command_startup_cpu_and_cleanup(self):
        argv = [sys.executable, "-c", BUSY]
        target = benchlab.measure_command("dummy", argv, 1.0, 0.2, "ready")
        self.assertIsInstance(target["startup_s"], float)
        self.assertGreater(target["result"]["cpu_percent_avg"], 20.0)
        self.assertGreater(target["result"]["rss_mb_peak"], 1.0)
        self.assertFalse(os.path.exists("/proc/%d" % target["pid"]) and
                         _is_running(target["pid"]))

    def test_command_without_ready_text_has_unknown_startup(self):
        target = benchlab.measure_command("d", [sys.executable, "-c", BUSY], 0.5, 0.1, None)
        self.assertEqual(target["startup_s"], "UNKNOWN")

    @unittest.skipUnless(FFMPEG and os.path.exists(FFMPEG), "LIGHTSTREAM_TEST_FFMPEG not set")
    def test_ffmpeg_is_measured(self):
        argv = [FFMPEG, "-hide_banner", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
                "-f", "null", "-"]
        target = benchlab.measure_command("ffmpeg", argv, 2.0, 0.5, "frame=")
        self.assertTrue(target["result"]["pid_found"])
        self.assertGreater(target["result"]["rss_mb_peak"], 5.0)
        self.assertIsInstance(target["startup_s"], float)

    def test_cli_json_and_markdown(self):
        out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "benchlab-test-%d" % os.getpid())
        done = subprocess.run(
            [sys.executable, benchlab.__file__, "--pid", "self:%d" % os.getpid(),
             "--duration", "0.3", "--interval", "0.1", "--out", out + ".json",
             "--markdown", out + ".md"], capture_output=True, text=True, timeout=30)
        try:
            self.assertEqual(done.returncode, 0, done.stderr)
            report = json.loads(done.stdout)
            self.assertEqual(report["competitors"]["OBS Studio"]["rss_mb_peak"], "UNKNOWN")
            with open(out + ".md", encoding="utf-8") as fh:
                self.assertIn("| Metric |", fh.read())
        finally:
            for ext in (".json", ".md"):
                if os.path.exists(out + ext):
                    os.remove(out + ext)

    def test_cli_needs_a_target(self):
        self.assertEqual(benchlab.main([]), 2)


def _is_running(pid):
    try:
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


if __name__ == "__main__":
    unittest.main()
