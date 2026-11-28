# v0.18 map: everywhere release, installable companion, honest native limits

Status words: **Existing** (already in 0.17), **Extended** (existing code grows), **New** (new module or package path), **Roadmap** (not built). Verification labels: **VERIFIED** (executed with recorded evidence), **PARTIALLY VERIFIED** (a lower layer ran, but the claimed end-to-end behavior did not), **UNVERIFIED** (not run), **NOT SUPPORTED** (deliberately absent). Competitor numbers remain UNKNOWN.

## Mission boundary

v0.18 makes the existing Python/tkinter desktop broadcaster easier to install. It does not pretend that renaming or wrapping the desktop executable creates an Android or iOS broadcaster.

The deliverables are:

1. A headless integrity path shared by source and frozen GUI entry points.
2. Native desktop package plans with explicit platform and architecture.
3. A provenance-gated release workflow with optional secret-based signing.
4. An installable mobile companion PWA with a strict capability label.
5. A separate, documented native-mobile roadmap.

No Electron, embedded Chromium, Capacitor, Cordova, npm dependency, bundled FFmpeg, mobile package, or unverified Snap/Flatpak manifest was added.

## Baseline before v0.18

Parent commit: `a9f60b7` on `feat/v0.17-live-studio`.

| Suite | v0.17 result | Status |
|---|---|---|
| Python unittest | 943 tests, 4 skipped with `LIGHTSTREAM_TEST_FFMPEG` set | VERIFIED in v0.17 |
| Node test | 44 passed | VERIFIED in v0.17 |
| Web weight | 56,421 text bytes, 20,950 gzip bytes, 84,984 image bytes | VERIFIED by the v0.18 baseline script against the parent tree |

## Architecture map

| Area | State | Primary code | Boundary and evidence |
|---|---|---|---|
| Version invariant | New | `tools/check_version.py`, `tests/test_version.py` | Reads `[project].version` without adding a Python 3.8 TOML dependency and requires it to equal `lightstream.__version__`; tag jobs also pass the tag version |
| Headless self-test | New | `src/lightstream/selftest.py`, `gui.main`, CLI `gui --self-test` | Runs before `tk.Tk()`. Checks frozen imports, Tcl/Tk without a display, app root, portable root containment, writable config directory, and FFmpeg discovery. Missing or invalid FFmpeg is a warning; a broken app check exits nonzero. `--self-test-output FILE` works when a Windows windowed executable has no stdout/stderr console |
| Frozen entry status | Extended | `tools/build_windows_portable.py` | Generated entry uses `raise SystemExit(main())`, so failed integrity checks reach the process exit status |
| Release builder | Extended | `tools/build_release.py` | One native target per host; rejects unknown platform/architecture and cross-compilation in the CLI; supports format subsets locally; every executable writes a JSON self-test report to a temporary file before packaging, which also works for Windows GUI-subsystem binaries |
| Reproducible identity assets | New | `tools/generate_icons.py`, `assets/icons/`, `web/icons/` | One stdlib generator emits SVG, ICO, ICNS and PNG. Tests check exact bytes, dimensions, headers, web weight, and `--check` reproducibility |
| Windows portable | Extended | release builder plus portable layout helper | One-file, windowed PyInstaller exe; signed before staging when secrets exist; portable flag and folders; deterministic ZIP metadata; FFmpeg note but no FFmpeg binary |
| Windows MSI | New | generated WiX v5 source | Separate on-directory PyInstaller payload under Local AppData, per-user scope, stable upgrade code, product metadata/icon, Start Menu shortcut, no `portable.flag`, config under APPDATA. Source and command plan VERIFIED; real MSI UNVERIFIED |
| macOS app metadata | Extended | PyInstaller app plus deterministic `Info.plist` update | Stable bundle ID, version, category, minimum OS, explicit arm64 record, ICNS icon. Optional application signing occurs after metadata changes |
| macOS ZIP/DMG/PKG | New/Extended | `ditto`, `hdiutil`, `pkgbuild`, `pkgutil` plans | ZIP preserves app structure; DMG staging has an Applications symlink and must verify; PKG root installs to `/Applications`; required tools or outputs fail the build. Real artifacts UNVERIFIED |
| Linux tar | Extended | one-file PyInstaller archive | Deterministic gzip/tar timestamps and ownership, README, no FFmpeg. A real v0.18 tarball was built and self-tested locally |
| Linux installed payload | New | on-directory PyInstaller tree plus metadata generators | `/opt/lightstream`, `/usr/bin/lightstream-gui`, XDG config, desktop entry, AppStream metadata and scalable SVG icon; no portable flag |
| AppImage/deb/rpm | New | appimagetool, dpkg-deb and rpmbuild plans | AppImage self-test uses extract-and-run; deb/rpm recommend external FFmpeg; package inspection commands are mandatory. Metadata/plans VERIFIED; real packages UNVERIFIED |
| Release provenance | Extended | `.github/workflows/release.yml` | Full checkout, both version sources checked, tag resolves to checkout, tag commit must be reachable from `origin/main`, runner architecture checked, exact nine-artifact gate before publish |
| Optional signing | New | workflow secret setup plus release-builder commands | Windows PFX and macOS P12/keychain/notary values come only from GitHub secrets and temporary runner paths. Partial configuration fails. Unsigned is the default and is named. Real signing UNVERIFIED |
| Installable companion | New | `manifest.webmanifest`, `/install/`, shared service-worker registration, PWA icons | Companion name and description, same-origin scope, any/maskable icons, Apple metadata, Android/iOS steps, shortcuts, screenshots, no npm dependencies |
| Offline shell | Extended | `sw-logic.js`, `sw.js` | Manifest, install page, icons, showcase and companion shell are precached. The cache suffix hashes every cached text and binary byte. Static logic VERIFIED; real offline browser launch UNVERIFIED |
| Native Android broadcaster | Roadmap, separate product | documentation only | Requires MediaProjection consent, foreground service, MediaCodec, native audio/network path, permissions, lifecycle, device testing and APK/AAB signing |
| Native iOS broadcaster | Roadmap, separate product | documentation only | Requires host app plus ReplayKit Broadcast Upload Extension, VideoToolbox, extension-safe networking/state, entitlements, provisioning and IPA/App Store signing |
| Snap/Flatpak | Roadmap | documentation only | Current X11 `x11grab`, host FFmpeg and direct device/GPU model does not fit strict confinement. PipeWire/ScreenCast portal and device/host-tool access must work first |

