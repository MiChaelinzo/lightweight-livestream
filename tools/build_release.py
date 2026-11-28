"""Build native LightStream release artifacts on the current operating system.

PyInstaller cannot cross-compile. The release matrix calls this tool once on
Windows, macOS, and Linux. Every executable is run with ``--self-test`` before
it is packaged. FFmpeg is always an external dependency and is never bundled.

Default artifacts:
  Windows: portable ZIP and per-user MSI (WiX 5)
  macOS:   app ZIP, DMG with Applications link, and PKG for /Applications
  Linux:   tar.gz, AppImage, deb, and rpm

Use ``--formats`` for a smaller local build, for example ``--formats tar.gz``.
"""

import argparse
import gzip
import hashlib
import json
import os
import platform as platform_module
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile
from xml.sax.saxutils import quoteattr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from tools import build_windows_portable as win  # noqa: E402

DEFAULT_OUTPUT = os.path.join("dist", "release")
APP_NAME = "LightStream"
PACKAGE_NAME = "lightstream"
BUNDLE_ID = "io.github.michaelinzo.lightstream"
PUBLISHER = "LightStream contributors"
HOMEPAGE = "https://github.com/MiChaelinzo/lightweight-livestream"
CHECKSUM_FILE = "SHA256SUMS.txt"
PLATFORMS = ("windows", "macos", "linux")
ARCHITECTURES = ("x86_64", "arm64")
FORMATS = {
    "windows": ("portable", "msi"),
    "macos": ("zip", "dmg", "pkg"),
    "linux": ("tar.gz", "AppImage", "deb", "rpm"),
}
SMOKE_TIMEOUT_SECONDS = 90
DEFAULT_SOURCE_DATE_EPOCH = 1704067200
WIX_UPGRADE_CODE = "6F21CB17-44A4-5A53-BD58-19D25D98965A"
ICON_DIR = os.path.join(ROOT, "assets", "icons")
WINDOWS_ICON = os.path.join(ICON_DIR, "lightstream.ico")
MACOS_ICON = os.path.join(ICON_DIR, "lightstream.icns")
LINUX_ICON = os.path.join(ICON_DIR, "lightstream.svg")
LINUX_DESKTOP_NAME = BUNDLE_ID + ".desktop"
LINUX_METAINFO_NAME = BUNDLE_ID + ".metainfo.xml"

LINUX_README = (
    "LightStream (Linux)\n\n"
    "Run ./LightStream from a desktop session. Everything is bundled except FFmpeg.\n"
    "Install FFmpeg with your package manager (for example: sudo apt install ffmpeg)\n"
    "or choose its file in the first-run window. Settings use XDG_CONFIG_HOME.\n"
)
BuildError = win.BuildError


def read_version():
    from lightstream import __version__
    return __version__


def detect_platform(name=None):
    name = name or sys.platform
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    if name.startswith("linux"):
        return "linux"
    raise BuildError("Unsupported release platform %r; expected Windows, macOS, or Linux." % name)


def machine_label(machine=None):
    machine = (machine or platform_module.machine()).lower().replace("-", "_")
    aliases = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}
    label = aliases.get(machine, machine)
    if label not in ARCHITECTURES:
        raise BuildError("Unsupported release architecture %r; expected %s."
                         % (machine, " or ".join(ARCHITECTURES)))
    return label


def require_native_target(target, host_name=None):
    if target not in PLATFORMS:
        raise BuildError("Unsupported release target %r." % target)
    host = detect_platform(host_name)
    if target != host:
        raise BuildError("PyInstaller cannot cross-compile: target %s, current host %s."
                         % (target, host))


def resolve_formats(target, formats=None):
    if target not in FORMATS:
        raise BuildError("Unsupported release target %r." % target)
    if formats is None:
        return FORMATS[target]
    values = tuple(formats)
    unknown = [value for value in values if value not in FORMATS[target]]
    if unknown:
        raise BuildError("Unsupported %s format(s): %s. Choose from: %s."
                         % (target, ", ".join(unknown), ", ".join(FORMATS[target])))
    if not values:
        raise BuildError("At least one release format is required.")
    return values


def _signature_label(target, environ):
    if target == "windows":
        cert = environ.get("LIGHTSTREAM_WINDOWS_CERTIFICATE")
        password = environ.get("LIGHTSTREAM_WINDOWS_CERTIFICATE_PASSWORD")
        if bool(cert) != bool(password):
            raise BuildError("Windows signing needs both certificate path and password secrets.")
        return "signed" if cert else "unsigned"
    if target == "macos":
        app_identity = environ.get("LIGHTSTREAM_MACOS_APP_IDENTITY")
        installer_identity = environ.get("LIGHTSTREAM_MACOS_INSTALLER_IDENTITY")
        if bool(app_identity) != bool(installer_identity):
            raise BuildError("macOS signing needs both application and installer identities.")
        profile = environ.get("LIGHTSTREAM_MACOS_NOTARY_PROFILE")
        if profile and not app_identity:
            raise BuildError("macOS notarization requires configured signing identities.")
        if profile:
            return "signed-notarized"
        return "signed" if app_identity else "unsigned"
    return "unsigned"


