import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import timeline as tl
from lightstream.telemetry import Sample


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def sample(cpu=None, ram=None):
    return Sample(cpu, ram, None, None, None, None, None)


class TimelineTests(unittest.TestCase):
    def test_events_are_bounded_and_timed_from_start(self):
        clock = Clock()
        t = tl.Timeline(clock)
        for i in range(tl.EVENT_LIMIT + 50):
            clock.now += 1
            t.record(tl.RECONNECT, "x")
        self.assertEqual(tl.EVENT_LIMIT, len(t.events))
        self.assertEqual(250, t.events[-1].seconds)

    def test_same_sample_object_is_kept_once_and_samples_are_bounded(self):
        clock = Clock()
        t = tl.Timeline(clock)
        s = sample(10)
        t.note_sample(s)
        t.note_sample(s)
        t.note_sample(None)
        self.assertEqual(1, len(t.samples))
        for _ in range(tl.SAMPLE_LIMIT + 5):
            t.note_sample(sample(1))
        self.assertEqual(tl.SAMPLE_LIMIT, len(t.samples))

    def test_spike_lists_events_that_happened_around_it(self):
        events = [tl.TimelineEvent(100, tl.STEP, "down"),
                  tl.TimelineEvent(500, tl.RECONNECT, "far away")]
        samples = [(95, sample(50)), (100, sample(97)), (102, sample(99)),
                   (104, sample(40))]
        spikes = tl.attribute_spikes(samples, events, window=30)
        self.assertEqual(1, len(spikes))
        self.assertEqual(99, spikes[0].peak)
        self.assertIn("Happened around then", spikes[0].text)
        self.assertIn("guardian step at 100s", spikes[0].text)
        self.assertNotIn("reconnect", spikes[0].text)
        for word in ("caused", "because", "due to", "led to"):
            self.assertNotIn(word, spikes[0].text)

    def test_spike_without_events_says_so(self):
        spikes = tl.attribute_spikes([(5, sample(96))], [], window=30)
        self.assertIn("No recorded event happened around then", spikes[0].text)

    def test_separate_runs_are_separate_spikes_and_unknown_breaks_a_run(self):
        samples = [(1, sample(96)), (2, sample(None)), (3, sample(96))]
        self.assertEqual(2, len(tl.attribute_spikes(samples, [])))

    def test_report_is_empty_without_events_and_hedged_with_them(self):
        clock = Clock()
        t = tl.Timeline(clock)
        self.assertEqual([], t.report_lines())
        t.note_sample(sample(97))
        t.record(tl.STEP, "down")
        text = "\n".join(t.report_lines())
        self.assertIn("not saved", text)
        self.assertIn("do not show what caused what", text)


if __name__ == "__main__":
    unittest.main()
