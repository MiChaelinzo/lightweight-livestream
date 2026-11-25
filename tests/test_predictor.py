"""Predictor tests on SYNTHETIC traces only. Results say nothing about real streams."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import predictor as pr

TARGET = 4000


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def noise(seed, amount):
    """Deterministic pseudo-noise in [-amount, amount] (small LCG)."""
    state = seed
    while True:
        state = (state * 1103515245 + 12345) % (2 ** 31)
        yield (state / 2 ** 31 * 2 - 1) * amount


def run(speed_at, seed=1, jitter=0.0, seconds=180):
    """Feed one reading per second. Returns [(t, trend)]."""
    clock = Clock()
    predictor = pr.TrendPredictor(TARGET, clock)
    wobble = noise(seed, jitter)
    out = []
    for t in range(seconds):
        clock.now = float(t)
        speed = speed_at(t) + next(wobble)
        predictor.add({"speed": speed, "bitrate_kbps": TARGET * min(1.0, speed)})
        out.append((t, predictor.predict()))
    return out


def first_degrading(trace):
    for t, trend in trace:
        if trend.state == pr.DEGRADING:
            return t
    return None


class PredictorSyntheticTests(unittest.TestCase):
    def test_unknown_until_enough_readings(self):
        trace = run(lambda t: 1.0, seconds=8)
        self.assertTrue(all(trend.state == pr.UNKNOWN for _, trend in trace))

    def test_steady_trace_never_degrades(self):
        trace = run(lambda t: 1.0)
        self.assertIsNone(first_degrading(trace))
        self.assertEqual(pr.STABLE, trace[-1][1].state)

    def test_noisy_steady_traces_have_no_false_positives(self):
        false_positives = 0
        for seed in range(1, 41):
            for jitter in (0.02, 0.05):
                if first_degrading(run(lambda t: 1.0, seed, jitter)) is not None:
                    false_positives += 1
        self.assertEqual(0, false_positives)   # 80 synthetic traces

    def test_ramp_down_is_flagged_before_speed_crosses_the_limit(self):
        # speed 1.10 falls 0.003 per second, crossing 0.95 at t = 50
        ramp = lambda t: 1.10 - 0.003 * t
        crossing = int((1.10 - 0.95) / 0.003)
        for seed in range(1, 21):
            found = first_degrading(run(ramp, seed, 0.02))
            self.assertIsNotNone(found, "seed %d" % seed)
            self.assertLess(found, crossing - 10, "seed %d" % seed)   # lead of 10+ s

    def test_ramp_reports_horizon_and_reason(self):
        trace = run(lambda t: 1.10 - 0.003 * t, 1, 0.02)
        trend = next(trend for _, trend in trace if trend.state == pr.DEGRADING)
        self.assertEqual(pr.HORIZON_SECONDS, trend.horizon_seconds)
        self.assertIn("seconds", trend.reasons[0])

    def test_step_drop_is_not_predicted_ahead(self):
        step = lambda t: 1.0 if t < 90 else 0.6
        trace = run(step, 3, 0.02)
        found = first_degrading(trace)
        self.assertTrue(found is None or found >= 90)   # a step has no lead time

    def test_retarget_clears_the_window(self):
        clock = Clock()
        p = pr.TrendPredictor(TARGET, clock)
        for t in range(30):
            clock.now = t
            p.add({"speed": 1.0 - 0.01 * t})
        p.retarget(3000, 30)
        self.assertEqual(pr.UNKNOWN, p.predict().state)

    def test_slope_and_ewma_helpers(self):
        rate, _ = pr.slope([(0, 1.0), (1, 2.0), (2, 3.0)])
        self.assertAlmostEqual(1.0, rate)
        self.assertIsNone(pr.slope([(0, 1.0)])[0])
        self.assertIsNone(pr.ewma([]))
        self.assertEqual(2.0, pr.ewma([2.0, 2.0]))

    def test_deterministic(self):
        a = run(lambda t: 1.10 - 0.003 * t, 5, 0.02)
        b = run(lambda t: 1.10 - 0.003 * t, 5, 0.02)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