def artifact_name(version, target, architecture, kind, signature="unsigned"):
    if target not in FORMATS or kind not in FORMATS[target]:
        raise BuildError("Unsupported artifact: %s/%s." % (target, kind))
    architecture = machine_label(architecture)
    base = "%s-%s-%s-%s" % (APP_NAME, version, target, architecture)
    if target == "windows":
        if kind == "portable":
            return "%s-portable-%s.zip" % (base, signature)
        return "%s-%s.msi" % (base, signature)
    if target == "macos":
        return "%s-%s.%s" % (base, signature, kind)
    extensions = {"tar.gz": "tar.gz", "AppImage": "AppImage", "deb": "deb", "rpm": "rpm"}
    return "%s.%s" % (base, extensions[kind])


def archive_name(version, target, machine=None):
    """Backward-compatible name for the primary archive on each platform."""
    architecture = machine_label(machine)
    kind = {"windows": "portable", "macos": "zip", "linux": "tar.gz"}[target]
    return artifact_name(version, target, architecture, kind)


def _version_tuple(version):
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise BuildError("Release version must be numeric MAJOR.MINOR.PATCH, got %r." % version)
    values = tuple(int(part) for part in parts)
    if any(value > 65535 for value in values):
        raise BuildError("Each release version part must be at most 65535.")
    return values + (0,)


def windows_version_info(version):
    values = _version_tuple(version)
    dotted = ", ".join(str(value) for value in values)
    return """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(%(dotted)s), prodvers=(%(dotted)s),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', '%(publisher)s'),
    StringStruct('FileDescription', 'LightStream desktop broadcaster'),
    StringStruct('FileVersion', '%(version)s'),
    StringStruct('InternalName', 'LightStream'),
    StringStruct('OriginalFilename', 'LightStream.exe'),
    StringStruct('ProductName', 'LightStream'),
    StringStruct('ProductVersion', '%(version)s')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""" % {"dotted": dotted, "publisher": PUBLISHER, "version": version}


