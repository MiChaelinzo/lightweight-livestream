# Releasing LightStream

Status: the release workflow (`.github/workflows/release.yml`) is UNVERIFIED. GitHub Actions is billing-locked for this repository, so it has never run. The Linux build script was run locally (VERIFIED). The Windows zip, the macOS zip/dmg and the workflow YAML logic are UNVERIFIED (the YAML parses, nothing more).

## Cut a release

1. Fix the GitHub Actions billing lock (Settings > Billing). Nothing below runs until this is done.
2. Bump the version in `src/lightstream/__init__.py` and `pyproject.toml`. Artifact names come from `lightstream.__version__`. Add a `CHANGELOG.md` entry.
3. Run the tests: `python3 -m unittest discover -s tests`.
4. Commit, then tag and push: `git tag v0.15.0 && git push origin main v0.15.0`.
5. The `Release` workflow builds on Windows, macOS and Linux, then publishes a GitHub release with generated notes and a combined `SHA256SUMS.txt`. You can also start it by hand with "Run workflow"; that builds and uploads artifacts but does not publish.

The workflow fails early if the tag (without the `v`) differs from `lightstream.__version__`, and fails the publish job if fewer than three artifacts arrive. Re-running the publish job on an existing release uploads the files again with `--clobber` instead of failing.

To build locally on one platform: `pip install pyinstaller` then `python tools/build_release.py` (`--dry-run` prints the plan). Output goes to `dist/release/`. PyInstaller cannot cross-compile, so each OS must build its own artifact.

## Artifacts

| Platform | File | Notes |
|---|---|---|
| Windows | `LightStream-<ver>-windows-portable.zip` | Unzip, double-click `LightStream.exe`. Portable folder layout. |
| macOS | `LightStream-<ver>-macos.zip` (and `.dmg` when `hdiutil` exists) | Contains `LightStream.app`. Built on `macos-latest` (Apple Silicon, arm64), so Intel Macs are not supported by this artifact. |
| Linux | `LightStream-<ver>-linux-x86_64.tar.gz` | One executable plus a short README. Built on `ubuntu-latest`, so it needs that image's glibc or newer; older distributions may not start it (UNVERIFIED on other distributions). |
| All | `SHA256SUMS.txt` | Verify with `sha256sum -c` (Linux) or `shasum -a 256 -c` (macOS). |

## FFmpeg is not bundled

Decision: no artifact contains FFmpeg. On first run, when FFmpeg is missing, the app shows a dialog with a download link and a "Choose ffmpeg file..." button. The chosen path is saved in the config.

Reasons: it follows the project rule of not shipping third-party binaries; FFmpeg builds are GPL or LGPL, and redistributing them brings source and license obligations; and it would add tens of MB to every download.

Trade-off: a beginner has one extra step. An optional separate "with FFmpeg" artifact is deferred. If it is added later it must be a separate download, link the exact upstream source and license, and be reviewed for GPL/LGPL compliance first.

## Unsigned apps: first-run warnings

Artifacts are not signed. Users will see warnings.

- Windows SmartScreen: click "More info", then "Run anyway".
- macOS Gatekeeper: right-click the app, choose Open, then Open again. Or run `xattr -d com.apple.quarantine LightStream.app`.

Signing is the maintainer's choice. If you sign, keep certificates and passwords in GitHub Actions secrets, never in the repository, and add the signing step to the workflow yourself. The workflow must keep working without any secrets.

## Formats not shipped

- `.apk` (Android) and `.ipa` (iOS): LightStream captures a desktop screen, uses tkinter and starts a desktop FFmpeg subprocess. A phone version is a different product. iOS also needs Apple developer signing and its sandbox forbids this process model.
- `.msi`, `.deb`, `.rpm`, AppImage: more packaging work for little gain over a portable zip or tar.gz. Revisit if users ask.
