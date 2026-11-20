import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import scenes
from lightstream.command import build_command, tee_output
from lightstream.config import resolve_settings
from lightstream.runner import format_command

KEY = "live_SECRET123"
LETTERBOX = ("scale=854:480:flags=fast_bilinear:force_original_aspect_ratio=decrease,"
             "pad=854:480:(ow-iw)/2:(oh-ih)/2")


def one_scene(*sources, name="s"):
    return scenes.parse_scenes({"scenes": [{"name": name, "sources": list(sources)}]})[name]


SCREEN = {"kind": "screen"}


class ParseTests(unittest.TestCase):
    def test_parse_all_kinds(self):
        sc = one_scene(
            {"kind": "browser", "window": "Chrome",
             "crop": {"x": 1, "y": 2, "w": 300, "h": 200}},
            {"kind": "webcam", "device": "Cam", "corner": "top-left",
             "size_percent": 10, "chromakey": {"color": "00FF00", "similarity": 0.2}},
            {"kind": "image", "path": "logo.png"},
            {"kind": "text", "text": "BRB soon", "font_file": "C:\\f\\a.ttf"})
        self.assertEqual(scenes.ScreenSource("Chrome", (1, 2, 300, 200)), sc.sources[0])
        self.assertEqual("00FF00", sc.sources[1].chromakey_color)
        self.assertEqual("top-left", sc.sources[2].corner)
        self.assertEqual(24, sc.sources[3].font_size)

    def test_errors_are_plain(self):
        bad = [
            ({"scenes": "x"}, "'scenes' list"),
            ({"scenes": [{"sources": [SCREEN]}]}, "'name'"),
            ({"scenes": [{"name": "a", "sources": []}]}, "non-empty 'sources'"),
            ({"scenes": [{"name": "a", "sources": [{"kind": "webcam", "device": "c"}]}]},
             "first source"),
            ({"scenes": [{"name": "a", "sources": [SCREEN, SCREEN]}]}, "exactly one"),
            ({"scenes": [{"name": "a", "sources": [SCREEN, {"kind": "ufo"}]}]},
             "unknown source kind"),
            ({"scenes": [{"name": "a", "sources": [
                SCREEN, {"kind": "webcam", "device": "c", "size_percent": 90}]}]},
             "size_percent"),
            ({"scenes": [{"name": "a", "sources": [
                SCREEN, {"kind": "webcam", "device": "c", "corner": "middle"}]}]},
             "corner"),
            ({"scenes": [{"name": "a", "sources": [
                SCREEN, {"kind": "webcam", "device": "c", "blur": 5,
                         "chromakey": {"color": "00ff00"}}]}]}, "not both"),
            ({"scenes": [{"name": "a", "sources": [
                SCREEN, {"kind": "webcam", "device": "c",
                         "chromakey": {"color": "green"}}]}]}, "6 hex"),
            ({"scenes": [{"name": "a", "sources": [
                SCREEN, {"kind": "text", "text": "a:b"}]}]}, "may only use"),
            ({"scenes": [{"name": "a", "sources": [
                {"kind": "screen", "crop": {"x": 0, "y": 0, "w": 0, "h": 5}}]}]},
             "crop"),
            ({"scenes": [{"name": "a", "sources": [SCREEN]},
                         {"name": "a", "sources": [SCREEN]}]}, "Duplicate"),
            ({"scenes": [{"name": "a", "sources": [
                SCREEN, {"kind": "webcam", "device": "c"},
                {"kind": "webcam", "device": "d"}]}]}, "only one webcam"),
        ]
        for data, fragment in bad:
            with self.assertRaises(ValueError) as ctx:
                scenes.parse_scenes(data)
            self.assertIn(fragment, str(ctx.exception))

    def test_load_scenes_file_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "scenes.json")
            with open(good, "w") as fh:
                json.dump({"scenes": [{"name": "a", "sources": [SCREEN]}]}, fh)
            self.assertEqual(["a"], list(scenes.load_scenes(good)))
            broken = os.path.join(tmp, "bad.json")
            with open(broken, "w") as fh:
                fh.write("{nope")
            with self.assertRaises(ValueError) as ctx:
                scenes.load_scenes(broken)
            self.assertIn("not valid JSON", str(ctx.exception))

    def test_select_scene(self):
        found = {"a": scenes.DEFAULT_SCENE}
        self.assertIs(scenes.DEFAULT_SCENE, scenes.select_scene(found, "a"))
        with self.assertRaises(ValueError) as ctx:
            scenes.select_scene(found, "b")
        self.assertIn("Available: a", str(ctx.exception))

    def test_scene_window_prefers_scene(self):
        sc = one_scene({"kind": "window", "window": "Game"})
        self.assertEqual("Game", scenes.scene_window(sc, "Other"))
        self.assertEqual("Other", scenes.scene_window(scenes.DEFAULT_SCENE, "Other"))


