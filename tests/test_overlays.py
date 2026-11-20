import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import overlays, scenes
from lightstream.config import resolve_settings

SETTINGS = resolve_settings({}, {})  # light preset: 854x480


def parse(*specs):
    return overlays.parse_overlays("t", list(specs))


def compile_with(*specs, exists=lambda _p: True, tail=""):
    scene = scenes.parse_scenes({"scenes": [{
        "name": "t", "sources": [{"kind": "screen"}], "overlays": list(specs)}]})["t"]
    return scenes.compile_scene(scene, SETTINGS, "linux", 2, tail, exists=exists)


class StageTextTests(unittest.TestCase):
    def stage(self, **raw):
        spec, = parse(raw)
        return overlays.drawtext_stage(spec, "a", "b")

    def test_text_with_position_and_size(self):
        self.assertEqual(
            "[a]drawtext=text='Hello':x=w-tw-20:y=30:fontsize=32:fontcolor=white[b]",
            self.stage(kind="text", text="Hello", corner="top-right",
                       margin_x=20, margin_y=30, font_size=32))

    def test_clock_uses_localtime_with_escaped_colons(self):
        self.assertEqual(
            "[a]drawtext=text='%{localtime\\:%H\\:%M\\:%S}':x=10:y=h-th-10:"
            "fontsize=24:fontcolor=white[b]",
            self.stage(kind="clock", corner="bottom-left"))
        self.assertIn("%H\\:%M}", self.stage(kind="clock", format="short"))

    def test_fps_widget(self):
        self.assertIn("text='FPS %{eif\\:n/(t+0.001)\\:d}'", self.stage(kind="fps"))

    def test_recording_indicator_blinks_red(self):
        text = self.stage(kind="recording")
        self.assertIn("text='REC'", text)
        self.assertIn("fontcolor=red:enable='lt(mod(t,2),1)'", text)

    def test_font_file_is_escaped(self):
        text = self.stage(kind="clock", font_file="C:\\Windows\\Fonts\\arial.ttf")
        self.assertIn("fontfile=C\\:/Windows/Fonts/arial.ttf:text=", text)

    def test_output_is_deterministic(self):
        self.assertEqual(self.stage(kind="fps"), self.stage(kind="fps"))


class ValidationTests(unittest.TestCase):
    def bad(self, **raw):
        with self.assertRaises(ValueError) as ctx:
            parse(raw)
        return str(ctx.exception)

    def test_unknown_kind(self):
        self.assertIn("unknown kind", self.bad(kind="browser"))

    def test_text_rejects_filter_syntax(self):
        self.assertIn("may only use", self.bad(kind="text", text="a%{pid}"))
        self.assertIn("may only use", self.bad(kind="text", text="it's"))

    def test_bad_corner_margin_and_size(self):
        self.assertIn("corner", self.bad(kind="fps", corner="middle"))
        self.assertIn("margin_x", self.bad(kind="fps", margin_x=-1))
        self.assertIn("font_size", self.bad(kind="fps", font_size=2))
        self.assertIn("size_percent", self.bad(kind="image", path="a.png", size_percent=90))

    def test_image_needs_safe_path(self):
        self.assertIn("path", self.bad(kind="image"))
        self.assertIn("unsupported", self.bad(kind="image", path="a,b.png"))

    def test_bad_clock_format(self):
        self.assertIn("format", self.bad(kind="clock", format="12h"))

    def test_too_many_overlays(self):
        with self.assertRaises(ValueError):
            parse(*[{"kind": "fps"}] * (overlays.MAX_OVERLAYS + 1))

    def test_overlays_must_be_a_list(self):
        with self.assertRaises(ValueError):
            overlays.parse_overlays("t", {"kind": "fps"})


class SceneIntegrationTests(unittest.TestCase):
    def test_all_five_kinds_in_order_and_png_input(self):
        inputs, graph, label = compile_with(
            {"kind": "text", "text": "Hi"}, {"kind": "clock"}, {"kind": "fps"},
            {"kind": "recording"},
            {"kind": "image", "path": "/tmp/logo.png", "corner": "bottom-right",
             "size_percent": 10})
        self.assertEqual("[vout]", label)
        self.assertEqual(["-loop", "1", "-framerate", "2", "-i", "/tmp/logo.png"], inputs)
        parts = graph.split(";")
        self.assertEqual(7, len(parts))
        self.assertTrue(parts[-2].startswith("[2:v]scale=84:-2[ovl2]"))
        self.assertEqual("[v4][ovl2]overlay=W-w-10:H-h-10[vout]", parts[-1])

    def test_missing_png_is_skipped_and_reported(self):
        spec = {"kind": "image", "path": "/nope/logo.png"}
        inputs, graph, _ = compile_with({"kind": "fps"}, spec, exists=lambda _p: False)
        self.assertEqual([], inputs)
        self.assertNotIn("overlay=", graph)
        self.assertTrue(graph.endswith("[vout]"))
        self.assertEqual(["/nope/logo.png"],
                         overlays.missing_images(parse(spec), lambda _p: False))

    def test_tail_filter_comes_last(self):
        _, graph, _ = compile_with({"kind": "fps"}, tail="format=nv12,hwupload")
        self.assertTrue(graph.endswith("[v1];[v1]format=nv12,hwupload[vout]"))

    def test_scene_without_overlays_is_unchanged(self):
        _, graph, _ = compile_with()
        self.assertEqual(1, len(graph.split(";")))

    def test_same_arguments_same_text(self):
        specs = ({"kind": "clock"}, {"kind": "recording"})
        self.assertEqual(compile_with(*specs), compile_with(*specs))


if __name__ == "__main__":
    unittest.main()