## Build topology

```text
source version + pyproject version
              |
              v
        version invariant
              |
              v
native runner + pinned PyInstaller ----> frozen app ----> --self-test
              |                                |
              |                                +--> native archive
              +--> installer metadata -------->+--> installer/container
                                               |
                                               +--> SHA256SUMS
```

Windows builds two frozen payloads because the portable ZIP needs one-file behavior while the MSI must avoid one-file extraction on every launch. macOS and Linux installed formats share an on-directory payload on their own runner. No payload contains FFmpeg.

## Release artifact matrix

| Platform | Workflow artifact | Local execution in this round | Status |
|---|---|---|---|
| Windows x86_64 | portable ZIP | fake PyInstaller/native tools only | UNVERIFIED native artifact |
| Windows x86_64 | per-user MSI | WiX XML parsed and command plan tested | UNVERIFIED build/install |
| macOS arm64 | app ZIP | fake native tools only | UNVERIFIED native artifact |
| macOS arm64 | DMG with Applications link | staging symlink and command plan tested | UNVERIFIED build/mount/install |
| macOS arm64 | PKG to `/Applications` | payload/sign/notary plans tested | UNVERIFIED build/install |
| Linux x86_64 | tar.gz | real PyInstaller 6.11.1 build, extract, frozen self-test | VERIFIED package integrity on this sandbox; GUI/capture UNVERIFIED |
| Linux x86_64 | AppImage | plan, metadata, output and smoke-failure handling with fakes | UNVERIFIED real artifact |
| Linux x86_64 | deb | control metadata and command plan tested | UNVERIFIED real artifact/install |
| Linux x86_64 | rpm | spec metadata and command plan tested | UNVERIFIED real artifact/install |
| Mobile browsers | companion PWA | manifest/CSP/cache/install wording tests | VERIFIED static logic; real installation UNVERIFIED |
| Android APK/AAB broadcaster | none | none | NOT SUPPORTED in v0.18 |
| iOS IPA broadcaster | none | none | NOT SUPPORTED in v0.18 |

## Decisions and tradeoffs

### Keep two version sources, enforce one invariant

Setuptools dynamic version metadata would remove duplication but changes packaging behavior. v0.18 keeps the low-risk static metadata and fails tests/workflow on drift.

### MSI with WiX instead of a different installer

The requested Windows format is MSI. WiX 5.0.2 is pinned, generated source uses stable IDs/GUIDs, and the package is per-user. This keeps the native format without committing generated installer source or binaries. A different installer was not needed.

### Separate portable and installed Windows payloads

The portable ZIP keeps the current one-file convenience. MSI uses on-directory output so every launch does not extract a one-file bundle. This costs one extra PyInstaller build on the Windows runner but gives the requested installed behavior.

### Require DMG and PKG instead of silently skipping

A release matrix that advertises a format must fail when the native tool or output is missing. Optional behavior is reserved for signing/notarization because unsigned artifacts are intentionally supported and clearly named.

