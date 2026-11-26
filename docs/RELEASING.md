# Releasing LightStream

## Current verification status

The release workflow (`.github/workflows/release.yml`) is **UNVERIFIED** because GitHub Actions is billing-locked for this repository and the workflow has not run. The v0.18 Python tests verify artifact naming, architecture checks, generated WiX source, macOS command plans, Linux package metadata, signing/notarization command plans, checksums, and failure handling with fake native tools.

A real v0.18 Linux x86_64 tarball was built locally with PyInstaller 6.11.1, extracted, and its frozen `--self-test --self-test-json` returned 0. The test confirmed imports, Tcl/Tk, app root, writable XDG state, and reported missing FFmpeg as a warning. Desktop capture and GUI display were not exercised. The Windows exe/MSI, macOS app/ZIP/DMG/PKG, AppImage, deb, rpm, signing, notarization, and the workflow itself remain **UNVERIFIED**.

Fix the repository's Actions billing lock before attempting a release. Do not change an UNVERIFIED label until the corresponding artifact has been built and installed or run on its target platform.

## Release builder versions and runners

The workflow deliberately records platform and architecture and fails on a mismatch:

| Target | Runner | Architecture | Tooling |
|---|---|---|---|
| Windows | `windows-latest` | x86_64 | PyInstaller 6.11.1, WiX 5.0.2 |
| macOS | `macos-15` | arm64 | PyInstaller 6.11.1, `ditto`, `hdiutil`, `pkgbuild`, `pkgutil` |
| Linux | `ubuntu-22.04` | x86_64 | PyInstaller 6.11.1, `appimagetool`, `dpkg-deb`, `rpmbuild`, `rpm` |

Ubuntu 22.04 sets a glibc 2.35 baseline. Older distributions may not run the result. The AppImage uses the same PyInstaller payload, so AppImage does not erase that glibc constraint.