def pyinstaller_command(target, entry, dist_dir, work_dir, python=sys.executable,
                        variant="archive", version_file=None, architecture=None):
    if target not in PLATFORMS:
        raise BuildError("Unsupported PyInstaller target %r." % target)
    cmd = [python, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
           "--name", APP_NAME, "--paths", os.path.join(ROOT, "src"),
           "--distpath", dist_dir, "--workpath", work_dir, "--specpath", work_dir]
    if target == "windows":
        cmd += ["--windowed", "--icon", WINDOWS_ICON]
        if version_file:
            cmd += ["--version-file", version_file]
        cmd += ["--onefile" if variant == "portable" else "--onedir"]
    elif target == "macos":
        cmd += ["--windowed", "--onedir", "--icon", MACOS_ICON,
                "--osx-bundle-identifier", BUNDLE_ID]
        if architecture:
            cmd += ["--target-architecture", machine_label(architecture)]
    else:
        cmd += ["--onefile" if variant == "archive" else "--onedir"]
    return cmd + [entry]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(output, names):
    lines = ["%s  %s\n" % (sha256_file(os.path.join(output, name)), name)
             for name in sorted(names)]
    with open(os.path.join(output, CHECKSUM_FILE), "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
    return lines


def _source_epoch(environ):
    raw = environ.get("SOURCE_DATE_EPOCH", str(DEFAULT_SOURCE_DATE_EPOCH))
    try:
        value = int(raw)
    except ValueError:
        raise BuildError("SOURCE_DATE_EPOCH must be an integer.")
    if value < 0:
        raise BuildError("SOURCE_DATE_EPOCH must not be negative.")
    return value


def _zip_tree(source, archive, epoch=DEFAULT_SOURCE_DATE_EPOCH):
    """Write a stable ZIP for the Windows portable directory."""
    timestamp = tuple(__import__("time").gmtime(max(315532800, epoch))[:6])
    base = os.path.dirname(source)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for folder, dirs, files in os.walk(source):
            dirs.sort()
            relative_folder = os.path.relpath(folder, base).replace(os.sep, "/")
            if not files and not dirs:
                info = zipfile.ZipInfo(relative_folder + "/", timestamp)
                info.external_attr = (0o40755 << 16) | 0x10
                zf.writestr(info, b"")
            for name in sorted(files):
                full = os.path.join(folder, name)
                relative = os.path.relpath(full, base).replace(os.sep, "/")
                info = zipfile.ZipInfo(relative, timestamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = 0o100755 if os.access(full, os.X_OK) else 0o100644
                info.external_attr = mode << 16
                with open(full, "rb") as handle:
                    zf.writestr(info, handle.read())


def _tar_files(files, archive, epoch):
    with open(archive, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tf:
                for path, arcname in files:
                    info = tf.gettarinfo(path, arcname=arcname)
                    info.mtime = epoch
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    with open(path, "rb") as handle:
                        tf.addfile(info, handle)


def _write_text(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    if mode is not None:
        os.chmod(path, mode)


def _result_text(result):
    text = ((getattr(result, "stdout", "") or "") + "\n" +
            (getattr(result, "stderr", "") or "")).strip()
    return text[-2000:]


def _run_checked(run, command, description, **kwargs):
    try:
        result = run(command, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError("%s could not run: %s" % (description, exc))
    if result.returncode != 0:
        detail = _result_text(result)
        raise BuildError("%s failed with exit code %d%s" %
                         (description, result.returncode,
                          ": " + detail if detail else "."))
    return result


def smoke_test(executable, run=subprocess.run, extra_args=(), environ=None):
    if not os.path.isfile(executable):
        raise BuildError("Smoke-test executable was not produced: %s" % executable)
    with tempfile.TemporaryDirectory(prefix="lightstream-self-test-") as report_dir:
        report_path = os.path.join(report_dir, "report.json")
        command = ([executable] + list(extra_args) +
                   ["--self-test", "--self-test-json",
                    "--self-test-output", report_path])
        _run_checked(run, command, "Packaged application self-test",
                     capture_output=True, text=True, timeout=SMOKE_TIMEOUT_SECONDS,
                     env=environ)
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError) as exc:
            raise BuildError("Packaged application self-test did not write valid JSON: %s"
                             % exc)
        if not isinstance(report, dict) or report.get("ok") is not True:
            raise BuildError("Packaged application self-test report did not pass.")
        if report.get("app") != APP_NAME:
            raise BuildError("Packaged application self-test reported the wrong app identity.")
        return report


def _require_tool(which, name, environment=None, variable=None):
    configured = environment.get(variable) if environment is not None and variable else None
    path = configured or which(name)
    if not path:
        raise BuildError("%s is required for this release format." % name)
    return path


def _build_pyinstaller(target, variant, entry, temp_dir, run, version,
                       architecture, version_file=None):
    dist = os.path.join(temp_dir, "dist-" + variant)
    work = os.path.join(temp_dir, "work-" + variant)
    command = pyinstaller_command(target, entry, dist, work, variant=variant,
                                  version_file=version_file, architecture=architecture)
    _run_checked(run, command, "PyInstaller %s build" % variant)
    if target == "windows":
        return (os.path.join(dist, win.EXE_NAME) if variant == "portable" else
                os.path.join(dist, APP_NAME))
    if target == "macos":
        return os.path.join(dist, APP_NAME + ".app")
    return (os.path.join(dist, APP_NAME) if variant == "archive" else
            os.path.join(dist, APP_NAME))


def _windows_sign(path, run, which, environ):
    certificate = environ.get("LIGHTSTREAM_WINDOWS_CERTIFICATE")
    if not certificate:
        return
    if not os.path.isfile(certificate):
        raise BuildError("Configured Windows signing certificate file does not exist.")
    signtool = _require_tool(which, "signtool", environ, "LIGHTSTREAM_SIGNTOOL")
    password = environ["LIGHTSTREAM_WINDOWS_CERTIFICATE_PASSWORD"]
    _run_checked(run, [signtool, "sign", "/fd", "SHA256", "/td", "SHA256",
                       "/tr", "http://timestamp.digicert.com", "/f", certificate,
                       "/p", password, path], "Windows code signing",
                 capture_output=True, text=True)
    _run_checked(run, [signtool, "verify", "/pa", path], "Windows signature verification",
                 capture_output=True, text=True)


def _macos_sign_app(app, run, which, environ):
    identity = environ.get("LIGHTSTREAM_MACOS_APP_IDENTITY")
    if not identity:
        return
    codesign = _require_tool(which, "codesign")
    _run_checked(run, [codesign, "--force", "--deep", "--options", "runtime",
                       "--timestamp", "--sign", identity, app], "macOS app signing",
                 capture_output=True, text=True)
    _run_checked(run, [codesign, "--verify", "--deep", "--strict", app],
                 "macOS app signature verification", capture_output=True, text=True)


def _macos_notarize(path, run, which, environ, staple=True):
    profile = environ.get("LIGHTSTREAM_MACOS_NOTARY_PROFILE")
    if not profile:
        return
    xcrun = _require_tool(which, "xcrun")
    command = [xcrun, "notarytool", "submit", path,
               "--keychain-profile", profile]
    keychain = environ.get("LIGHTSTREAM_MACOS_KEYCHAIN")
    if keychain:
        command += ["--keychain", keychain]
    command.append("--wait")
    _run_checked(run, command,
                 "macOS notarization", capture_output=True, text=True,
                 timeout=900)
    if staple:
        _run_checked(run, [xcrun, "stapler", "staple", path],
                     "macOS notarization stapling", capture_output=True, text=True)


def _wix_id(prefix, relative):
    return prefix + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]


def _wix_guid(relative):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, BUNDLE_ID + "/" + relative)).upper()


def wix_source(app_dir, version, architecture, icon_path=WINDOWS_ICON):
    """Generate deterministic WiX v5 source for a per-user onedir install."""
    machine_label(architecture)
    directories = {"": "INSTALLFOLDER"}
    files = []
    for folder, dirnames, filenames in os.walk(app_dir):
        dirnames.sort()
        relative_dir = os.path.relpath(folder, app_dir)
        relative_dir = "" if relative_dir == "." else relative_dir.replace(os.sep, "/")
        for dirname in dirnames:
            rel = "/".join(part for part in (relative_dir, dirname) if part)
            directories[rel] = _wix_id("dir", rel)
        for filename in sorted(filenames):
            full = os.path.join(folder, filename)
            rel = "/".join(part for part in (relative_dir, filename) if part)
            files.append((rel, full, directories[relative_dir]))

    children = {relative: [] for relative in directories}
    for relative in directories:
        if not relative:
            continue
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        children[parent].append(relative)

    def directory_xml(relative, indent):
        lines = []
        for child in sorted(children[relative]):
            name = child.rsplit("/", 1)[-1]
            lines.append('%s<Directory Id=%s Name=%s>' %
                         (indent, quoteattr(directories[child]), quoteattr(name)))
            lines += directory_xml(child, indent + "  ")
            lines.append("%s</Directory>" % indent)
        return lines

    directory_lines = directory_xml("", "          ")
    component_lines = []
    feature_lines = []
    for relative, source, directory in files:
        component = _wix_id("cmp", relative)
        file_id = _wix_id("fil", relative)
        component_lines.append("    <Component Id=%s Directory=%s Guid=%s>" %
                               (quoteattr(component), quoteattr(directory),
                                quoteattr(_wix_guid(relative))))
        if relative.lower() == "lightstream.exe":
            component_lines.append("      <File Id=%s Source=%s KeyPath=\"yes\">" %
                                   (quoteattr(file_id), quoteattr(source)))
            component_lines.append("        <Shortcut Id=\"StartMenuShortcut\" "
                                   "Directory=\"ApplicationProgramsFolder\" "
                                   "Name=\"LightStream\" Description=\"Lightweight desktop broadcaster\" "
                                   "WorkingDirectory=\"INSTALLFOLDER\" Advertise=\"yes\" />")
            component_lines.append("      </File>")
            component_lines.append("      <RemoveFolder Id=\"RemoveStartMenuFolder\" "
                                   "Directory=\"ApplicationProgramsFolder\" On=\"uninstall\" />")
        else:
            component_lines.append("      <File Id=%s Source=%s KeyPath=\"yes\" />" %
                                   (quoteattr(file_id), quoteattr(source)))
        component_lines.append("    </Component>")
        feature_lines.append("      <ComponentRef Id=%s />" % quoteattr(component))

    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">',
        '  <Package Name="LightStream" Manufacturer="%s" Language="1033" '
        'Version="%s" UpgradeCode="%s" Scope="perUser" Compressed="yes" '
        'InstallerVersion="500">' % (PUBLISHER, version, WIX_UPGRADE_CODE),
        '    <MajorUpgrade DowngradeErrorMessage="A newer LightStream version is already installed." />',
        '    <MediaTemplate EmbedCab="yes" />',
        '    <Icon Id="LightStreamIcon" SourceFile=%s />' % quoteattr(icon_path),
        '    <Property Id="ARPPRODUCTICON" Value="LightStreamIcon" />',
        '    <Feature Id="Complete" Title="LightStream" Level="1">',
        *feature_lines,
        '    </Feature>',
        '  </Package>',
        '  <Fragment>',
        '    <StandardDirectory Id="LocalAppDataFolder">',
        '      <Directory Id="ProgramsDirectory" Name="Programs">',
        '        <Directory Id="INSTALLFOLDER" Name="LightStream">',
        *directory_lines,
        '        </Directory>',
        '      </Directory>',
        '    </StandardDirectory>',
        '    <StandardDirectory Id="ProgramMenuFolder">',
        '      <Directory Id="ApplicationProgramsFolder" Name="LightStream" />',
        '    </StandardDirectory>',
        '  </Fragment>',
        '  <Fragment>',
        *component_lines,
        '  </Fragment>',
        '</Wix>',
        '',
    ])


