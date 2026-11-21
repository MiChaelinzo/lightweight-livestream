import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import telemetry
from lightstream.telemetry import HISTORY_LIMIT, TelemetrySampler

STAT_1 = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 1 1 1 1 0 0 0 0 0\n"
STAT_2 = "cpu  200 0 200 1400 200 0 0 0 0 0\n"
MEMINFO = "MemTotal:       8000000 kB\nMemFree: 100 kB\nMemAvailable:   2000000 kB\n"
STATUS = "Name:\tffmpeg\nVmRSS:\t   204800 kB\n"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def linux_files(stat=STAT_1):
    return {"/proc/stat": stat, "/proc/meminfo": MEMINFO,
            "/proc/42/status": STATUS,
            "/sys/class/hwmon/hwmon1/name": "coretemp\n",
            "/sys/class/hwmon/hwmon1/temp1_input": "55000\n",
            "/sys/class/thermal/thermal_zone0/type": "x86_pkg_temp\n",
            "/sys/class/thermal/thermal_zone0/temp": "61000\n"}


def make(files, clock=None, **kw):
    def read_text(path):
        if path not in files:
            raise FileNotFoundError(path)
        return files[path]

    def find(pattern):
        prefix = pattern.split("*")[0]
        suffix = pattern.rsplit("*", 1)[1]
        return sorted(p for p in files if p.startswith(prefix) and p.endswith(suffix))
    kw.setdefault("which", lambda name: None)
    return TelemetrySampler("linux", clock or FakeClock(), read_text, find, **kw)


class ParseTests(unittest.TestCase):
    def test_meminfo(self):
        percent, used_mb = telemetry.parse_meminfo(MEMINFO)
        self.assertAlmostEqual(75.0, percent)
        self.assertAlmostEqual(6000000 / 1024, used_mb)

    def test_bad_text_raises_value_error(self):
        with self.assertRaises(ValueError):
            telemetry.parse_proc_stat("nothing here")
        with self.assertRaises(ValueError):
            telemetry.parse_vmrss_mb("Name: x")


class LinuxSamplerTests(unittest.TestCase):
    def test_first_tick_has_no_cpu_delta_then_percent(self):
        files = linux_files()
        sampler = make(files, pid=42)
        first = sampler.tick()
        self.assertIsNone(first.cpu_percent)
        self.assertIn("cpu_percent", sampler.unavailable)
        files["/proc/stat"] = STAT_2
        second = sampler.tick()
        # busy 200->400, total 1000->2000: 200 of 1000 jiffies
        self.assertAlmostEqual(20.0, second.cpu_percent)
        self.assertAlmostEqual(75.0, second.ram_percent)
        self.assertAlmostEqual(200.0, second.process_rss_mb)
        self.assertEqual(61.0, second.cpu_temp_c)  # hottest sensor

    def test_missing_sources_become_none_with_reason(self):
        sampler = make({})
        sample = sampler.tick()
        self.assertEqual(telemetry.UNKNOWN_SAMPLE, sample)
        self.assertIn("FileNotFoundError", sampler.unavailable["ram_percent"])
        self.assertIn("gpu_percent", sampler.unavailable)

    def test_history_is_bounded(self):
        sampler = make(linux_files())
        for _ in range(HISTORY_LIMIT + 10):
            sampler.tick()
        self.assertEqual(HISTORY_LIMIT, len(sampler.history))
        self.assertEqual(sampler.history[-1], sampler.latest)

    def test_tick_if_due_follows_interval(self):
        clock = FakeClock()
        sampler = make(linux_files(), clock)
        self.assertIsNotNone(sampler.tick_if_due())
        clock.now = telemetry.POLL_SECONDS - 0.1
        self.assertIsNone(sampler.tick_if_due())
        clock.now = telemetry.POLL_SECONDS
        self.assertIsNotNone(sampler.tick_if_due())

    def test_no_pid_means_unknown_rss(self):
        self.assertIsNone(make(linux_files()).tick().process_rss_mb)


class GpuTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def fake_run(self, argv, **kwargs):
        self.calls.append(argv)

        class Result:
            stdout = "37, 64\n"
        return Result()

    def test_nvidia_smi_parsed_and_cached_for_five_seconds(self):
        clock = FakeClock()
        sampler = make(linux_files(), clock, which=lambda n: "/bin/" + n, run=self.fake_run)
        sample = sampler.tick()
        self.assertEqual((37.0, 64.0), (sample.gpu_percent, sample.gpu_temp_c))
        clock.now = telemetry.GPU_CACHE_SECONDS - 1
        sampler.tick()
        self.assertEqual(1, len(self.calls))
        clock.now = telemetry.GPU_CACHE_SECONDS
        sampler.tick()
        self.assertEqual(2, len(self.calls))
        self.assertIn("--format=csv,noheader,nounits", self.calls[0])

    def test_not_installed_never_runs(self):
        sampler = make(linux_files(), run=self.fake_run)
        self.assertIsNone(sampler.tick().gpu_percent)
        self.assertEqual([], self.calls)

    def test_failure_is_cached_and_never_raises(self):
        clock = FakeClock()
        attempts = []

        def failing(argv, **kwargs):
            attempts.append(argv)
            raise OSError("boom")
        sampler = make(linux_files(), clock, which=lambda n: n, run=failing)
        self.assertIsNone(sampler.tick().gpu_percent)
        sampler.tick()
        self.assertEqual(1, len(attempts))


class OtherPlatformTests(unittest.TestCase):
    def test_windows_uses_injected_readers(self):
        times = iter([(50, 100, 100), (150, 300, 300)])
        sampler = TelemetrySampler(
            "windows", FakeClock(), which=lambda n: None,
            windows_cpu_times=lambda: next(times),
            windows_memory=lambda: (8 * 1024 * 1024 * 1024, 2 * 1024 * 1024 * 1024))
        sampler.tick()
        sample = sampler.tick()
        # total 200->600 (+400), idle 50->150 (+100), busy +300 -> 75%
        self.assertAlmostEqual(75.0, sample.cpu_percent)
        self.assertAlmostEqual(75.0, sample.ram_percent)
        self.assertIsNone(sample.cpu_temp_c)

    def test_windows_ctypes_failure_off_windows_is_none(self):
        sampler = TelemetrySampler("windows", FakeClock(), which=lambda n: None)
        self.assertIsNone(sampler.tick().cpu_percent)

    def test_macos_is_unknown(self):
        sampler = TelemetrySampler("macos", FakeClock(), which=lambda n: None)
        self.assertEqual(telemetry.UNKNOWN_SAMPLE, sampler.tick())


if __name__ == "__main__":
    unittest.main()
