import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "release.yml")


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(WORKFLOW, encoding="utf-8") as handle:
            cls.text = handle.read()

    def test_checkout_has_full_history_and_tag_provenance_checks_main(self):
        self.assertIn("fetch-depth: 0", self.text)
        self.assertIn('python tools/check_version.py --expect "${GITHUB_REF_NAME#v}"', self.text)
        self.assertIn("refs/heads/main:refs/remotes/origin/main", self.text)
        self.assertIn('git merge-base --is-ancestor "$tag_commit" origin/main', self.text)
        self.assertIn('git rev-parse "${GITHUB_REF}^{commit}"', self.text)

    def test_runner_platform_and_architecture_are_explicit(self):
        expected = (
            ("windows-latest", "windows", "x86_64"),
            ("macos-15", "macos", "arm64"),
            ("ubuntu-22.04", "linux", "x86_64"),
        )
        for operating_system, target, architecture in expected:
            block = ("- os: %s\n            target: %s\n            architecture: %s"
                     % (operating_system, target, architecture))
            self.assertIn(block, self.text)
        self.assertIn("Record and verify runner architecture", self.text)

    def test_release_dependencies_are_pinned_or_checksum_verified(self):
        self.assertIn("pyinstaller==6.11.1", self.text)
        self.assertIn("wix --version 5.0.2", self.text)
        self.assertIn("appimagetool-x86_64.AppImage", self.text)
        self.assertIn("e8c1169c4af66c3184d7ee110713d4be04befe671fa358e2c1591ee840553b03", self.text)
        self.assertIn("sha256sum --check --strict", self.text)

    def test_each_native_job_runs_all_source_and_packaged_checks(self):
        for command in (
            "python -m unittest discover -s tests",
            'node --test "web/test/*.test.js"',
            "python -m compileall -q src",
            "python tools/export_presets.py --check",
            "python tools/generate_icons.py --check",
            "python -m lightstream gui --self-test --self-test-json",
            "python tools/build_release.py --platform ${{ matrix.target }} --architecture ${{ matrix.architecture }}",
        ):
            self.assertIn(command, self.text)

    def test_all_nine_release_formats_are_required_before_publish(self):
        patterns = (
            "windows-x86_64-portable-*.zip", "windows-x86_64-*.msi",
            "macos-arm64-*.zip", "macos-arm64-*.dmg", "macos-arm64-*.pkg",
            "linux-x86_64.tar.gz", "linux-x86_64.AppImage",
            "linux-x86_64.deb", "linux-x86_64.rpm",
        )
        for pattern in patterns:
            self.assertIn(pattern, self.text)
        self.assertIn('sha256sum "${files[@]}" > SHA256SUMS.txt', self.text)

    def test_signing_is_optional_secret_only_and_material_is_removed(self):
        for secret in (
            "secrets.WINDOWS_CERTIFICATE_PFX_BASE64",
            "secrets.WINDOWS_CERTIFICATE_PASSWORD",
            "secrets.MACOS_CERTIFICATE_P12_BASE64",
            "secrets.MACOS_CERTIFICATE_PASSWORD",
            "secrets.MACOS_APP_IDENTITY",
            "secrets.MACOS_INSTALLER_IDENTITY",
            "secrets.MACOS_NOTARY_PASSWORD",
        ):
            self.assertIn(secret, self.text)
        self.assertIn("Remove temporary signing material", self.text)
        self.assertNotRegex(self.text, re.compile(r"^\s*(printenv|env|set)\s*$", re.MULTILINE))
        self.assertNotIn("dict(os.environ)", self.text)
        self.assertNotIn("print(os.environ)", self.text)
        self.assertNotIn("/proc/self/environ", self.text)

    def test_action_references_remain_on_reviewed_major_versions(self):
        for action in ("actions/checkout@v4", "actions/setup-python@v5",
                       "actions/setup-node@v4", "actions/upload-artifact@v4",
                       "actions/download-artifact@v4"):
            self.assertIn(action, self.text)


if __name__ == "__main__":
    unittest.main()
