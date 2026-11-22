import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import analytics, gui_controller as gc
from lightstream.fileio import create_private_text, write_private_text

POSIX = os.name == "posix"


class PrivateWriteTests(unittest.TestCase):
    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_write_replaces_atomically_and_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            write_private_text(path, "one")
            write_private_text(path, "two")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual("two", fh.read())
            self.assertEqual(["a.json"], os.listdir(d))

    def test_failed_write_keeps_old_file_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.json")
            write_private_text(path, "old")
            with self.assertRaises(TypeError):
                write_private_text(path, 123)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual("old", fh.read())
            self.assertEqual(["a.json"], os.listdir(d))

    @unittest.skipUnless(POSIX, "POSIX modes only")
    def test_mode_is_owner_only_even_with_open_umask(self):
        old = os.umask(0)
        try:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "a.json")
                write_private_text(path, "x")
                self.assertEqual(0o600, self.mode(path))
                other = os.path.join(d, "b.json")
                create_private_text(other, "x")
                self.assertEqual(0o600, self.mode(other))
        finally:
            os.umask(old)

    def test_create_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.json")
            create_private_text(path, "x")
            with self.assertRaises(FileExistsError):
                create_private_text(path, "y")

    def test_create_removes_partial_file_on_write_failure(self):
        class Unwritable:
            def __str__(self):
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.json")
            with self.assertRaises(TypeError):
                create_private_text(path, Unwritable())
            self.assertFalse(os.path.exists(path))
            create_private_text(path, "ok")

    @unittest.skipUnless(POSIX, "POSIX modes only")
    def test_prefs_and_history_files_are_private(self):
        old = os.umask(0)
        try:
            with tempfile.TemporaryDirectory() as d:
                prefs = os.path.join(d, "prefs.json")
                gc.save_prefs(prefs, {"platform": "twitch"})
                self.assertEqual(0o600, self.mode(prefs))
                hist = analytics.append_history(d, {"n": 1})
                self.assertEqual(0o600, self.mode(hist))
                with open(hist, encoding="utf-8") as fh:
                    self.assertEqual([{"n": 1}], json.load(fh))
        finally:
            os.umask(old)


if __name__ == "__main__":
    unittest.main()
