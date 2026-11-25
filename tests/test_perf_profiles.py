import io
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import audio, cli, perf_profiles as pp
from lightstream.bandwidth import PLATFORM_VIDEO_CAP_KBPS
from lightstream.command import build_command
from lightstream.config import resolve_settings
from lightstream.presets import PRESETS
from lightstream.runner import priority_kwargs

EXPECTED_PROFILES = {"potato", "balanced", "quality", "competitive", "low_latency"}
EXPECTED_STREAMS = {"youtube_gaming", "twitch_gaming", "kick", "podcast",
                    "just_chatting", "tutorial", "esports"}
EXPECTED_AUDIO = {"gaming", "podcast", "music", "commentary", "asmr"}


def argv_for(cli_values, file_cfg=None, cpus=8, hardware=None, os_name="linux"):
    values = dict(cli_values, hardware=hardware)
    s = resolve_settings(values, file_cfg or {}, cpu_count=cpus)
    return s, build_command(s, "KEY", os_name, "libx264")


def option(argv, name):
    return argv[argv.index(name) + 1]


class DataTests(unittest.TestCase):
    def test_all_concepts_exist(self):
        self.assertEqual(EXPECTED_PROFILES, set(pp.PERF_PROFILES))
        self.assertEqual(EXPECTED_STREAMS, set(pp.STREAM_PRESETS))
        self.assertEqual(EXPECTED_AUDIO, set(audio.AUDIO_PROFILES))

    def test_every_profile_resolves_to_known_preset(self):
        for name in pp.PERF_PROFILES:
            s, argv = argv_for({"profile": name})
            self.assertIn(pp.get_perf_profile(name).preset_name, PRESETS)
            self.assertEqual("%dk" % s.video_kbps, option(argv, "-b:v"))

    def test_every_stream_preset_resolves_within_platform_cap(self):
        for name, stream in pp.STREAM_PRESETS.items():
            s = resolve_settings({"stream_preset": name}, {}, cpu_count=8)
            self.assertEqual(stream.platform, s.platform)
            self.assertLessEqual(s.video_kbps, PLATFORM_VIDEO_CAP_KBPS[stream.platform])
            self.assertIsNotNone(s.audio_filter)

    def test_unknown_names_are_plain_errors(self):
        for getter in (pp.get_perf_profile, pp.get_stream_preset, audio.get_audio_profile):
            with self.assertRaises(ValueError):
                getter("nope")


class ResolutionTests(unittest.TestCase):
    def test_quality_is_capped_by_hardware_profile(self):
        self.assertEqual("720p60", pp.profile_preset_name("quality"))
        self.assertEqual("light", pp.profile_preset_name("quality", "intel_hd"))
        s = resolve_settings({"profile": "quality", "hardware": "intel_hd"}, {}, cpu_count=4)
        self.assertEqual(854, s.width)

    def test_explicit_preset_beats_profile(self):
        s = resolve_settings({"profile": "quality", "preset": "potato",
                              "force_preset": True}, {}, cpu_count=4)
        self.assertEqual(640, s.width)

    def test_explicit_flags_beat_stream_preset(self):
        s = resolve_settings({"stream_preset": "twitch_gaming", "platform": "youtube",
                              "bitrate": 9999, "fps": 45,
                              "audio_profile": "asmr"}, {}, cpu_count=8)
        self.assertEqual(("youtube", 9999, 45), (s.platform, s.video_kbps, s.fps))
        self.assertEqual(audio.audio_profile_chain("asmr"), s.audio_filter)

    def test_cli_profile_beats_file_preset_and_file_profile_works(self):
        s = resolve_settings({"profile": "competitive"}, {"preset": "light"}, cpu_count=8)
        self.assertEqual(60, s.fps)
        s = resolve_settings({}, {"profile": "potato"}, cpu_count=8)
        self.assertEqual(640, s.width)
        s = resolve_settings({}, {"profile": "potato", "preset": "balanced"}, cpu_count=8)
        self.assertEqual(1280, s.width)

    def test_no_profile_leaves_argv_as_before(self):
        s, argv = argv_for({})
        self.assertNotIn("-threads", argv)
        self.assertNotIn("-af", argv)
        self.assertEqual("zerolatency", option(argv, "-tune"))
        self.assertEqual(str(s.fps * 2), option(argv, "-g"))

    def test_thread_math(self):
        self.assertEqual(pp.PerfTuning(7, 1), pp.resolve_tuning("balanced", 8))
        self.assertEqual(pp.PerfTuning(6, 2), pp.resolve_tuning("competitive", 8))
        self.assertEqual(pp.PerfTuning(2, 1), pp.resolve_tuning("potato", 8))
        self.assertEqual(pp.PerfTuning(1, 0), pp.resolve_tuning("balanced", 1))
        self.assertEqual(pp.PerfTuning(None, 0), pp.resolve_tuning("quality", 8))
        self.assertEqual(pp.PerfTuning(1, 1), pp.resolve_tuning("potato", 2))

    def test_threads_reach_ffmpeg(self):
        _, argv = argv_for({"profile": "competitive"}, cpus=8)
        self.assertEqual("6", option(argv, "-threads"))
        self.assertEqual("6", option(argv, "-filter_threads"))

    def test_threads_replace_hardware_profile_threads(self):
        _, argv = argv_for({"profile": "balanced"}, cpus=8, hardware="generic")
        self.assertEqual(1, argv.count("-threads"))
        self.assertEqual(1, argv.count("-filter_threads"))
        self.assertEqual("7", option(argv, "-threads"))

    def test_low_latency_and_quality_knobs(self):
        _, argv = argv_for({"profile": "low_latency"})
        self.assertEqual(str(30 * pp.LOW_LATENCY_KEYINT_SECONDS), option(argv, "-g"))
        self.assertEqual("1250k", option(argv, "-bufsize"))
        _, argv = argv_for({"profile": "quality"})
        self.assertNotIn("-tune", argv)

    def test_affinity_cpus(self):
        self.assertEqual({2, 3, 4, 5, 6, 7}, pp.affinity_cpus(8, 2))
        self.assertIsNone(pp.affinity_cpus(8, 0))
        self.assertIsNone(pp.affinity_cpus(1, 1))
        self.assertEqual({1}, pp.affinity_cpus(2, 5))