def wix_command(source, output, architecture, wix="wix"):
    arch = {"x86_64": "x64", "arm64": "arm64"}[machine_label(architecture)]
    return [wix, "build", "-arch", arch, "-o", output, source]


def _update_macos_plist(app, version, architecture):
    path = os.path.join(app, "Contents", "Info.plist")
    if not os.path.isfile(path):
        raise BuildError("PyInstaller app is missing Contents/Info.plist.")
    with open(path, "rb") as handle:
        data = plistlib.load(handle)
    data.update({
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSApplicationCategoryType": "public.app-category.video",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LightStreamBuildArchitecture": machine_label(architecture),
    })
    with open(path, "wb") as handle:
        plistlib.dump(data, handle, sort_keys=True)


def desktop_entry():
    return """[Desktop Entry]
Type=Application
Version=1.0
Name=LightStream
GenericName=Livestream Broadcaster
Comment=Lightweight desktop broadcaster powered by an external FFmpeg
Exec=lightstream-gui
TryExec=lightstream-gui
Icon=%s
Terminal=false
Categories=AudioVideo;Recorder;
Keywords=stream;broadcast;record;ffmpeg;
StartupNotify=true
StartupWMClass=LightStream
""" % BUNDLE_ID


def appstream_metadata(version):
    return """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>%(id)s</id>
  <name>LightStream</name>
  <summary>Lightweight desktop livestream broadcaster</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <launchable type="desktop-id">%(desktop)s</launchable>
  <url type="homepage">%(homepage)s</url>
  <description><p>Broadcast a desktop through an external FFmpeg installation without an embedded browser.</p></description>
  <releases><release version="%(version)s" /></releases>
  <categories><category>AudioVideo</category><category>Recorder</category></categories>
</component>
""" % {"id": BUNDLE_ID, "desktop": LINUX_DESKTOP_NAME,
       "homepage": HOMEPAGE, "version": version}