class CompileTests(unittest.TestCase):
    def setUp(self):
        self.s = resolve_settings({}, {})  # light: 854x480 at 30 fps

    def test_default_scene_is_letterbox_only(self):
        inputs, graph, label = scenes.compile_scene(
            scenes.DEFAULT_SCENE, self.s, "linux", 2)
        self.assertEqual([], inputs)
        self.assertEqual("[0:v]%s[vout]" % LETTERBOX, graph)
        self.assertEqual("[vout]", label)

    def test_crop_and_vaapi_tail(self):
        sc = one_scene({"kind": "browser", "window": "W",
                        "crop": {"x": 10, "y": 20, "w": 640, "h": 360}})
        _, graph, _ = scenes.compile_scene(sc, self.s, "windows", 2,
                                           "format=nv12,hwupload")
        self.assertEqual("[0:v]crop=640:360:10:20,%s[v0];[v0]format=nv12,hwupload[vout]"
                         % LETTERBOX, graph)

    def test_webcam_chromakey_bottom_right(self):
        sc = one_scene(SCREEN, {"kind": "webcam", "device": "Integrated Camera",
                                "chromakey": {"color": "00FF00"}})
        inputs, graph, _ = scenes.compile_scene(sc, self.s, "windows", 2)
        self.assertEqual(["-f", "dshow", "-framerate", "15", "-i",
                          "video=Integrated Camera"], inputs)
        self.assertEqual(
            "[0:v]%s[v0];[2:v]fps=15,scale=170:-2,"
            "chromakey=color=0x00ff00:similarity=0.3:blend=0.0[ov1];"
            "[v0][ov1]overlay=W-w-10:H-h-10[vout]" % LETTERBOX, graph)

    def test_webcam_blur_top_left_and_fps_cap(self):
        sc = one_scene(SCREEN, {"kind": "webcam", "device": "/dev/video0",
                                "corner": "top-left", "size_percent": 10, "blur": 8})
        slow = self.s._replace(fps=10)
        inputs, graph, _ = scenes.compile_scene(sc, slow, "linux", 2)
        self.assertEqual(["-f", "v4l2", "-framerate", "10", "-i", "/dev/video0"], inputs)
        self.assertIn("[2:v]fps=10,scale=84:-2,boxblur=8:1[ov1]", graph)
        self.assertIn("overlay=10:10[vout]", graph)

    def test_macos_webcam_input(self):
        sc = one_scene(SCREEN, {"kind": "webcam", "device": "0"})
        inputs, _, _ = scenes.compile_scene(sc, self.s, "macos", 1)
        self.assertEqual(["-f", "avfoundation", "-framerate", "15", "-i", "0:none"],
                         inputs)

    def test_image_and_text(self):
        sc = one_scene(SCREEN,
                       {"kind": "image", "path": "logo.png", "corner": "top-right"},
                       {"kind": "text", "text": "Be right back", "corner": "bottom-left",
                        "font_file": "C:\\Fonts\\arial.ttf", "font_size": 30})
        inputs, graph, _ = scenes.compile_scene(sc, self.s, "windows", 2)
        self.assertEqual(["-loop", "1", "-framerate", "2", "-i", "logo.png"], inputs)
        self.assertEqual(
            "[0:v]%s[v0];[2:v]scale=170:-2[ov1];[v0][ov1]overlay=W-w-10:10[v1];"
            "[v1]drawtext=fontfile=C\\:/Fonts/arial.ttf:text='Be right back':"
            "x=10:y=h-th-10:fontsize=30:fontcolor=white[vout]" % LETTERBOX, graph)

    def test_deterministic(self):
        sc = one_scene(SCREEN, {"kind": "webcam", "device": "c", "blur": 3})
        a = scenes.compile_scene(sc, self.s, "linux", 2)
        self.assertEqual(a, scenes.compile_scene(sc, self.s, "linux", 2))


