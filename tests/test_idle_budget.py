"""tools/idle_budget.py: pure budget checks, plus a display-gated real window."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import benchlab, idle_budget  # noqa: E402

MB = benchlab.BYTES_PER_MB
HAVE_DISPLAY = idle_budget.display_available()


class FakeWatcher:
    def __init__(self, found_at):
        self.found_at = found_at


class FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class BuildResultTest(unittest.TestCase):
    def test_numbers_come_from_samples(self):
        samples = [{"cpu_percent": None, "rss_bytes": 80 * MB},
                   {"cpu_percent": 2.0, "rss_bytes": 90 * MB},
                   {"cpu_percent": 4.0, "rss_bytes": 85 * MB}]
        result = idle_budget.build_result(1.23456, samples)
        self.assertEqual(result["startup_s"], 1.235)
        self.assertEqual(result["rss_mb"], 85.0)
        self.assertEqual(result["rss_mb_peak"], 90.0)
        self.assertEqual(result["idle_cpu_percent"], 3.0)
        self.assertEqual(result["idle_cpu_percent_max"], 4.0)
        self.assertEqual(result["samples"], 3)

    def test_no_samples_gives_none(self):
        result = idle_budget.build_result(None, [])
        self.assertIsNone(result["startup_s"])
        self.assertIsNone(result["rss_mb"])
        self.assertIsNone(result["idle_cpu_percent"])


class CheckBudgetsTest(unittest.TestCase):
    def good(self):
        return {"startup_s": 1.0, "rss_mb": 90.0, "idle_cpu_percent": 0.5}

    def test_within_budget(self):
        self.assertEqual(idle_budget.check_budgets(self.good()), [])

    def test_each_limit_is_enforced(self):
        for name, limit in idle_budget.BUDGETS.items():
            result = dict(self.good(), **{name: limit})
            self.assertEqual(idle_budget.check_budgets(result), [name])

    def test_unmeasured_value_is_a_violation(self):
        result = dict(self.good(), startup_s=None)
        self.assertEqual(idle_budget.check_budgets(result), ["startup_s"])

    def test_budgets_match_the_documented_limits(self):
        self.assertEqual(idle_budget.BUDGETS,
                         {"startup_s": 2.0, "rss_mb": 150.0, "idle_cpu_percent": 5.0})


class WaitForReadyTest(unittest.TestCase):
    def test_returns_found_time(self):
        self.assertEqual(idle_budget.wait_for_ready(
            FakeWatcher(0.7), FakeProc(), 5, sleep=lambda s: None), 0.7)

    def test_stops_when_child_exited(self):
        self.assertIsNone(idle_budget.wait_for_ready(
            FakeWatcher(None), FakeProc(1), 5, sleep=lambda s: None))

    def test_times_out(self):
        ticks = iter(range(100))
        self.assertIsNone(idle_budget.wait_for_ready(
            FakeWatcher(None), FakeProc(), 3, clock=lambda: next(ticks),
            sleep=lambda s: None))


class DisplayGateTest(unittest.TestCase):
    def test_display_detection(self):
        self.assertFalse(idle_budget.display_available({}))
        self.assertTrue(idle_budget.display_available({"DISPLAY": ":0"}))


@unittest.skipUnless(HAVE_DISPLAY and benchlab.proc_available(),
                     "needs a DISPLAY (for example Xvfb) and /proc")
class RealWindowIdleBudgetTest(unittest.TestCase):
    def test_window_stays_inside_the_idle_budgets(self):
        result = idle_budget.measure_window(duration=5.0, settle=1.0)
        violations = idle_budget.check_budgets(result)
        self.assertEqual(violations, [], result)


if __name__ == "__main__":
    unittest.main()
