import os
import subprocess
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_SUFFIXES = (
    ".whl", ".exe", ".msi", ".pkg", ".dmg", ".deb", ".rpm", ".appimage",
    ".apk", ".aab", ".ipa", ".pfx", ".p12", ".mobileprovision",
)
FORBIDDEN_SEGMENTS = {
    "node_modules", "dist", "build", "ms-playwright", ".playwright", ".android",
}


class RepositoryArtifactPolicyTests(unittest.TestCase):
    def tracked_files(self):
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True)
        return [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]

    def test_release_binaries_signing_material_and_dependency_trees_are_not_tracked(self):
        violations = []
        for path in self.tracked_files():
            lowered = path.lower()
            segments = set(lowered.split("/"))
            if (lowered.endswith(FORBIDDEN_SUFFIXES) or segments & FORBIDDEN_SEGMENTS
                    or any(segment.startswith(".venv") for segment in segments)):
                violations.append(path)
        self.assertEqual(violations, [], "forbidden tracked artifacts: " + ", ".join(violations))

    def test_ffmpeg_binary_is_not_tracked(self):
        violations = [path for path in self.tracked_files()
                      if os.path.basename(path).lower() in ("ffmpeg", "ffmpeg.exe")]
        self.assertEqual(violations, [], "FFmpeg must remain an external dependency")


if __name__ == "__main__":
    unittest.main()
