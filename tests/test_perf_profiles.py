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

EXPECTED_PROFILES = {"potato", "potato_2000", "potato_4000", "balanced", "quality", "competitive", "low_latency",
                     "potato_pc", "office_laptop", "budget_gaming"}
EXPECTED_STREAMS = {"youtube_gaming", "twitch_gaming", "facebook_live", "kick", "podcast",
                    "just_chatting", "tutorial", "esports"}
EXPECTED_AUDIO = {"gaming", "podcast", "music", "commentary", "asmr", "teaching",
                  "meeting"}


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
        allowed = {"highpass", "afftdn", "acompressor", "equalizer", "alimiter",
                   "dynaudnorm"}
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


class OneClickProfileTests(unittest.TestCase):
    def test_office_laptop_is_900p30_and_never_40_fps(self):
        preset = PRESETS[pp.get_perf_profile("office_laptop").preset_name]
        self.assertEqual((1600, 900, 30), (preset.width, preset.height, preset.fps))
        for p in PRESETS.values():
            self.assertNotEqual(40, p.fps, p.name)

    def test_budget_gaming_is_1080p60_within_every_cap_it_is_chosen_for(self):
        preset = PRESETS[pp.get_perf_profile("budget_gaming").preset_name]
        self.assertEqual((1920, 1080, 60), (preset.width, preset.height, preset.fps))
        self.assertLessEqual(preset.video_kbps, PLATFORM_VIDEO_CAP_KBPS["twitch"])
        self.assertIn("hardware encoder", pp.get_perf_profile("budget_gaming").description)

    def test_office_laptop_fits_the_smallest_platform_cap(self):
        self.assertLessEqual(PRESETS["office_laptop"].video_kbps,
                             min(PLATFORM_VIDEO_CAP_KBPS.values()))

    def test_potato_pc_is_480p30_at_1000k_with_two_threads(self):
        s, argv = argv_for({"profile": "potato_pc"}, cpus=8)
        self.assertEqual((854, 480, 30, 1000), (s.width, s.height, s.fps, s.video_kbps))
        self.assertEqual("2", option(argv, "-threads"))

    def test_cli_accepts_the_new_profile_names(self):
        for name in ("potato_pc", "office_laptop", "budget_gaming"):
            args = cli.build_parser().parse_args(["start", "--profile", name])
            self.assertEqual(name, args.profile)

    def test_gui_profile_list_shows_the_new_profiles(self):
        from lightstream import gui_pages
        choices = gui_pages.profile_choices()
        for name in ("potato_pc", "office_laptop", "budget_gaming"):
            self.assertIn(name, choices)

    def test_new_presets_are_never_chosen_by_upload_recommendation(self):
        from lightstream import bandwidth
        for hardware in (None, "nvidia"):
            rec = bandwidth.recommend(100000, "twitch", hardware)
            self.assertNotIn(rec.preset, ("office_laptop", "budget_gaming"))

    def test_intel_hd_caps_the_new_presets_to_light(self):
        from lightstream.hardware import cap_preset_name
        for name in ("office_laptop", "budget_gaming"):
            self.assertEqual("light", cap_preset_name("intel_hd", name))


class RecommendProfileTests(unittest.TestCase):
    def test_weak_pcs_get_potato_profiles(self):
        self.assertEqual("potato_2000", pp.recommend_profile(2, 2048))
        self.assertEqual("potato_pc", pp.recommend_profile(2, 8192))
        self.assertEqual("potato_pc", pp.recommend_profile(8, 4096))

    def test_intel_hd_gets_potato_pc(self):
        self.assertEqual("potato_pc", pp.recommend_profile(
            4, 8192, "Intel(R) HD Graphics 620"))

    def test_nvidia_with_capable_cpu_gets_budget_gaming(self):
        self.assertEqual("budget_gaming", pp.recommend_profile(
            6, 16384, "NVIDIA GeForce GTX 1650"))
        self.assertEqual("budget_gaming", pp.recommend_profile(
            6, 16384, hardware_profile="nvidia"))

    def test_capable_pc_without_nvenc_gets_office_laptop(self):
        self.assertEqual("office_laptop", pp.recommend_profile(4, 8192, "AMD Radeon"))
        self.assertEqual("office_laptop", pp.recommend_profile(
            8, 16384, hardware_profile="mx250_streamer"))

    def test_middle_pc_and_unknowns_get_balanced(self):
        self.assertEqual("balanced", pp.recommend_profile(4, 6144))
        self.assertEqual("balanced", pp.recommend_profile(None, None))

    def test_hardware_profile_overrides_gpu_name(self):
        self.assertEqual("potato_pc", pp.recommend_profile(
            8, 16384, "NVIDIA GeForce GTX 1650", hardware_profile="intel_hd"))

    def test_every_answer_is_a_known_profile(self):
        for cpus in (None, 1, 2, 4, 8):
            for ram in (None, 1024, 4096, 6144, 8192, 32768):
                for gpu in (None, "NVIDIA GeForce GTX 1650", "Intel HD Graphics 620"):
                    self.assertIn(pp.recommend_profile(cpus, ram, gpu), pp.PERF_PROFILES)

    def test_optimize_text_names_the_one_click_profile(self):
        from lightstream import wizard
        prop = wizard.propose_optimization(
            {}, "NVIDIA GeForce GTX 1650", 6, 16384, None, "twitch",
            wizard.gather_readiness_facts("linux", 6, 16384, None,
                                          run=lambda *a, **k: None,
                                          find=lambda: None))
        self.assertTrue(any("--profile budget_gaming" in n for n in prop.notes), prop.notes)


if __name__ == "__main__":
    unittest.main()
