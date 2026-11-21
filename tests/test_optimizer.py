import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import optimizer as opt
from lightstream.adaptive import AdaptiveAdvisor
from lightstream.health import HealthTracker
from lightstream.telemetry import Sample


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def sample(cpu=None, gpu=None, cpu_temp=None, gpu_temp=None):
    return Sample(cpu, None, None, cpu_temp, gpu, gpu_temp, None)


def run(seconds, speed=1.0, bitrate=2500.0, fps=30.0, dropped=0, target=2500):
    clock = Clock()
    advisor = AdaptiveAdvisor("balanced", target, 30, clock=clock)
    tracker = HealthTracker(target_kbps=target, clock=clock)
    for _ in range(seconds):
        clock.now += 1
        progress = {"speed": speed, "bitrate_kbps": bitrate, "fps": fps,
                    "dropped": dropped}
        advisor.observe(progress)
        tracker.update(progress)
    return advisor, tracker


def insights(advisor, tracker, samples=(), context=None, history=()):
    return opt.build_insights(advisor, tracker.summary(), samples,
                              tracker.network_stability(),
                              context or opt.OptimizerContext("balanced", 2500, 30,
                                                              "libx264"), history)


def areas(found):
    return {i.area: i for i in found}


class ConfidenceTests(unittest.TestCase):
    def test_monotonic_in_samples(self):
        values = [opt.confidence(n, 0.5, 0.9) for n in (0, 10, 30, 60, 120)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(0.0, values[0])
        self.assertEqual(values[3], values[4])

    def test_monotonic_in_margin(self):
        values = [opt.confidence(60, 0.9 - m, 0.9) for m in (0, 0.1, 0.3, 0.9)]
        self.assertEqual(values, sorted(values))

    def test_bounds_and_history_cap(self):
        self.assertLessEqual(opt.confidence(1000, 0, 0.9, 5.0), 1.0)
        rows = [{"bottleneck": "cpu"}] * 10 + [{"bottleneck": "network"}]
        self.assertEqual(opt.HISTORY_BONUS_MAX, opt.history_bonus(rows, "cpu"))
        self.assertEqual(opt.HISTORY_BONUS_PER_SESSION, opt.history_bonus(rows, "network"))
        self.assertEqual(0, opt.history_bonus([], "cpu"))


class ClassifyTests(unittest.TestCase):
    def kind(self, advisor, tracker, samples=(), context=None):
        return opt.bottleneck_of(insights(advisor, tracker, samples, context))

    def test_healthy_gives_nothing(self):
        advisor, tracker = run(60)
        self.assertEqual([], insights(advisor, tracker, [sample(20)] * 5))

    def test_cpu(self):
        advisor, tracker = run(60, speed=0.7)
        self.assertEqual("cpu", self.kind(advisor, tracker, [sample(97)] * 5))

    def test_cpu_unknown_with_software_encoder_is_cpu(self):
        advisor, tracker = run(60, speed=0.7)
        self.assertEqual("cpu", self.kind(advisor, tracker))

    def test_encoder_when_cpu_has_room(self):
        advisor, tracker = run(60, speed=0.7)
        self.assertEqual("encoder", self.kind(advisor, tracker, [sample(30)] * 5))

    def test_gpu_with_hardware_encoder(self):
        advisor, tracker = run(60, speed=0.7)
        ctx = opt.OptimizerContext("balanced", 2500, 30, "h264_nvenc")
        self.assertEqual("gpu", self.kind(advisor, tracker, [sample(30, gpu=99)] * 5, ctx))

    def test_thermal_beats_cpu(self):
        advisor, tracker = run(60, speed=0.7)
        self.assertEqual("thermal", self.kind(advisor, tracker,
                                              [sample(97, cpu_temp=95)] * 5))

    def test_network_from_low_bitrate(self):
        advisor, tracker = run(60, bitrate=900.0)
        self.assertEqual("network", self.kind(advisor, tracker, [sample(20)] * 5))

    def test_unknown_when_only_drops(self):
        clock = Clock()
        advisor = AdaptiveAdvisor("balanced", 2500, 30, clock=clock)
        tracker = HealthTracker(target_kbps=2500, clock=clock)
        for i in range(60):
            clock.now += 1
            progress = {"speed": 1.0, "bitrate_kbps": 2500.0, "fps": 30.0,
                        "dropped": i * 2}
            advisor.observe(progress)
            tracker.update(progress)
        self.assertEqual("unknown", self.kind(advisor, tracker))


class InsightTests(unittest.TestCase):
    def test_every_insight_has_confidence_and_texts(self):
        advisor, tracker = run(60, speed=0.7, fps=20.0)
        ctx = opt.OptimizerContext("balanced", 2500, 60, "libx264", "ai")
        found = insights(advisor, tracker, [sample(97)] * 5, ctx)
        by_area = areas(found)
        for area in ("bottleneck", "fps", "audio", "encoder", "resolution"):
            self.assertIn(area, by_area)
        for item in found:
            self.assertTrue(0 < item.confidence <= 1)
            self.assertTrue(item.explanation and item.plain_text)
        self.assertEqual(30, by_area["fps"].value)
        self.assertEqual("light", by_area["audio"].value)
        self.assertEqual(["bottleneck"] * 0 + sorted(
            (i.confidence for i in found), reverse=True),
            [i.confidence for i in found])

    def test_network_suggests_lower_bitrate(self):
        advisor, tracker = run(60, bitrate=900.0)
        by_area = areas(insights(advisor, tracker))
        self.assertEqual(2000, by_area["bitrate"].value)

    def test_deterministic(self):
        advisor, tracker = run(60, speed=0.7)
        first = insights(advisor, tracker, [sample(97)] * 5)
        self.assertEqual(first, insights(advisor, tracker, [sample(97)] * 5))

    def test_confidence_grows_with_samples(self):
        scores = []
        for seconds in (35, 50, 90):
            advisor, tracker = run(seconds, speed=0.7)
            scores.append(areas(insights(advisor, tracker, [sample(97)] * 5))
                          ["bottleneck"].confidence)
        self.assertEqual(scores, sorted(scores))
        self.assertLess(scores[0], scores[-1])

    def test_history_raises_confidence(self):
        advisor, tracker = run(40, speed=0.7)
        base = areas(insights(advisor, tracker, [sample(90)] * 5))["bottleneck"]
        more = areas(insights(advisor, tracker, [sample(90)] * 5,
                              history=[{"bottleneck": "cpu"}] * 2))["bottleneck"]
        self.assertGreater(more.confidence, base.confidence)

    def test_insight_line(self):
        item = opt.Insight("fps", "x", 30, 0.756, "why", "Do this.")
        self.assertEqual("Do this. (confidence 76%)", opt.insight_line(item))


if __name__ == "__main__":
    unittest.main()
