import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import cli
from lightstream import scene_collections as sc
from lightstream.scenes import EXAMPLE_SCENES, load_scenes, parse_scene


def scenes_file(tmp, scenes=None):
    path = os.path.join(tmp, "scenes.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"scenes": scenes or EXAMPLE_SCENES["scenes"]}, fh)
    return path


def text_of(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ExampleCollectionTests(unittest.TestCase):
    def test_four_named_files_all_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = sc.write_example_collection(os.path.join(tmp, "scenes"))
            self.assertEqual(["gaming.json", "just-chatting.json", "retro.json", "work.json"],
                             sorted(os.path.basename(p) for p in paths))
            for path in paths:
                parse_scene(read(path))
            with open(paths[0], encoding="utf-8") as fh:
                raw = fh.read()
            self.assertIn("\n  ", raw)  # indented, human readable

    def test_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            sc.write_example_collection(tmp)
            with self.assertRaises(ValueError):
                sc.write_example_collection(tmp)


class FileNameTests(unittest.TestCase):
    def test_safe_names(self):
        self.assertEqual("just-chatting.json", sc.scene_filename("Just Chatting"))
        self.assertEqual("etc-passwd.json", sc.scene_filename("../etc/passwd"))
        with self.assertRaises(ValueError):
            sc.scene_filename("///")


class ExportImportTests(unittest.TestCase):
    def test_export_single_and_reimport(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = scenes_file(tmp)
            dest = os.path.join(tmp, "out", "g.json")
            sc.export_scene(src, "game-with-webcam", dest)
            self.assertEqual("game-with-webcam", read(dest)["name"])
            other = os.path.join(tmp, "other.json")
            added, replaced = sc.import_scenes(other, dest)
            self.assertEqual((["game-with-webcam"], []), (added, replaced))
            self.assertEqual(["game-with-webcam"], list(load_scenes(other)))

    def test_export_collection_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = scenes_file(tmp)
            folder = os.path.join(tmp, "scenes")
            paths = sc.export_collection(src, folder)
            self.assertEqual(3, len(paths))
            dest = os.path.join(tmp, "copy.json")
            added, _ = sc.import_scenes(dest, folder)
            self.assertEqual(sorted(load_scenes(src)), sorted(added))
            by_name = {r["name"]: r for r in read(dest)["scenes"]}
            for raw in read(src)["scenes"]:
                self.assertEqual(raw, by_name[raw["name"]])

    def test_export_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = scenes_file(tmp)
            folder = os.path.join(tmp, "scenes")
            sc.export_collection(src, folder)
            with self.assertRaises(ValueError):
                sc.export_collection(src, folder)
            self.assertEqual(3, len(sc.export_collection(src, folder, force=True)))

    def test_export_unknown_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                sc.export_scene(scenes_file(tmp), "nope", os.path.join(tmp, "x.json"))
            self.assertIn("Available", str(ctx.exception))

    def test_import_accepts_scenes_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapped = scenes_file(tmp)
            target = os.path.join(tmp, "new", "scenes.json")
            added, _ = sc.import_scenes(target, wrapped)
            self.assertEqual(3, len(added))

    def test_import_duplicate_needs_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = scenes_file(tmp)
            one = os.path.join(tmp, "one.json")
            sc.export_scene(src, "browser-source", one)
            with self.assertRaises(ValueError):
                sc.import_scenes(src, one)
            self.assertEqual((([]), ["browser-source"]), sc.import_scenes(src, one, True))

    def test_import_rejects_invalid_scene_and_keeps_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = scenes_file(tmp)
            before = text_of(src)
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                json.dump({"name": "x", "sources": [{"kind": "webcam", "device": "c"}]}, fh)
            with self.assertRaises(ValueError):
                sc.import_scenes(src, bad)
            self.assertEqual(before, text_of(src))

    def test_import_rejects_missing_path_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sc.import_scenes(os.path.join(tmp, "s.json"), os.path.join(tmp, "none"))
            broken = os.path.join(tmp, "broken.json")
            with open(broken, "w") as fh:
                fh.write("{nope")
            with self.assertRaises(ValueError):
                sc.import_scenes(os.path.join(tmp, "s.json"), broken)


class SaveDuplicateTests(unittest.TestCase):
    def test_save_adds_then_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scenes.json")
            sc.save_scene(path, {"name": "a", "sources": [{"kind": "screen"}]})
            sc.save_scene(path, {"name": "a", "sources": [{"kind": "browser"}]})
            self.assertEqual("browser", read(path)["scenes"][0]["sources"][0]["kind"])
            self.assertEqual(1, len(read(path)["scenes"]))

    def test_save_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sc.save_scene(os.path.join(tmp, "s.json"), {"name": "a", "sources": []})

    def test_duplicate_names_and_deep_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = scenes_file(tmp)
            self.assertEqual("browser-source-copy", sc.duplicate_scene(path, "browser-source"))
            self.assertEqual("browser-source-copy-2", sc.duplicate_scene(path, "browser-source"))
            self.assertEqual("mine", sc.duplicate_scene(path, "browser-source", "mine"))
            with self.assertRaises(ValueError):
                sc.duplicate_scene(path, "browser-source", "mine")
            scenes = {s["name"]: s for s in read(path)["scenes"]}
            scenes["mine"]["sources"][0]["window"] = "changed"
            self.assertNotEqual(scenes["browser-source"]["sources"][0]["window"], "changed")
            load_scenes(path)


class CliTests(unittest.TestCase):
    def run_cli(self, argv, home):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": home}, clear=True):
            code = cli.main(argv, out)
        return code, out.getvalue()

    def test_example_collection_import_export_flow(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "scenes.json")
            code, _ = self.run_cli(["scenes", "example", "--collection",
                                    "--scenes-file", path], home)
            self.assertEqual(0, code)
            self.assertTrue(os.path.exists(os.path.join(home, "scenes", "gaming.json")))
            code, text = self.run_cli(["scenes", "import", os.path.join(home, "scenes"),
                                       "--scenes-file", path], home)
            self.assertEqual(0, code)
            self.assertIn("Imported 4 new", text)
            code, text = self.run_cli(["scenes", "list", "--scenes-file", path], home)
            self.assertEqual(["gaming", "just-chatting", "retro", "work"],
                             sorted(text.split()))
            code, text = self.run_cli(["scenes", "export", "work", "--scenes-file", path,
                                       "--to", os.path.join(home, "w.json")], home)
            self.assertEqual(0, code)
            self.assertEqual("work", read(os.path.join(home, "w.json"))["name"])

    def test_import_needs_path_and_clashes_are_plain_errors(self):
        with tempfile.TemporaryDirectory() as home:
            path = scenes_file(home)
            code, text = self.run_cli(["scenes", "import", "--scenes-file", path], home)
            self.assertEqual(2, code)
            self.assertIn("Error:", text)
            code, text = self.run_cli(["scenes", "export", "--scenes-file", path], home)
            self.assertEqual(0, code)
            code, text = self.run_cli(["scenes", "export", "--scenes-file", path], home)
            self.assertEqual(2, code)
            self.assertIn("--force", text)


if __name__ == "__main__":
    unittest.main()
