"""Build a release download: python tools/build_release.py [--platform P] [--version V] [--dry-run]

Produces files in dist/release/ for the current platform (PyInstaller cannot cross-compile):
  windows: LightStream-<ver>-windows-portable.zip (LightStream.exe, portable.flag, folders)
  macos:   LightStream-<ver>-macos.zip (LightStream.app) and a .dmg when hdiutil exists
  linux:   LightStream-<ver>-linux-x86_64.tar.gz (one executable plus a README note)
plus SHA256SUMS.txt. FFmpeg is never bundled. PyInstaller must be installed
(pip install pyinstaller). No .spec file is used: all options are passed on the command line.
"""

import argparse
import hashlib
import os
import platform as platform_module
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from tools import build_windows_portable as win  # noqa: E402

DEFAULT_OUTPUT = os.path.join("dist", "release")
APP_NAME = "LightStream"
BUNDLE_ID = "io.github.michaelinzo.lightstream"
CHECKSUM_FILE = "SHA256SUMS.txt"
PLATFORMS = ("windows", "macos", "linux")
LINUX_README = ("LightStream (Linux)\n\nRun ./LightStream. Run it from a desktop session: "
                "everything is bundled except FFmpeg.\n"
                "Install FFmpeg with your package manager (for example: sudo apt install ffmpeg)\n"
                "or choose its file in the first-run window.\n")
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
    return "linux"


def machine_label(machine=None):
    machine = (machine or platform_module.machine()).lower()
    return "x86_64" if machine in ("x86_64", "amd64") else machine


def archive_name(version, target, machine=None):
    if target == "windows":
        return "LightStream-%s-windows-portable.zip" % version
    if target == "macos":
        return "LightStream-%s-macos.zip" % version
    return "LightStream-%s-linux-%s.tar.gz" % (version, machine_label(machine))


