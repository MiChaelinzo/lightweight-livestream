import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import __version__
from tools import check_version


class VersionInvariantTests(unittest.TestCase):
    def write_project(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        with handle:
            handle.write(text)
        return handle.name

    def test_runtime_and_project_versions_match(self):
        self.assertEqual(check_version.check_versions(), __version__)

    def test_reader_uses_project_section_not_another_version_key(self):
        path = self.write_project(
            '[build-system]\nversion = "99"\n\n[project]\nname = "x"\nversion = "1.2.3"\n')
        self.assertEqual(check_version.read_project_version(path), "1.2.3")

    def test_mismatch_and_missing_project_version_fail_clearly(self):
        mismatch = self.write_project('[project]\nversion = "9.9.9"\n')
        with self.assertRaises(check_version.VersionError):
            check_version.check_versions(project_file=mismatch)
        missing = self.write_project('[project]\nname = "x"\n')
        with self.assertRaises(check_version.VersionError):
            check_version.read_project_version(missing)

    def test_expected_tag_must_match_both_sources(self):
        self.assertEqual(check_version.check_versions(expected=__version__), __version__)
        with self.assertRaises(check_version.VersionError):
            check_version.check_versions(expected="0.0.0")

    def test_cli_returns_nonzero_without_printing_environment(self):
        err = io.StringIO()
        self.assertEqual(check_version.main(["--expect", "0.0.0"], out=io.StringIO(), err=err), 1)
        self.assertIn("expected version", err.getvalue())
        self.assertNotIn("HOME=", err.getvalue())


if __name__ == "__main__":
    unittest.main()