def _linux_arch(architecture, package):
    architecture = machine_label(architecture)
    if package == "deb":
        return {"x86_64": "amd64", "arm64": "arm64"}[architecture]
    return {"x86_64": "x86_64", "arm64": "aarch64"}[architecture]


def debian_control(version, architecture, installed_size_kib):
    return """Package: lightstream
Version: %(version)s
Section: video
Priority: optional
Architecture: %(architecture)s
Maintainer: LightStream contributors <michaelinzo@users.noreply.github.com>
Installed-Size: %(size)d
Depends: libc6 (>= 2.35), libx11-6, libxext6, libxrender1, libxft2, fontconfig
Recommends: ffmpeg
Homepage: %(homepage)s
Description: lightweight desktop livestream broadcaster
 LightStream launches the host FFmpeg to capture, encode, and publish a desktop stream.
 FFmpeg is deliberately not bundled.
""" % {"version": version, "architecture": _linux_arch(architecture, "deb"),
       "size": installed_size_kib, "homepage": HOMEPAGE}


def rpm_spec(version, architecture, source_root):
    arch = _linux_arch(architecture, "rpm")
    return """%%global debug_package %%{nil}
Name:           lightstream
Version:        %(version)s
Release:        1%%{?dist}
Summary:        Lightweight desktop livestream broadcaster
License:        MIT
URL:            %(homepage)s
BuildArch:      %(arch)s
Requires:       glibc >= 2.35
Requires:       libX11, libXext, libXrender, libXft, fontconfig
Recommends:     ffmpeg

%%description
LightStream launches the host FFmpeg to capture, encode, and publish a desktop stream.
FFmpeg is deliberately not bundled.

%%install
mkdir -p "%%{buildroot}"
cp -a %(source)s/. "%%{buildroot}/"

%%files
/opt/lightstream
/usr/bin/lightstream-gui
/usr/share/applications/%(desktop)s
/usr/share/icons/hicolor/scalable/apps/%(id)s.svg
/usr/share/metainfo/%(metainfo)s

%%changelog
* Thu Jan 01 2026 LightStream contributors <michaelinzo@users.noreply.github.com> - %(version)s-1
- LightStream %(version)s
""" % {"version": version, "homepage": HOMEPAGE, "arch": arch,
       "source": quoteattr(source_root), "desktop": LINUX_DESKTOP_NAME,
       "id": BUNDLE_ID, "metainfo": LINUX_METAINFO_NAME}