def pyinstaller_command(target, entry, dist_dir, work_dir, python=sys.executable):
    cmd = [python, "-m", "PyInstaller", "--noconfirm", "--name", APP_NAME,
           "--paths", os.path.join(ROOT, "src"), "--distpath", dist_dir,
           "--workpath", work_dir, "--specpath", work_dir]
    if target == "macos":
        cmd += ["--windowed", "--onedir", "--osx-bundle-identifier", BUNDLE_ID]
    elif target == "windows":
        cmd += ["--onefile", "--windowed"]
    else:
        cmd += ["--onefile"]
    return cmd + [entry]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(output, names):
    """Write SHA256SUMS.txt in 'sha256sum' format, sorted by name."""
    lines = ["%s  %s\n" % (sha256_file(os.path.join(output, n)), n) for n in sorted(names)]
    with open(os.path.join(output, CHECKSUM_FILE), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    return lines


def _zip_tree(source, archive):
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        base = os.path.dirname(source)
        for folder, dirs, files in os.walk(source):
            dirs.sort()
            if not files and not dirs:
                zf.write(folder, os.path.relpath(folder, base) + "/")
            for name in sorted(files):
                full = os.path.join(folder, name)
                zf.write(full, os.path.relpath(full, base))


def plan(target, version, output, machine=None):
    """Human-readable steps, used by --dry-run."""
    steps = ["platform: " + target, "version: " + version,
             "PyInstaller: " + " ".join(pyinstaller_command(
                 target, "<entry.py>", "<tmp>/dist", "<tmp>/work", python="python"))]
    steps.append("archive: " + os.path.join(output, archive_name(version, target, machine)))
    if target == "macos":
        steps.append("optional: " + os.path.join(output, "LightStream-%s-macos.dmg" % version)
                     + " (hdiutil, if available)")
    steps += ["checksums: " + os.path.join(output, CHECKSUM_FILE), "FFmpeg: not bundled"]
    return steps


def build(target, version, output, run=subprocess.run, find_module=None,
          which=shutil.which, machine=None):
    """Build and package. Returns the list of artifact file names written to output."""
    if find_module is None:
        import importlib.util
        find_module = importlib.util.find_spec
    if find_module("PyInstaller") is None:
        raise BuildError("PyInstaller is not installed. Run: pip install pyinstaller")
    os.makedirs(output, exist_ok=True)
    names = []
    with tempfile.TemporaryDirectory() as tmp:
        entry = os.path.join(tmp, "lightstream_entry.py")
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write(win.ENTRY_SOURCE)
        dist_dir = os.path.join(tmp, "dist")
        result = run(pyinstaller_command(target, entry, dist_dir, os.path.join(tmp, "work")))
        if result.returncode != 0:
            raise BuildError("PyInstaller failed with exit code %d." % result.returncode)
        archive = archive_name(version, target, machine)
        archive_path = os.path.join(output, archive)
        if target == "windows":
            built = os.path.join(dist_dir, win.EXE_NAME)
            if not os.path.isfile(built):
                raise BuildError("%s was not produced. A Windows exe must be built on Windows."
                                 % win.EXE_NAME)
            stage = os.path.join(tmp, "stage", "LightStreamPortable")
            win.create_layout(stage)
            shutil.copy2(built, os.path.join(stage, win.EXE_NAME))
            _zip_tree(stage, archive_path)
        elif target == "macos":
            app = os.path.join(dist_dir, APP_NAME + ".app")
            if not os.path.isdir(app):
                raise BuildError("%s.app was not produced. A macOS app must be built on a Mac."
                                 % APP_NAME)
            # ditto keeps symlinks and permissions that zipfile would lose.
            if which("ditto"):
                ditto = run(["ditto", "-c", "-k", "--keepParent", app, archive_path])
                if ditto.returncode != 0:
                    raise BuildError("ditto failed with exit code %d." % ditto.returncode)
            else:
                _zip_tree(app, archive_path)
            if which("hdiutil"):
                dmg = "LightStream-%s-macos.dmg" % version
                made = run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", app,
                            "-ov", "-format", "UDZO", os.path.join(output, dmg)])
                if made.returncode == 0 and os.path.isfile(os.path.join(output, dmg)):
                    names.append(dmg)
        else:
            built = os.path.join(dist_dir, APP_NAME)
            if not os.path.isfile(built):
                raise BuildError("%s was not produced by PyInstaller." % APP_NAME)
            stage = os.path.join(tmp, "stage")
            os.makedirs(stage)
            shutil.copy2(built, os.path.join(stage, APP_NAME))
            os.chmod(os.path.join(stage, APP_NAME), 0o755)
            with open(os.path.join(stage, "README.txt"), "w", encoding="utf-8") as fh:
                fh.write(LINUX_README)
            with tarfile.open(archive_path, "w:gz") as tf:
                tf.add(os.path.join(stage, APP_NAME), arcname=APP_NAME)
                tf.add(os.path.join(stage, "README.txt"), arcname="README.txt")
        names.append(archive)
    write_checksums(output, names)
    return names + [CHECKSUM_FILE]


def main(argv=None, run=subprocess.run, find_module=None):
    parser = argparse.ArgumentParser(description="Build a LightStream release download.")
    parser.add_argument("--platform", choices=PLATFORMS, default=None,
                        help="default: the platform this runs on")
    parser.add_argument("--version", default=None, help="default: lightstream.__version__")
    parser.add_argument("--output", default=os.path.join(ROOT, DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = parser.parse_args(argv)
    target = args.platform or detect_platform()
    version = args.version or read_version()
    if args.dry_run:
        print("\n".join(plan(target, version, args.output)))
        return 0
    try:
        names = build(target, version, args.output, run=run, find_module=find_module)
    except BuildError as err:
        print("error: " + str(err), file=sys.stderr)
        return 1
    print("Wrote to %s: %s" % (args.output, ", ".join(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