The workflow downloads the official x86_64 `appimagetool` continuous asset and requires SHA-256 `e8c1169c4af66c3184d7ee110713d4be04befe671fa358e2c1591ee840553b03`. If upstream replaces the continuous asset, the job fails instead of running changed bytes. Review the new [official release asset](https://github.com/AppImage/appimagetool/releases) and update both URL or checksum deliberately.

## Prepare version changes in a pull request

1. Update `src/lightstream/__init__.py` and `pyproject.toml` to the same version.
2. Add the release section to `CHANGELOG.md`.
3. Update artifact examples in `README.md`, `docs/INSTALLING.md`, and this file.
4. Run the full validation set:

```sh
HOME=/tmp/ls-home \
XDG_CONFIG_HOME=/tmp/ls-home/.config \
LIGHTSTREAM_TEST_FFMPEG=/path/to/ffmpeg \
python3 -m unittest discover -s tests
node --test "web/test/*.test.js"
python3 -m compileall -q src
python3 tools/export_presets.py --check
python3 tools/generate_icons.py --check
python3 tools/check_version.py
python3 tools/page_weight.py
PYTHONPATH=src python3 -m lightstream gui --self-test --self-test-json
```

5. Merge the reviewed pull request. Do not tag a feature branch, an unmerged commit, or a local commit that differs from the merged commit.

## Sync main and verify the exact release commit

Start from a clean tree. Replace `<MERGED_MAIN_SHA>` with the merge commit shown for the reviewed release pull request.

```sh
git status --short
git switch main
git fetch origin
git pull --ff-only origin main
git status --short

release_sha=$(git rev-parse HEAD)
test "$release_sha" = "<MERGED_MAIN_SHA>"
test "$(git rev-parse origin/main)" = "$release_sha"
python3 tools/check_version.py --expect 0.18.0
```

Both `git status --short` commands must print nothing. If either SHA comparison fails, stop. Do not merge, reset, or tag until you understand why local main, origin/main, and the reviewed merge commit differ.

Run the validation set again on this exact main commit. Record `release_sha` with the test results.

## Tag only the verified merged commit

Create the tag explicitly at `release_sha`, inspect it, and push only the tag:

```sh
git tag -a v0.18.0 "$release_sha" -m "LightStream 0.18.0"
test "$(git rev-parse 'v0.18.0^{commit}')" = "$release_sha"
git show --no-patch --decorate v0.18.0
git push origin refs/tags/v0.18.0
```

Do not use `git push origin main v0.18.0` as a release shortcut. Main was already synchronized and verified. The release action should push only `refs/tags/v0.18.0`.

The workflow checks all of the following before building a tag:

- Checkout has full history (`fetch-depth: 0`).
- The tag without `v` equals both `lightstream.__version__` and `[project].version`.
- The tag resolves to the checked-out commit.
- That commit is reachable from `origin/main`.

## What the workflow runs

Every native matrix job runs:

```sh
python -m unittest discover -s tests
node --test "web/test/*.test.js"
python -m compileall -q src
python tools/export_presets.py --check
python tools/generate_icons.py --check
PYTHONPATH=src python -m lightstream gui --self-test --self-test-json
python tools/build_release.py --platform TARGET --architecture ARCH
```

`tools/build_release.py` then executes every freshly built native app with `--self-test --self-test-json` before packaging it. AppImage is also invoked with `--appimage-extract-and-run`. Package containers are checked with their native inspection tools where practical. A successful mocked unit test does not verify a real installer.

A manual **Run workflow** builds and uploads workflow artifacts but does not publish a GitHub release. A matching `v*.*.*` tag runs the same builds, requires exactly one of every expected format, writes one combined `SHA256SUMS.txt`, and publishes or replaces the release assets.

## Expected v0.18 artifact set

`unsigned` changes to `signed` or `signed-notarized` only when optional signing completes.

| Platform | Artifact | Installation model | Status before first successful workflow |
|---|---|---|---|
| Windows x86_64 | `LightStream-0.18.0-windows-x86_64-portable-unsigned.zip` | One-file exe plus `portable.flag` and portable folders | UNVERIFIED |
| Windows x86_64 | `LightStream-0.18.0-windows-x86_64-unsigned.msi` | Per-user on-directory install, Start Menu shortcut | UNVERIFIED |
| macOS arm64 | `LightStream-0.18.0-macos-arm64-unsigned.zip` | `LightStream.app` | UNVERIFIED |
| macOS arm64 | `LightStream-0.18.0-macos-arm64-unsigned.dmg` | App plus Applications link | UNVERIFIED |
| macOS arm64 | `LightStream-0.18.0-macos-arm64-unsigned.pkg` | Installs app to `/Applications` | UNVERIFIED |
| Linux x86_64 | `LightStream-0.18.0-linux-x86_64.tar.gz` | One executable plus README | Locally built and self-tested; workflow artifact UNVERIFIED |
| Linux x86_64 | `LightStream-0.18.0-linux-x86_64.AppImage` | AppImage using host FFmpeg | UNVERIFIED |
| Linux x86_64 | `LightStream-0.18.0-linux-x86_64.deb` | `/opt/lightstream`, launcher and desktop metadata | UNVERIFIED |
| Linux x86_64 | `LightStream-0.18.0-linux-x86_64.rpm` | `/opt/lightstream`, launcher and desktop metadata | UNVERIFIED |
| All | `SHA256SUMS.txt` | Combined release checksums | UNVERIFIED workflow output |

The publish job fails if any required artifact is absent or duplicated. It does not treat an optional format as a substitute for a missing platform.

## Local builds

Install the pinned builder in an isolated environment:

```sh
python3 -m venv .venv-release
. .venv-release/bin/activate
python -m pip install pyinstaller==6.11.1
python tools/build_release.py --dry-run
python tools/build_release.py --formats tar.gz
```

Use the native operating system. PyInstaller cannot cross-compile. The full default build also needs the native package tools listed above. `--formats` accepts a comma-separated subset for local work, such as `portable`, `zip,dmg`, or `tar.gz,deb` depending on the platform.

Output goes to `dist/release/`, which is gitignored. Never commit an exe, MSI, app bundle, DMG, PKG, AppImage, deb, rpm, wheel, signing certificate, or generated release archive.

## Why MSI uses WiX

The Windows installer is an MSI because that is the requested native format. WiX 5.0.2 is pinned, and the source is generated from the PyInstaller on-directory tree with stable component IDs and GUIDs. The package is per-user under Local AppData, adds a Start Menu shortcut, has a stable upgrade code, does not include `portable.flag`, and leaves config under APPDATA. Unit tests parse the generated source and assert the command plan. A real MSI build, upgrade, repair, and uninstall are still UNVERIFIED.

## Optional signing and notarization

Unsigned builds are the default and say `unsigned` in their names. The workflow must remain successful with no signing secrets.

### Windows secrets

- `WINDOWS_CERTIFICATE_PFX_BASE64`
- `WINDOWS_CERTIFICATE_PASSWORD`

The workflow decodes the PFX only into the runner's temporary directory, finds the installed Windows SDK `signtool`, signs and verifies the exe and MSI, then deletes the temporary file. Never add a PFX, password, certificate export, or signing command containing a literal password to the repository.

### macOS secrets

- `MACOS_CERTIFICATE_P12_BASE64`
- `MACOS_CERTIFICATE_PASSWORD`
- `MACOS_APP_IDENTITY`
- `MACOS_INSTALLER_IDENTITY`
- Optional notarization trio: `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, `MACOS_NOTARY_PASSWORD`

The workflow creates a temporary keychain, imports the certificate, signs the app and package, optionally stores a temporary notary profile, submits and staples the relevant artifacts, then deletes the keychain and P12. Partial secret configuration fails instead of silently publishing a misleading filename.

These paths are command-plan tested only. Real signing and notarization are UNVERIFIED.

## FFmpeg policy

No release artifact contains FFmpeg. The app keeps its first-run download link and file picker. Linux packages declare FFmpeg as a recommended external dependency; the portable formats use the host installation or a user-supplied copy.

This policy avoids committing or silently redistributing third-party FFmpeg binaries. Any future separate “with FFmpeg” download requires an explicit license and source-offer review first.

## Formats deliberately not shipped

- **APK, AAB, IPA:** the desktop broadcaster cannot become a phone broadcaster by repackaging tkinter and an FFmpeg subprocess. Native Android needs MediaProjection, a foreground service, and MediaCodec. Native iOS needs ReplayKit Broadcast Upload Extension, VideoToolbox, and Apple signing. They are a separate product roadmap.
- **Snap and Flatpak:** current Linux capture uses X11 `x11grab`, direct devices, and host FFmpeg. Confinement needs a tested PipeWire/ScreenCast portal capture path plus host FFmpeg, camera, microphone, GPU, and driver access. No unverified manifest is shipped.

## Source notes

Runner architecture labels follow the [GitHub runner images table](https://github.com/actions/runner-images#available-images). AppImage tooling comes from the [official appimagetool releases](https://github.com/AppImage/appimagetool/releases). WiX authoring follows the [WiX Toolset documentation](https://wixtoolset.org/docs/). Content from these sources was rephrased for compliance with licensing restrictions.