def _installed_size_kib(root):
    total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            total += os.path.getsize(os.path.join(folder, name))
    return max(1, (total + 1023) // 1024)


def _stage_linux_root(app_dir, stage, version):
    destination = os.path.join(stage, "opt", PACKAGE_NAME)
    shutil.copytree(app_dir, destination, symlinks=True)
    _write_text(os.path.join(stage, "usr", "bin", "lightstream-gui"),
                '#!/bin/sh\nexec /opt/lightstream/LightStream "$@"\n', 0o755)
    _write_text(os.path.join(stage, "usr", "share", "applications", LINUX_DESKTOP_NAME),
                desktop_entry(), 0o644)
    icon_target = os.path.join(stage, "usr", "share", "icons", "hicolor", "scalable",
                               "apps", BUNDLE_ID + ".svg")
    os.makedirs(os.path.dirname(icon_target), exist_ok=True)
    shutil.copy2(LINUX_ICON, icon_target)
    _write_text(os.path.join(stage, "usr", "share", "metainfo", LINUX_METAINFO_NAME),
                appstream_metadata(version), 0o644)
    return stage


def _build_windows(version, output, temp_dir, formats, architecture, signature,
                   run, which, environ):
    names = []
    version_file = os.path.join(temp_dir, "version-info.txt")
    _write_text(version_file, windows_version_info(version))
    entry = os.path.join(temp_dir, "lightstream_entry.py")
    _write_text(entry, win.ENTRY_SOURCE)
    epoch = _source_epoch(environ)

    if "portable" in formats:
        built = _build_pyinstaller("windows", "portable", entry, temp_dir, run,
                                   version, architecture, version_file)
        if not os.path.isfile(built):
            raise BuildError("LightStream.exe was not produced for the portable build.")
        _windows_sign(built, run, which, environ)
        stage = os.path.join(temp_dir, "portable-stage", "LightStreamPortable")
        win.create_layout(stage)
        staged_exe = os.path.join(stage, win.EXE_NAME)
        shutil.copy2(built, staged_exe)
        smoke_test(staged_exe, run=run, environ=environ)
        name = artifact_name(version, "windows", architecture, "portable", signature)
        _zip_tree(stage, os.path.join(output, name), epoch)
        names.append(name)

    if "msi" in formats:
        wix = _require_tool(which, "wix", environ, "LIGHTSTREAM_WIX")
        app_dir = _build_pyinstaller("windows", "installed", entry, temp_dir, run,
                                     version, architecture, version_file)
        executable = os.path.join(app_dir, win.EXE_NAME)
        if not os.path.isfile(executable):
            raise BuildError("The Windows onedir build did not produce LightStream.exe.")
        _windows_sign(executable, run, which, environ)
        smoke_test(executable, run=run, environ=environ)
        source = os.path.join(temp_dir, "LightStream.wxs")
        _write_text(source, wix_source(app_dir, version, architecture))
        name = artifact_name(version, "windows", architecture, "msi", signature)
        path = os.path.join(output, name)
        _run_checked(run, wix_command(source, path, architecture, wix), "WiX MSI build",
                     capture_output=True, text=True)
        if not os.path.isfile(path):
            raise BuildError("WiX completed but the MSI was not produced.")
        _windows_sign(path, run, which, environ)
        names.append(name)
    return names


def _build_macos(version, output, temp_dir, formats, architecture, signature,
                 run, which, environ):
    entry = os.path.join(temp_dir, "lightstream_entry.py")
    _write_text(entry, win.ENTRY_SOURCE)
    app = _build_pyinstaller("macos", "app", entry, temp_dir, run,
                             version, architecture)
    executable = os.path.join(app, "Contents", "MacOS", APP_NAME)
    if not os.path.isdir(app) or not os.path.isfile(executable):
        raise BuildError("PyInstaller did not produce a complete LightStream.app.")
    _update_macos_plist(app, version, architecture)
    _macos_sign_app(app, run, which, environ)
    smoke_test(executable, run=run, environ=environ)
    ditto = _require_tool(which, "ditto")

    if environ.get("LIGHTSTREAM_MACOS_NOTARY_PROFILE"):
        submission = os.path.join(temp_dir, "LightStream-notarization.zip")
        _run_checked(run, [ditto, "-c", "-k", "--keepParent", app, submission],
                     "macOS notarization ZIP creation")
        _macos_notarize(submission, run, which, environ, staple=False)
        xcrun = _require_tool(which, "xcrun")
        _run_checked(run, [xcrun, "stapler", "staple", app],
                     "macOS app ticket stapling", capture_output=True, text=True)

    names = []
    if "zip" in formats:
        name = artifact_name(version, "macos", architecture, "zip", signature)
        path = os.path.join(output, name)
        _run_checked(run, [ditto, "-c", "-k", "--keepParent", app, path],
                     "macOS app ZIP creation")
        if not os.path.isfile(path):
            raise BuildError("ditto completed but the macOS ZIP was not produced.")
        names.append(name)

    if "dmg" in formats:
        hdiutil = _require_tool(which, "hdiutil")
        stage = os.path.join(temp_dir, "dmg-stage")
        os.makedirs(stage)
        shutil.copytree(app, os.path.join(stage, APP_NAME + ".app"), symlinks=True)
        os.symlink("/Applications", os.path.join(stage, "Applications"))
        name = artifact_name(version, "macos", architecture, "dmg", signature)
        path = os.path.join(output, name)
        _run_checked(run, [hdiutil, "create", "-volname", APP_NAME, "-srcfolder", stage,
                           "-ov", "-format", "UDZO", path], "macOS DMG creation",
                     capture_output=True, text=True)
        if not os.path.isfile(path):
            raise BuildError("hdiutil completed but the DMG was not produced.")
        if environ.get("LIGHTSTREAM_MACOS_APP_IDENTITY"):
            codesign = _require_tool(which, "codesign")
            _run_checked(run, [codesign, "--force", "--timestamp", "--sign",
                               environ["LIGHTSTREAM_MACOS_APP_IDENTITY"], path],
                         "macOS DMG signing", capture_output=True, text=True)
        _macos_notarize(path, run, which, environ)
        _run_checked(run, [hdiutil, "verify", path], "macOS DMG verification",
                     capture_output=True, text=True)
        names.append(name)

    if "pkg" in formats:
        pkgbuild = _require_tool(which, "pkgbuild")
        pkgutil = _require_tool(which, "pkgutil")
        root = os.path.join(temp_dir, "pkg-root", "Applications")
        os.makedirs(root)
        shutil.copytree(app, os.path.join(root, APP_NAME + ".app"), symlinks=True)
        name = artifact_name(version, "macos", architecture, "pkg", signature)
        path = os.path.join(output, name)
        command = [pkgbuild, "--root", os.path.dirname(root), "--identifier", BUNDLE_ID,
                   "--version", version, "--install-location", "/", "--ownership",
                   "recommended"]
        identity = environ.get("LIGHTSTREAM_MACOS_INSTALLER_IDENTITY")
        if identity:
            command += ["--sign", identity]
        command.append(path)
        _run_checked(run, command, "macOS PKG creation", capture_output=True, text=True)
        if not os.path.isfile(path):
            raise BuildError("pkgbuild completed but the PKG was not produced.")
        _macos_notarize(path, run, which, environ)
        _run_checked(run, [pkgutil, "--payload-files", path], "macOS PKG payload check",
                     capture_output=True, text=True)
        names.append(name)
    return names


def _build_linux(version, output, temp_dir, formats, architecture, run, which, environ):
    entry = os.path.join(temp_dir, "lightstream_entry.py")
    _write_text(entry, win.ENTRY_SOURCE)
    names = []
    epoch = _source_epoch(environ)

    if "tar.gz" in formats:
        built = _build_pyinstaller("linux", "archive", entry, temp_dir, run,
                                   version, architecture)
        if not os.path.isfile(built):
            raise BuildError("PyInstaller did not produce the Linux executable.")
        os.chmod(built, 0o755)
        smoke_test(built, run=run, environ=environ)
        readme = os.path.join(temp_dir, "README.txt")
        _write_text(readme, LINUX_README)
        name = artifact_name(version, "linux", architecture, "tar.gz")
        _tar_files(((built, APP_NAME), (readme, "README.txt")),
                   os.path.join(output, name), epoch)
        names.append(name)

    package_formats = tuple(kind for kind in formats if kind != "tar.gz")
    if not package_formats:
        return names
    app_dir = _build_pyinstaller("linux", "installed", entry, temp_dir, run,
                                 version, architecture)
    executable = os.path.join(app_dir, APP_NAME)
    if not os.path.isfile(executable):
        raise BuildError("The Linux onedir build did not produce LightStream.")
    os.chmod(executable, 0o755)
    smoke_test(executable, run=run, environ=environ)
    root = _stage_linux_root(app_dir, os.path.join(temp_dir, "linux-root"), version)

    if "AppImage" in formats:
        tool = _require_tool(which, "appimagetool", environ, "LIGHTSTREAM_APPIMAGETOOL")
        appdir = os.path.join(temp_dir, "LightStream.AppDir")
        shutil.copytree(root, appdir, symlinks=True)
        _write_text(os.path.join(appdir, "AppRun"),
                    '#!/bin/sh\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                    'exec "$HERE/opt/lightstream/LightStream" "$@"\n', 0o755)
        shutil.copy2(os.path.join(root, "usr", "share", "applications", LINUX_DESKTOP_NAME),
                     os.path.join(appdir, LINUX_DESKTOP_NAME))
        shutil.copy2(LINUX_ICON, os.path.join(appdir, BUNDLE_ID + ".svg"))
        name = artifact_name(version, "linux", architecture, "AppImage")
        path = os.path.join(output, name)
        tool_env = dict(environ, ARCH={"x86_64": "x86_64", "arm64": "aarch64"}[architecture],
                        VERSION=version, SOURCE_DATE_EPOCH=str(epoch),
                        APPIMAGE_EXTRACT_AND_RUN="1")
        _run_checked(run, [tool, appdir, path], "AppImage build",
                     capture_output=True, text=True, env=tool_env)
        if not os.path.isfile(path):
            raise BuildError("appimagetool completed but the AppImage was not produced.")
        os.chmod(path, 0o755)
        smoke_test(path, run=run, extra_args=("--appimage-extract-and-run",),
                   environ=tool_env)
        names.append(name)

    if "deb" in formats:
        dpkg = _require_tool(which, "dpkg-deb")
        stage = os.path.join(temp_dir, "deb-root")
        shutil.copytree(root, stage, symlinks=True)
        control = debian_control(version, architecture, _installed_size_kib(stage))
        _write_text(os.path.join(stage, "DEBIAN", "control"), control, 0o644)
        name = artifact_name(version, "linux", architecture, "deb")
        path = os.path.join(output, name)
        _run_checked(run, [dpkg, "--root-owner-group", "--build", stage, path],
                     "Debian package build", capture_output=True, text=True,
                     env=dict(environ, SOURCE_DATE_EPOCH=str(epoch)))
        if not os.path.isfile(path):
            raise BuildError("dpkg-deb completed but the deb was not produced.")
        _run_checked(run, [dpkg, "--info", path], "Debian package metadata check",
                     capture_output=True, text=True)
        names.append(name)

    if "rpm" in formats:
        rpmbuild = _require_tool(which, "rpmbuild")
        rpm = _require_tool(which, "rpm")
        top = os.path.join(temp_dir, "rpmbuild")
        for folder in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
            os.makedirs(os.path.join(top, folder))
        spec = os.path.join(top, "SPECS", "lightstream.spec")
        _write_text(spec, rpm_spec(version, architecture, root))
        _run_checked(run, [rpmbuild, "-bb", "--define", "_topdir " + top,
                           "--target", _linux_arch(architecture, "rpm"), spec],
                     "RPM package build", capture_output=True, text=True,
                     env=dict(environ, SOURCE_DATE_EPOCH=str(epoch)))
        candidates = []
        for folder, _dirs, files in os.walk(os.path.join(top, "RPMS")):
            candidates += [os.path.join(folder, name) for name in files
                           if name.endswith(".rpm") and not name.endswith(".src.rpm")]
        if len(candidates) != 1:
            raise BuildError("rpmbuild produced %d binary RPM files; expected one." % len(candidates))
        name = artifact_name(version, "linux", architecture, "rpm")
        path = os.path.join(output, name)
        shutil.copy2(candidates[0], path)
        _run_checked(run, [rpm, "-qpl", path], "RPM package payload check",
                     capture_output=True, text=True)
        names.append(name)
    return names


def plan(target, version, output, machine=None, formats=None):
    architecture = machine_label(machine)
    formats = resolve_formats(target, formats)
    steps = ["platform: " + target, "architecture: " + architecture,
             "version: " + version, "formats: " + ", ".join(formats),
             "PyInstaller executable self-test: --self-test --self-test-json --self-test-output <temporary-file>"]
    for kind in formats:
        steps.append("artifact: " + os.path.join(
            output, artifact_name(version, target, architecture, kind)))
    steps += ["checksums: " + os.path.join(output, CHECKSUM_FILE),
              "FFmpeg: external dependency, not bundled",
              "signing: optional secrets; default artifacts are unsigned"]
    return steps


def build(target, version, output, run=subprocess.run, find_module=None,
          which=shutil.which, machine=None, formats=None, environ=None):
    """Build and package one native platform. Return artifact basenames."""
    if find_module is None:
        import importlib.util
        find_module = importlib.util.find_spec
    if find_module("PyInstaller") is None:
        raise BuildError("PyInstaller is not installed. Run: pip install pyinstaller")
    if target not in PLATFORMS:
        raise BuildError("Unsupported release target %r." % target)
    architecture = machine_label(machine)
    formats = resolve_formats(target, formats)
    environ = dict(os.environ if environ is None else environ)
    signature = _signature_label(target, environ)
    for icon in (WINDOWS_ICON, MACOS_ICON, LINUX_ICON):
        if not os.path.isfile(icon):
            raise BuildError("Required icon is missing: %s" % icon)
    os.makedirs(output, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        if target == "windows":
            names = _build_windows(version, output, temp_dir, formats, architecture,
                                   signature, run, which, environ)
        elif target == "macos":
            names = _build_macos(version, output, temp_dir, formats, architecture,
                                 signature, run, which, environ)
        else:
            names = _build_linux(version, output, temp_dir, formats, architecture,
                                 run, which, environ)
    write_checksums(output, names)
    return names + [CHECKSUM_FILE]


def _parse_formats(value):
    return tuple(part.strip() for part in value.split(",") if part.strip())


def main(argv=None, run=subprocess.run, find_module=None, which=shutil.which,
         host_name=None, machine=None, environ=None):
    parser = argparse.ArgumentParser(description="Build native LightStream release downloads.")
    parser.add_argument("--platform", choices=PLATFORMS, default=None,
                        help="default: the platform this runs on")
    parser.add_argument("--architecture", choices=ARCHITECTURES,
                        help="require this runner architecture")
    parser.add_argument("--formats", type=_parse_formats,
                        help="comma-separated subset for this platform")
    parser.add_argument("--version", default=None, help="default: lightstream.__version__")
    parser.add_argument("--output", default=os.path.join(ROOT, DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = parser.parse_args(argv)
    try:
        target = args.platform or detect_platform(host_name)
        version = args.version or read_version()
        actual_arch = machine_label(machine)
        if args.architecture and args.architecture != actual_arch:
            raise BuildError("Runner architecture is %s, expected %s."
                             % (actual_arch, args.architecture))
        formats = resolve_formats(target, args.formats)
        if args.dry_run:
            print("\n".join(plan(target, version, args.output, actual_arch, formats)))
            return 0
        require_native_target(target, host_name)
        names = build(target, version, args.output, run=run, find_module=find_module,
                      which=which, machine=actual_arch, formats=formats, environ=environ)
    except BuildError as error:
        print("error: " + str(error), file=sys.stderr)
        return 1
    print("Wrote %s %s artifacts to %s: %s"
          % (target, actual_arch, args.output, ", ".join(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
