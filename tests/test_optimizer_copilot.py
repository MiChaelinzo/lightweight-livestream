import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import optimizer as opt
from lightstream.audio_check import AudioCheck
from tests.test_optimizer import insights, run, sample


def lower_preset(found):
    return next((i for i in found if i.action == "lower_preset"), None)


def rows(preset, speed, count):
    return [{"preset": preset, "avg_speed": speed}] * count


class SlowSetup(unittest.TestCase):
    def slow(self, history=(), preset="balanced"):
        advisor, tracker = run(120, speed=0.6)
        ctx = opt.OptimizerContext(preset, 2500, 30, "libx264")
        return insights(advisor, tracker, [sample(97)] * 5, ctx, history)


class ExpectedGainTests(SlowSetup):
    def test_no_history_means_no_gain_number(self):
        found = lower_preset(self.slow())
        self.assertIsNotNone(found, "scenario must produce lower_preset")
        self.assertIsNone(found.expected_gain)
        self.assertNotIn("Measured", opt.insight_line(found))

    def test_too_few_sessions_gives_no_number(self):
        history = rows("balanced", 0.6, 2) + rows(lower_preset(self.slow()).value, 1.1, 5)
        self.assertIsNone(lower_preset(self.slow(history)).expected_gain)

    def test_gain_shown_with_sample_sizes(self):
        target = lower_preset(self.slow()).value
        history = rows("balanced", 0.6, 4) + rows(target, 1.1, 3)
        found = lower_preset(self.slow(history))
        self.assertEqual(0.5, found.expected_gain.delta)
        line = opt.insight_line(found)
        self.assertIn("+0.50", line)
        self.assertIn("n=4", line)
        self.assertIn("n=3", line)

    def test_helper_ignores_non_numeric_and_same_preset(self):
        bad = [{"preset": "a", "avg_speed": None}] * 5 + rows("b", 1.0, 5)
        self.assertIsNone(opt.expected_gain_from_history(bad, "a", "b"))
        self.assertIsNone(opt.expected_gain_from_history(rows("a", 1, 5), "a", "a"))
        self.assertIsNone(opt.expected_gain_from_history(rows("a", 1, 5), None, "a"))

    def test_no_insight_prints_a_number_without_counts(self):
        for item in self.slow(rows("balanced", 0.6, 5)):
            if item.expected_gain is None:
                self.assertIsNone(opt.gain_text(item))
            else:
                self.assertIn("n=", opt.gain_text(item))

    def test_gain_text_is_a_comparison_not_a_cause(self):
        history = rows("balanced", 0.6, 4) + rows("fast", 1.1, 3)
        gain = opt.expected_gain_from_history(history, "balanced", "fast")
        insight = opt.Insight("speed", "lower_preset", None, 0.5, "e", "m", expected_gain=gain)
        text = opt.gain_text(insight)
        self.assertNotIn("going from", text)
        self.assertIn("sessions at 'fast' (n=3) averaged", text)
        self.assertIn("compared with sessions at 'balanced' (n=4)", text)
        self.assertIn("Not a controlled comparison", text)


class AudioLatencyUploadTests(unittest.TestCase):
    def healthy(self, **kwargs):
        advisor, tracker = run(20)
        return opt.build_insights(
            advisor, tracker.summary(), (), tracker.network_stability(),
            opt.OptimizerContext("balanced", 2500, 30, "libx264"), **kwargs)

    def test_nothing_without_inputs(self):
        self.assertEqual([], self.healthy())

    def test_clipping_insight(self):
        found = self.healthy(audio=AudioCheck(0.0, 500, -3.0, 0.2))
        self.assertEqual(["reduce_input_gain"], [i.action for i in found])
        self.assertEqual(opt.CLIPPING_CONFIDENCE_SAMPLES, found[0].confidence)
        self.assertIsNone(found[0].expected_gain)

    def test_peak_only_clipping_has_lower_confidence(self):
        found = self.healthy(audio=AudioCheck(-0.5, 0, None, None))
        self.assertEqual(opt.CLIPPING_CONFIDENCE_PEAK, found[0].confidence)

    def test_clean_audio_gives_no_insight(self):
        self.assertEqual([], self.healthy(audio=AudioCheck(-12.0, 0, -20.0, -11.0)))

    def test_high_latency(self):
        found = self.healthy(latency_ms=opt.HIGH_LATENCY_MS)
        self.assertEqual(["high_latency"], [i.action for i in found])
        self.assertEqual([], self.healthy(latency_ms=opt.HIGH_LATENCY_MS - 1))

    def test_bitrate_above_upload_headroom(self):
        found = self.healthy(upload_kbps=2000)
        self.assertEqual(["lower_bitrate"], [i.action for i in found])
        self.assertEqual(int(2000 * opt.UPLOAD_HEADROOM), found[0].value)
        self.assertEqual([], self.healthy(upload_kbps=5000))

    def test_deterministic(self):
        args = dict(audio=AudioCheck(0.0, 5, -3.0, 0.2), latency_ms=300, upload_kbps=2000)
        self.assertEqual(self.healthy(**args), self.healthy(**args))


class FacadeTests(unittest.TestCase):
    def test_facade_matches_build_insights(self):
        advisor, tracker = run(20)
        ctx = opt.OptimizerContext("balanced", 2500, 30, "libx264")
        audio = AudioCheck(0.0, 5, -3.0, 0.2)
        assistant = opt.AIStreamingAssistant(advisor, ctx)
        direct = opt.build_insights(advisor, tracker.summary(), (), None, ctx,
                                    audio=audio, latency_ms=400)
        via = assistant.advise(tracker.summary(), audio=audio, latency_ms=400)
        self.assertEqual(direct, via)
        self.assertEqual([opt.insight_line(i) for i in direct], assistant.lines(via))


class AudioHealthTests(unittest.TestCase):
    def test_absent_audio_changes_nothing(self):
        base = opt.performance_health(cpu=80, network=100)
        self.assertEqual(base, opt.performance_health(cpu=80, network=100,
                                                      audio_peak_dbfs=None))
        self.assertNotIn("audio", base.parts)
        self.assertNotIn("audio", base.skipped)

    def test_clipping_lowers_score(self):
        clean = opt.performance_health(cpu=60, network=100, audio_peak_dbfs=-12.0)
        clipped = opt.performance_health(cpu=60, network=100, audio_peak_dbfs=0.0)
        self.assertEqual(100.0, clean.parts["audio"])
        self.assertEqual(0.0, clipped.parts["audio"])
        self.assertLess(clipped.score, clean.score)

    def test_audio_alone_gives_a_score(self):
        self.assertEqual(0, opt.performance_health(audio_peak_dbfs=0.0).score)

    def test_session_health_passes_audio(self):
        health = opt.session_health({"recent_speed": 1.0}, audio_peak_dbfs=0.0)
        self.assertEqual(0.0, health.parts["audio"])


if __name__ == "__main__":
    unittest.main()