class AffinityRunnerTests(unittest.TestCase):
    def test_preexec_sets_priority_and_affinity(self):
        calls = []
        kwargs = priority_kwargs("linux", {2, 3}, nice=lambda n: calls.append(("nice", n)),
                                 set_affinity=lambda pid, cpus: calls.append((pid, cpus)))
        kwargs["preexec_fn"]()
        self.assertEqual([("nice", 10), (0, {2, 3})], calls)

    def test_affinity_is_a_noop_without_support_or_request(self):
        calls = []
        priority_kwargs("linux", {1}, nice=calls.append, set_affinity=None)["preexec_fn"]()
        priority_kwargs("linux", None, nice=calls.append,
                        set_affinity=lambda *a: calls.append("bad"))["preexec_fn"]()
        self.assertEqual([10, 10], calls)

    def test_windows_ignores_affinity(self):
        self.assertIn("creationflags", priority_kwargs("windows", {1}))


class AudioProfileTests(unittest.TestCase):
    def test_chains_are_built_from_allowed_filters(self):
        allowed = {"highpass", "afftdn", "acompressor", "equalizer", "alimiter"}
        for p in audio.AUDIO_PROFILES.values():
            for chain in (p.light, p.full):
                names = {stage.split("=")[0] for stage in chain.split(",")}
                self.assertTrue(names <= allowed, chain)
            self.assertTrue(p.cost_note)

    def test_light_is_not_longer_than_full(self):
        for p in audio.AUDIO_PROFILES.values():
            self.assertLessEqual(len(p.light.split(",")), len(p.full.split(",")))

    def test_bad_chain_level_rejected(self):
        with self.assertRaises(ValueError):
            audio.audio_profile_chain("gaming", "heavy")

    def test_noise_option_wins_over_audio_profile(self):
        s = resolve_settings({"audio_profile": "gaming", "noise": "light"}, {})
        argv = build_command(s, "KEY", "linux", "libx264")
        self.assertEqual(audio.LIGHT_CHAIN, option(argv, "-af"))
        self.assertEqual(1, argv.count("-af"))

    def test_audio_profile_adds_chain_and_light_on_weak_profiles(self):
        _, argv = argv_for({"audio_profile": "podcast"})
        self.assertEqual(audio.AUDIO_PROFILES["podcast"].full, option(argv, "-af"))
        _, argv = argv_for({"audio_profile": "podcast"}, hardware="intel_hd_optimized")
        self.assertEqual(audio.AUDIO_PROFILES["podcast"].light, option(argv, "-af"))
        _, argv = argv_for({"profile": "potato", "audio_profile": "gaming"})
        self.assertEqual(audio.AUDIO_PROFILES["gaming"].light, option(argv, "-af"))

    def test_potato_profile_has_no_audio_filter_by_default(self):
        self.assertNotIn("-af", argv_for({"profile": "potato"})[1])


class ProfilesCommandTests(unittest.TestCase):
    def test_lists_every_name(self):
        out = io.StringIO()
        self.assertEqual(0, cli.main(["profiles"], out))
        text = out.getvalue()
        for name in EXPECTED_PROFILES | EXPECTED_STREAMS | EXPECTED_AUDIO:
            self.assertIn(name, text)

    def test_start_parser_accepts_new_flags(self):
        args = cli.build_parser().parse_args(
            ["start", "--profile", "quality", "--stream-preset", "kick",
             "--audio-profile", "asmr"])
        self.assertEqual(("quality", "kick", "asmr"),
                         (args.profile, args.stream_preset, args.audio_profile))


FFMPEG = os.environ.get("LIGHTSTREAM_TEST_FFMPEG")


@unittest.skipUnless(FFMPEG, "set LIGHTSTREAM_TEST_FFMPEG to a real ffmpeg binary")
class RealFfmpegAudioChainTests(unittest.TestCase):
    def test_every_chain_is_accepted(self):
        for p in audio.AUDIO_PROFILES.values():
            for label, chain in (("light", p.light), ("full", p.full)):
                with self.subTest(profile=p.name, chain=label):
                    result = subprocess.run(
                        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                         "-i", "sine=frequency=440:duration=1", "-af", chain,
                         "-t", "1", "-f", "null", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True)
                    self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