### Conservative but explicit Linux baseline

The workflow uses Ubuntu 22.04 x86_64 and documents glibc 2.35. AppImage still carries the PyInstaller payload's libc requirement. Calling it universally portable would be inaccurate.

### PWA companion instead of a fake mobile app

The static site can honestly install as a guide/calculator/overlay shell with no heavy framework. It cannot use the desktop FFmpeg subprocess architecture to capture and broadcast a phone. Native broadcaster work remains a separate roadmap with its real platform APIs named.

## Security and repository policy

- No FFmpeg, installer binary, package output, browser bundle, SDK, `node_modules`, signing material, or secret is tracked.
- Repository tests inspect tracked paths for forbidden release/signing artifacts and FFmpeg binaries.
- Signing values are referenced by secret names only. Workflow scripts never dump the environment.
- The PWA keeps the existing strict CSP. Twitch connections remain scoped to `/companion`; install and showcase pages stay same-origin.
- The service worker caches no stream key. Companion credentials stay in the URL fragment and are not part of shell files.
- Tag provenance checks version and ancestry before any release build.

## Local native evidence

Environment: Linux x86_64, kernel 6.1, Python 3.11.15, PyInstaller 6.11.1, glibc 2.34, no display or GPU. The build command selected only `tar.gz` because `appimagetool`, `dpkg-deb`, and `rpmbuild` were unavailable locally.

The generated tar was extracted into a temporary directory and the frozen binary returned exit 0. Its JSON report recorded:

- 8 required LightStream modules imported: pass.
- Tcl 8.6.10 and Tk API 8.6 without opening a display: pass.
- Extracted app root: pass.
- Writable XDG state under `/tmp/ls-home/.config/lightstream`: pass.
- FFmpeg discovery: warning, deliberately not an integrity failure.
- Frozen version: 0.18.0.

This verifies package integrity on one Linux host. It does not verify X11 capture, audio, FFmpeg launch, GUI rendering, installation, or compatibility with another distribution.

## Final local validation

Commands used the requested environment:

```sh
HOME=/tmp/ls-home \
XDG_CONFIG_HOME=/tmp/ls-home/.config \
LIGHTSTREAM_TEST_FFMPEG=/projects/sandbox/.cache-ffmpeg/ffmpeg-7.0.2-amd64-static/ffmpeg \
python3 -m unittest discover -s tests
```

| Check | Result | Status |
|---|---|---|
| Python unittest | 985 tests, OK, 4 skipped | VERIFIED |
| Node test | 54 passed, 0 failed, 0 skipped | VERIFIED |
| `python3 -m compileall -q src` | clean | VERIFIED |
| `python3 tools/export_presets.py --check` | up to date | VERIFIED |
| `python3 tools/check_version.py` | runtime and pyproject both 0.18.0 | VERIFIED |
| `python3 tools/generate_icons.py --check` | exact generated bytes up to date | VERIFIED |
| Source `gui --self-test --self-test-json` | exit 0; FFmpeg warning only | VERIFIED |
| Real Linux tar frozen self-test | exit 0 after extraction | VERIFIED on this sandbox |
| `python3 tools/page_weight.py` | 63,955 text bytes; 23,837 gzip; 146,617 image bytes | VERIFIED |
| Release workflow YAML | parsed locally; static workflow tests pass | PARTIALLY VERIFIED; never executed |

The four Python skips all require a display: two `GuiWindowDisplayTests`, the real-window idle-budget test (also needs `/proc`), and the banner paint snapshot test. The suite emitted pre-existing `ResourceWarning` messages for some test subprocesses and unclosed test file handles but completed successfully. They are not converted into packaging verification.

## Remaining limitations and next steps

1. Remove the GitHub Actions billing lock and run a manual workflow before tagging.
2. Inspect every matrix job's packaged self-test and checksum output.
3. Install, upgrade, repair, and uninstall the MSI on Windows x86_64. Verify Start Menu identity and APPDATA state.
4. Open the macOS app, mount the DMG, install/uninstall the PKG, and test both unsigned and optional signed/notarized paths on Apple Silicon.
5. Execute and install AppImage, deb, and rpm on representative supported distributions. Confirm desktop menu, icon, XDG state, host FFmpeg discovery, and glibc error wording.
6. Install the companion from Android Chrome and iOS Safari, then test offline launch and removal. Do not upgrade this to broadcaster status without native capture work.
7. Keep Snap/Flatpak deferred until PipeWire portal capture and confined device/FFmpeg access are implemented and exercised.
8. Do not publish an APK, AAB, or IPA from this repository unless a reviewed native product supplies the architecture documented in the roadmap.