class SceneCommandTests(unittest.TestCase):
    def scene_settings(self, window="Game"):
        source = {"kind": "window", "window": window} if window else SCREEN
        sc = one_scene(source, {"kind": "webcam", "device": "Cam"})
        return resolve_settings({}, {})._replace(scene=sc)

    def test_scene_command_windows(self):
        argv = build_command(self.scene_settings(), KEY, "windows", "libx264")
        self.assertIn("title=Game", argv)
        i = argv.index("dshow")
        self.assertEqual(["-f", "dshow", "-framerate", "15", "-i", "video=Cam"],
                         argv[i - 1:i + 5])
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("[2:v]fps=15", graph)
        self.assertEqual(["-map", "[vout]", "-map", "1:a"],
                         argv[argv.index("-map"):argv.index("-map") + 4])
        self.assertNotIn("-vf", argv)

    def test_scene_audio_map_macos_uses_input_zero(self):
        argv = build_command(self.scene_settings(None), KEY, "macos", "libx264")
        self.assertIn("0:a", argv)
        self.assertIn("[1:v]fps=15", argv[argv.index("-filter_complex") + 1])

    def test_scene_vaapi_uploads_last(self):
        s = resolve_settings({}, {})._replace(scene=one_scene(SCREEN))
        argv = build_command(s, KEY, "linux", "h264_vaapi")
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertTrue(graph.endswith("[v0]format=nv12,hwupload[vout]"))

    def test_resolve_settings_loads_scene_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scenes.json")
            with open(path, "w") as fh:
                json.dump({"scenes": [{"name": "talk", "sources": [
                    SCREEN, {"kind": "webcam", "device": "Cam"}]}]}, fh)
            s = resolve_settings({"scene": "talk", "scenes_file": path}, {})
            self.assertEqual("talk", s.scene.name)
            with self.assertRaises(ValueError):
                resolve_settings({"scene": "nope", "scenes_file": path}, {})


class DefaultArgvTests(unittest.TestCase):
    def test_default_argv_matches_v050(self):
        argv = build_command(resolve_settings({}, {}), "K", "linux", "libx264")
        self.assertEqual(
            ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-stats",
             "-fflags", "nobuffer", "-thread_queue_size", "64", "-f", "x11grab",
             "-framerate", "30", "-draw_mouse", "0", "-i", ":0.0",
             "-fflags", "nobuffer", "-thread_queue_size", "64", "-f", "pulse",
             "-i", "default", "-vf", LETTERBOX, "-r", "30", "-c:v", "libx264",
             "-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "main",
             "-pix_fmt", "yuv420p", "-b:v", "1000k", "-maxrate", "1000k",
             "-bufsize", "1000k", "-g", "60", "-bf", "0", "-c:a", "aac",
             "-b:a", "96k", "-ar", "44100", "-ac", "2", "-flush_packets", "1",
             "-flvflags", "no_duration_filesize", "-f", "flv",
             "rtmp://live.twitch.tv/app/K"], argv)


class RecordingTests(unittest.TestCase):
    def test_tee_string_and_command_tail(self):
        s = resolve_settings({}, {})._replace(record_to="C:\\Videos\\out.mkv")
        argv = build_command(s, KEY, "linux", "libx264")
        self.assertEqual(
            ["-flush_packets", "1", "-f", "tee",
             "[f=flv:flvflags=no_duration_filesize]rtmp://live.twitch.tv/app/%s"
             "|[f=matroska:onfail=ignore]C:/Videos/out.mkv" % KEY], argv[-5:])
        self.assertNotIn("-flvflags", argv)

    def test_key_redacted_inside_tee(self):
        s = resolve_settings({}, {})._replace(record_to="out.mkv")
        shown = format_command(build_command(s, KEY, "linux", "libx264"), KEY)
        self.assertNotIn(KEY, shown)
        self.assertIn("rtmp://live.twitch.tv/app/****", shown)

    def test_unsafe_paths_rejected(self):
        with self.assertRaises(ValueError):
            tee_output("rtmp://h/a/k", "a|b.mkv")
        with self.assertRaises(ValueError):
            tee_output("rtmp://h/a/k", "a[1].mkv")
        with self.assertRaises(ValueError):
            tee_output("rtmp://h/a/k|x", "ok.mkv")

    def test_test_recording_ignores_record_to(self):
        s = resolve_settings({}, {})._replace(record_to="out.mkv")
        argv = build_command(s, KEY, "linux", "libx264", record_path="t.mkv")
        self.assertEqual(["-t", "10", "-f", "matroska", "-y", "t.mkv"], argv[-6:])

    def test_config_record_key(self):
        s = resolve_settings({}, {"record": "/tmp/x.mkv"})
        self.assertEqual("/tmp/x.mkv", s.record_to)


if __name__ == "__main__":
    unittest.main()
