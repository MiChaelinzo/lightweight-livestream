import hashlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import __version__, portable
from tools import build_release as br


class FakeRun:
    """Create the outputs of native build tools without executing them."""

    def __init__(self, target, pyinstaller_returncode=0, produce=True,
                 smoke_returncode=0, smoke_report=True):
        self.target = target
        self.pyinstaller_returncode = pyinstaller_returncode
        self.produce = produce
        self.smoke_returncode = smoke_returncode
        self.smoke_report = smoke_report
        self.calls = []
        self.dmg_has_applications_link = False

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append((cmd, kwargs))
        if len(cmd) >= 3 and cmd[1:3] == ["-m", "PyInstaller"]:
            if self.produce and self.pyinstaller_returncode == 0:
                self._pyinstaller(cmd)
            return subprocess.CompletedProcess(cmd, self.pyinstaller_returncode, "", "")

        if "--self-test" in cmd:
            if self.smoke_report is not None and "--self-test-output" in cmd:
                path = cmd[cmd.index("--self-test-output") + 1]
                payload = ({"app": "LightStream", "ok": True, "checks": []}
                           if self.smoke_report is True else self.smoke_report)
                data = (json.dumps(payload).encode("utf-8") if isinstance(payload, dict)
                        else str(payload).encode("utf-8"))
                self._write(path, data)
            return subprocess.CompletedProcess(cmd, self.smoke_returncode,
                                               "", "")
        tool = os.path.basename(cmd[0])
        if tool == "wix" and "build" in cmd:
            self._write(cmd[cmd.index("-o") + 1], b"fake-msi")
        elif tool == "ditto":
            self._write(cmd[-1], b"fake-zip")
        elif tool == "hdiutil" and len(cmd) > 1 and cmd[1] == "create":
            stage = cmd[cmd.index("-srcfolder") + 1]
            self.dmg_has_applications_link = os.path.islink(os.path.join(stage, "Applications"))
            self._write(cmd[-1], b"fake-dmg")
        elif tool == "pkgbuild":
            self._write(cmd[-1], b"fake-pkg")
        elif tool == "appimagetool":
            self._write(cmd[-1], b"fake-appimage", executable=True)
        elif tool == "dpkg-deb" and "--build" in cmd:
            self._write(cmd[-1], b"fake-deb")
        elif tool == "rpmbuild":
            definition = cmd[cmd.index("--define") + 1]
            top = definition.split(" ", 1)[1]
            arch = cmd[cmd.index("--target") + 1]
            self._write(os.path.join(top, "RPMS", arch,
                                     "lightstream-9.9.9-1.%s.rpm" % arch), b"fake-rpm")
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    def _write(self, path, data, executable=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        if executable:
            os.chmod(path, 0o755)

    def _pyinstaller(self, cmd):
        dist = cmd[cmd.index("--distpath") + 1]
        os.makedirs(dist, exist_ok=True)
        if self.target == "windows":
            if "--onefile" in cmd:
                self._write(os.path.join(dist, "LightStream.exe"), b"fake-exe", True)
            else:
                self._write(os.path.join(dist, "LightStream", "LightStream.exe"),
                            b"fake-exe", True)
                self._write(os.path.join(dist, "LightStream", "_internal", "runtime.dll"),
                            b"fake-dll")
        elif self.target == "macos":
            app = os.path.join(dist, "LightStream.app", "Contents")
            self._write(os.path.join(app, "MacOS", "LightStream"), b"fake-app", True)
            os.makedirs(app, exist_ok=True)
            with open(os.path.join(app, "Info.plist"), "wb") as handle:
                plistlib.dump({"CFBundleName": "LightStream"}, handle)
        else:
            if "--onefile" in cmd:
                self._write(os.path.join(dist, "LightStream"), b"fake-linux", True)
            else:
                self._write(os.path.join(dist, "LightStream", "LightStream"),
                            b"fake-linux", True)
                self._write(os.path.join(dist, "LightStream", "_internal", "runtime.so"),
                            b"fake-runtime")


def has_pyinstaller(name):
    return object()


def all_tools(name):
    return "/tools/" + name


def commands(run):
    return [call[0] for call in run.calls]


class ReleaseNamingAndPlanTests(unittest.TestCase):
    def test_commands_use_native_icons_metadata_and_expected_bundle_modes(self):
        win_portable = br.pyinstaller_command(
            "windows", "e.py", "d", "w", variant="portable", version_file="v.txt")
        win_installed = br.pyinstaller_command(
            "windows", "e.py", "d", "w", variant="installed", version_file="v.txt")
        mac = br.pyinstaller_command("macos", "e.py", "d", "w", architecture="arm64")
        lin_archive = br.pyinstaller_command("linux", "e.py", "d", "w", variant="archive")
        lin_installed = br.pyinstaller_command("linux", "e.py", "d", "w", variant="installed")
        self.assertIn("--onefile", win_portable)
        self.assertIn("--onedir", win_installed)
        self.assertIn("--version-file", win_installed)
        self.assertIn(br.WINDOWS_ICON, win_portable)
        self.assertIn(br.MACOS_ICON, mac)
        self.assertEqual(mac[mac.index("--target-architecture") + 1], "arm64")
        self.assertIn("--onefile", lin_archive)
        self.assertIn("--onedir", lin_installed)
        for command in (win_portable, win_installed, mac, lin_archive, lin_installed):
            self.assertIn("--noupx", command)
            self.assertNotIn("--add-binary", command)
            self.assertFalse(any(part.endswith(".spec") for part in command))

    def test_every_artifact_name_has_platform_and_normalized_architecture(self):
        expected = {
            ("windows", "portable"): "LightStream-1.2.3-windows-x86_64-portable-unsigned.zip",
            ("windows", "msi"): "LightStream-1.2.3-windows-x86_64-unsigned.msi",
            ("macos", "zip"): "LightStream-1.2.3-macos-arm64-unsigned.zip",
            ("macos", "dmg"): "LightStream-1.2.3-macos-arm64-unsigned.dmg",
            ("macos", "pkg"): "LightStream-1.2.3-macos-arm64-unsigned.pkg",
            ("linux", "tar.gz"): "LightStream-1.2.3-linux-x86_64.tar.gz",
            ("linux", "AppImage"): "LightStream-1.2.3-linux-x86_64.AppImage",
            ("linux", "deb"): "LightStream-1.2.3-linux-x86_64.deb",
            ("linux", "rpm"): "LightStream-1.2.3-linux-x86_64.rpm",
        }
        for (target, kind), name in expected.items():
            arch = "arm64" if target == "macos" else "AMD64"
            self.assertEqual(br.artifact_name("1.2.3", target, arch, kind), name)

    def test_platform_architecture_and_format_validation_is_explicit(self):
        self.assertEqual(br.detect_platform("win32"), "windows")
        self.assertEqual(br.detect_platform("darwin"), "macos")
        self.assertEqual(br.detect_platform("linux2"), "linux")
        with self.assertRaises(br.BuildError):
            br.detect_platform("freebsd13")
        with self.assertRaises(br.BuildError):
            br.machine_label("i686")
        with self.assertRaises(br.BuildError):
            br.resolve_formats("linux", ["snap"])
        with self.assertRaises(br.BuildError):
            br.require_native_target("windows", "linux")

    def test_version_resource_has_stable_product_identity(self):
        text = br.windows_version_info("1.2.3")
        self.assertIn("filevers=(1, 2, 3, 0)", text)
        self.assertIn("LightStream desktop broadcaster", text)
        self.assertIn("ProductVersion', '1.2.3'", text)
        with self.assertRaises(br.BuildError):
            br.windows_version_info("1.2")

    def test_dry_run_lists_all_artifacts_without_building_or_secrets(self):
        run = FakeRun("linux")
        output = io.StringIO()
        with redirect_stdout(output):
            code = br.main(["--dry-run", "--platform", "windows",
                            "--architecture", "x86_64", "--version", "1.2.3"],
                           run=run, host_name="linux", machine="AMD64")
        self.assertEqual(code, 0)
        self.assertEqual(run.calls, [])
        text = output.getvalue()
        self.assertIn("windows-x86_64-portable-unsigned.zip", text)
        self.assertIn("windows-x86_64-unsigned.msi", text)
        self.assertIn("FFmpeg: external dependency, not bundled", text)
        self.assertNotIn("PASSWORD", text)


class InstallerMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def windows_app(self):
        app = os.path.join(self.tmp.name, "LightStream")
        os.makedirs(os.path.join(app, "_internal"))
        with open(os.path.join(app, "LightStream.exe"), "wb") as handle:
            handle.write(b"exe")
        with open(os.path.join(app, "_internal", "runtime.dll"), "wb") as handle:
            handle.write(b"dll")
        return app

    def test_wix_source_is_deterministic_per_user_onedir_with_start_menu_shortcut(self):
        app = self.windows_app()
        first = br.wix_source(app, "1.2.3", "x86_64")
        second = br.wix_source(app, "1.2.3", "x86_64")
        self.assertEqual(first, second)
        root = ET.fromstring(first)
        ns = {"w": "http://wixtoolset.org/schemas/v4/wxs"}
        package = root.find("w:Package", ns)
        self.assertEqual(package.attrib["Scope"], "perUser")
        self.assertEqual(package.attrib["UpgradeCode"], br.WIX_UPGRADE_CODE)
        self.assertIsNotNone(root.find(".//w:StandardDirectory[@Id='LocalAppDataFolder']", ns))
        self.assertIsNotNone(root.find(".//w:StandardDirectory[@Id='ProgramMenuFolder']", ns))
        shortcut = root.find(".//w:Shortcut", ns)
        self.assertEqual(shortcut.attrib["Name"], "LightStream")
        sources = [node.attrib["Source"] for node in root.findall(".//w:File", ns)]
        self.assertEqual(len(sources), 2)
        self.assertFalse(any("portable.flag" in source for source in sources))
        self.assertEqual(br.wix_command("a.wxs", "a.msi", "AMD64", "wix")[:5],
                         ["wix", "build", "-arch", "x64", "-o"])

    def test_macos_plist_records_identity_version_and_architecture(self):
        app = os.path.join(self.tmp.name, "LightStream.app", "Contents")
        os.makedirs(app)
        path = os.path.join(app, "Info.plist")
        with open(path, "wb") as handle:
            plistlib.dump({}, handle)
        br._update_macos_plist(os.path.dirname(app), "1.2.3", "arm64")
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
        self.assertEqual(data["CFBundleIdentifier"], br.BUNDLE_ID)
        self.assertEqual(data["CFBundleShortVersionString"], "1.2.3")
        self.assertEqual(data["LightStreamBuildArchitecture"], "arm64")

    def test_linux_desktop_and_package_metadata_declares_external_ffmpeg(self):
        desktop = br.desktop_entry()
        self.assertIn("Categories=AudioVideo;Recorder;", desktop)
        self.assertIn("Exec=lightstream-gui", desktop)
        self.assertIn("Terminal=false", desktop)
        deb = br.debian_control("1.2.3", "x86_64", 42)
        self.assertIn("Architecture: amd64", deb)
        self.assertIn("Recommends: ffmpeg", deb)
        spec = br.rpm_spec("1.2.3", "x86_64", "/tmp/root")
        self.assertIn("BuildArch:      x86_64", spec)
        self.assertIn("Recommends:     ffmpeg", spec)
        self.assertNotIn("portable.flag", desktop + deb + spec)

    def test_linux_installed_tree_uses_xdg_runtime_layout_without_ffmpeg(self):
        app = os.path.join(self.tmp.name, "app")
        os.makedirs(app)
        with open(os.path.join(app, "LightStream"), "wb") as handle:
            handle.write(b"app")
        stage = br._stage_linux_root(app, os.path.join(self.tmp.name, "root"), "1.2.3")
        self.assertTrue(os.path.isfile(os.path.join(stage, "usr", "bin", "lightstream-gui")))
        self.assertTrue(os.path.isfile(os.path.join(
            stage, "usr", "share", "applications", br.LINUX_DESKTOP_NAME)))
        all_names = [name for _folder, _dirs, files in os.walk(stage) for name in files]
        self.assertFalse(any(name.lower().startswith("ffmpeg") for name in all_names))
        self.assertNotIn("portable.flag", all_names)


class NativeBuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "release")

    def test_windows_portable_and_msi_include_smoked_separate_builds(self):
        run = FakeRun("windows")
        names = br.build("windows", "9.9.9", self.out, run=run,
                         find_module=has_pyinstaller, which=all_tools,
                         machine="x86_64", environ={})
        self.assertEqual(names, [
            "LightStream-9.9.9-windows-x86_64-portable-unsigned.zip",
            "LightStream-9.9.9-windows-x86_64-unsigned.msi",
            "SHA256SUMS.txt",
        ])
        with zipfile.ZipFile(os.path.join(self.out, names[0])) as archive:
            members = set(archive.namelist())
        self.assertIn("LightStreamPortable/LightStream.exe", members)
        self.assertIn("LightStreamPortable/portable.flag", members)
        self.assertIn("LightStreamPortable/ffmpeg/PUT-FFMPEG-HERE.txt", members)
        self.assertFalse([name for name in members if name.endswith("ffmpeg.exe")])
        pyinstaller = [c for c in commands(run) if c[1:3] == ["-m", "PyInstaller"]]
        self.assertEqual(len(pyinstaller), 2)
        self.assertIn("--onefile", pyinstaller[0])
        self.assertIn("--onedir", pyinstaller[1])
        smoke = [c for c in commands(run) if "--self-test" in c]
        self.assertEqual(len(smoke), 2)
        self.assertTrue(all("--self-test-json" in c for c in smoke))
        self.assertTrue(all("--self-test-output" in c for c in smoke))
        self.assertTrue(any(os.path.basename(c[0]) == "wix" for c in commands(run)))

    def test_optional_windows_signing_is_secret_driven_and_named(self):
        certificate = os.path.join(self.tmp.name, "certificate.pfx")
        with open(certificate, "wb") as handle:
            handle.write(b"fake")
        run = FakeRun("windows")
        env = {"LIGHTSTREAM_WINDOWS_CERTIFICATE": certificate,
               "LIGHTSTREAM_WINDOWS_CERTIFICATE_PASSWORD": "SECRET-PASSWORD",
               "LIGHTSTREAM_SIGNTOOL": "/tools/signtool"}
        names = br.build("windows", "9.9.9", self.out, run=run,
                         find_module=has_pyinstaller, which=all_tools,
                         machine="x86_64", formats=("portable",), environ=env)
        self.assertEqual(names[0], "LightStream-9.9.9-windows-x86_64-portable-signed.zip")
        sign_calls = [c for c in commands(run) if len(c) > 1 and c[1] == "sign"]
        verify_calls = [c for c in commands(run) if len(c) > 1 and c[1] == "verify"]
        self.assertEqual((len(sign_calls), len(verify_calls)), (1, 1))
        self.assertNotIn("SECRET-PASSWORD", "\n".join(br.plan(
            "windows", "9.9.9", self.out, "x86_64", ("portable",))))

    def test_macos_zip_dmg_and_pkg_are_required_and_smoked(self):
        run = FakeRun("macos")
        names = br.build("macos", "9.9.9", self.out, run=run,
                         find_module=has_pyinstaller, which=all_tools,
                         machine="arm64", environ={})
        self.assertEqual(names[:-1], [
            "LightStream-9.9.9-macos-arm64-unsigned.zip",
            "LightStream-9.9.9-macos-arm64-unsigned.dmg",
            "LightStream-9.9.9-macos-arm64-unsigned.pkg",
        ])
        self.assertTrue(run.dmg_has_applications_link)
        self.assertEqual(len([c for c in commands(run) if "--self-test" in c]), 1)
        self.assertTrue(any(os.path.basename(c[0]) == "hdiutil" and "verify" in c
                            for c in commands(run)))
        self.assertTrue(any(os.path.basename(c[0]) == "pkgutil" for c in commands(run)))

    def test_optional_macos_signing_and_notarization_are_command_planned(self):
        run = FakeRun("macos")
        env = {
            "LIGHTSTREAM_MACOS_APP_IDENTITY": "Developer ID Application: Example",
            "LIGHTSTREAM_MACOS_INSTALLER_IDENTITY": "Developer ID Installer: Example",
            "LIGHTSTREAM_MACOS_NOTARY_PROFILE": "lightstream-notary",
            "LIGHTSTREAM_MACOS_KEYCHAIN": "/tmp/release.keychain-db",
        }
        names = br.build("macos", "9.9.9", self.out, run=run,
                         find_module=has_pyinstaller, which=all_tools,
                         machine="arm64", formats=("zip", "pkg"), environ=env)
        self.assertIn("LightStream-9.9.9-macos-arm64-signed-notarized.zip", names)
        self.assertIn("LightStream-9.9.9-macos-arm64-signed-notarized.pkg", names)
        calls = commands(run)
        self.assertTrue(any(os.path.basename(c[0]) == "codesign" and "--options" in c
                            for c in calls))
        submissions = [c for c in calls if len(c) > 2 and c[1:3] == ["notarytool", "submit"]]
        self.assertEqual(len(submissions), 2)  # app submission ZIP and signed PKG
        self.assertTrue(all("--keychain-profile" in c and "--keychain" in c
                            for c in submissions))
        self.assertTrue(any(os.path.basename(c[0]) == "pkgbuild" and "--sign" in c
                            for c in calls))

    def test_linux_tar_appimage_deb_and_rpm_are_built_and_checked(self):
        run = FakeRun("linux")
        names = br.build("linux", "9.9.9", self.out, run=run,
                         find_module=has_pyinstaller, which=all_tools,
                         machine="AMD64", environ={})
        self.assertEqual(names[:-1], [
            "LightStream-9.9.9-linux-x86_64.tar.gz",
            "LightStream-9.9.9-linux-x86_64.AppImage",
            "LightStream-9.9.9-linux-x86_64.deb",
            "LightStream-9.9.9-linux-x86_64.rpm",
        ])
        with tarfile.open(os.path.join(self.out, names[0])) as archive:
            self.assertEqual(sorted(archive.getnames()), ["LightStream", "README.txt"])
            self.assertTrue(archive.getmember("LightStream").mode & 0o111)
        tool_names = [os.path.basename(c[0]) for c in commands(run)]
        for tool in ("appimagetool", "dpkg-deb", "rpmbuild", "rpm"):
            self.assertIn(tool, tool_names)
        smoke = [c for c in commands(run) if "--self-test" in c]
        self.assertEqual(len(smoke), 3)  # tar binary, onedir binary, AppImage
        appimage_smoke = next(c for c in smoke if c[0].endswith(".AppImage"))
        self.assertEqual(appimage_smoke[1], "--appimage-extract-and-run")

    def test_missing_required_native_tool_fails_instead_of_silently_skipping(self):
        with self.assertRaises(br.BuildError) as windows:
            br.build("windows", "9.9.9", self.out, run=FakeRun("windows"),
                     find_module=has_pyinstaller, which=lambda name: None,
                     machine="x86_64", formats=("msi",), environ={})
        self.assertIn("wix is required", str(windows.exception))
        with self.assertRaises(br.BuildError) as mac:
            br.build("macos", "9.9.9", self.out, run=FakeRun("macos"),
                     find_module=has_pyinstaller,
                     which=lambda name: None if name == "hdiutil" else name,
                     machine="arm64", formats=("dmg",), environ={})
        self.assertIn("hdiutil is required", str(mac.exception))

    def test_smoke_test_failure_stops_packaging(self):
        run = FakeRun("linux", smoke_returncode=7)
        with self.assertRaises(br.BuildError) as context:
            br.build("linux", "9.9.9", self.out, run=run,
                     find_module=has_pyinstaller, which=all_tools,
                     machine="x86_64", formats=("tar.gz",), environ={})
        self.assertIn("self-test failed", str(context.exception))

    def test_smoke_test_requires_a_valid_passing_json_report(self):
        executable = os.path.join(self.tmp.name, "LightStream")
        with open(executable, "wb") as handle:
            handle.write(b"fake")
        for report in (None, "not-json", {"app": "LightStream", "ok": False},
                       {"app": "WrongApp", "ok": True}):
            with self.subTest(report=report):
                with self.assertRaises(br.BuildError):
                    br.smoke_test(executable, run=FakeRun("linux", smoke_report=report))

    def test_checksums_match_every_artifact(self):
        names = br.build("linux", "9.9.9", self.out, run=FakeRun("linux"),
                         find_module=has_pyinstaller, which=all_tools,
                         machine="x86_64", formats=("tar.gz",), environ={})
        with open(os.path.join(self.out, br.CHECKSUM_FILE), encoding="utf-8") as handle:
            line = handle.read()
        with open(os.path.join(self.out, names[0]), "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(line, "%s  %s\n" % (digest, names[0]))

    def test_primary_archives_are_byte_reproducible_with_fixed_epoch(self):
        first = os.path.join(self.tmp.name, "one")
        second = os.path.join(self.tmp.name, "two")
        env = {"SOURCE_DATE_EPOCH": "1800000000"}
        for output in (first, second):
            br.build("linux", "9.9.9", output, run=FakeRun("linux"),
                     find_module=has_pyinstaller, which=all_tools,
                     machine="x86_64", formats=("tar.gz",), environ=env)
        name = "LightStream-9.9.9-linux-x86_64.tar.gz"
        self.assertEqual(br.sha256_file(os.path.join(first, name)),
                         br.sha256_file(os.path.join(second, name)))

    def test_missing_pyinstaller_and_output_are_clear_errors(self):
        with self.assertRaises(br.BuildError) as missing:
            br.build("linux", "9.9.9", self.out, run=FakeRun("linux"),
                     find_module=lambda name: None, which=all_tools,
                     machine="x86_64", formats=("tar.gz",), environ={})
        self.assertIn("pip install pyinstaller", str(missing.exception))
        with self.assertRaises(br.BuildError):
            br.build("windows", "9.9.9", self.out,
                     run=FakeRun("windows", produce=False),
                     find_module=has_pyinstaller, which=all_tools,
                     machine="x86_64", formats=("portable",), environ={})


class FfmpegHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make_file(self, name="ffmpeg-custom"):
        path = os.path.join(self.dir, name)
        open(path, "w").close()
        return path

    def test_guidance_per_platform(self):
        self.assertIn("gyan.dev", portable.ffmpeg_guidance("win32"))
        self.assertIn("brew install ffmpeg", portable.ffmpeg_guidance("darwin"))
        self.assertIn("apt install ffmpeg", portable.ffmpeg_guidance("linux"))
        for name in ("win32", "darwin", "linux"):
            self.assertIn("https://ffmpeg.org/download.html", portable.ffmpeg_guidance(name))
        self.assertEqual(portable.ffmpeg_download_url("win32"), portable.WINDOWS_BUILDS_URL)
        self.assertEqual(portable.ffmpeg_download_url("linux"), portable.FFMPEG_DOWNLOAD_URL)

    def test_validate_ok(self):
        path = self.make_file()
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "ffmpeg version 6.0\nmore", "")
        self.assertEqual(portable.validate_ffmpeg(path, run=run), (True, "ffmpeg version 6.0"))

    def test_validate_rejects_missing_wrong_and_failing(self):
        path = self.make_file()
        self.assertFalse(portable.validate_ffmpeg(os.path.join(self.dir, "nope"))[0])
        wrong = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "hello", "")
        self.assertFalse(portable.validate_ffmpeg(path, run=wrong)[0])
        failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "ffmpeg version", "")
        self.assertFalse(portable.validate_ffmpeg(path, run=failing)[0])

        def boom(cmd, **kw):
            raise OSError("not executable")
        self.assertFalse(portable.validate_ffmpeg(path, run=boom)[0])

    def test_save_keeps_other_settings_and_find_ffmpeg_uses_it(self):
        chosen = self.make_file()
        config = os.path.join(self.dir, "sub", "config.json")
        os.makedirs(os.path.dirname(config))
        with open(config, "w") as handle:
            json.dump({"platform": "youtube"}, handle)
        portable.save_configured_ffmpeg(chosen, config)
        with open(config) as handle:
            self.assertEqual(json.load(handle), {"platform": "youtube", "ffmpeg_path": chosen})
        self.assertEqual(portable.configured_ffmpeg(config), chosen)
        empty_root = os.path.join(self.dir, "root")
        os.makedirs(empty_root)
        self.assertEqual(portable.find_ffmpeg(empty_root, which=lambda name: "/usr/bin/ffmpeg",
                                              configured=chosen), chosen)

    def test_find_ffmpeg_checks_homebrew_dirs_on_macos_only(self):
        root = tempfile.mkdtemp()
        brew = os.path.join(root, "brew")
        os.makedirs(brew)
        open(os.path.join(brew, "ffmpeg"), "w").close()
        with mock.patch.object(portable, "MACOS_FFMPEG_DIRS", (brew,)):
            none = lambda name: None
            self.assertEqual(portable.find_ffmpeg(root, which=none, platform_name="darwin"),
                             os.path.join(brew, "ffmpeg"))
            self.assertIsNone(portable.find_ffmpeg(root, which=none, platform_name="linux"))


if __name__ == "__main__":
    unittest.main()
