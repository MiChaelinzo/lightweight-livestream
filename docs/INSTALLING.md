# Installing LightStream

LightStream has two products with different capabilities:

1. **Desktop broadcaster:** Windows, macOS, or Linux. It captures a desktop and starts the host's FFmpeg process.
2. **Installable web companion:** Android, iPhone, iPad, and desktop browsers. It provides the guide, preset calculator, and overlay shell. It does not capture a phone screen or broadcast video.

The v0.18 release workflow is still **UNVERIFIED** because GitHub Actions is billing-locked for this repository. The package plans and metadata are unit tested. A real Linux x86_64 tarball was built, extracted, and passed its frozen `--self-test` in the development sandbox. Windows, macOS, MSI, DMG, PKG, AppImage, deb, and rpm installation remain UNVERIFIED until the workflow can run and the files can be installed on their target systems.

## Pick the right download

`<version>` is the release number. `signed` replaces `unsigned` only when the maintainer configured the optional signing secrets.

| System | v0.18 workflow download | What it does | Current verification |
|---|---|---|---|
| Windows 10/11 x86_64 | `LightStream-<version>-windows-x86_64-portable-unsigned.zip` | Portable folder. Settings stay beside the app because `portable.flag` is present | Build plan and layout VERIFIED by tests; real exe UNVERIFIED |
| Windows 10/11 x86_64 | `LightStream-<version>-windows-x86_64-unsigned.msi` | Per-user install under `%LOCALAPPDATA%\Programs\LightStream`, Start Menu shortcut, settings under `%APPDATA%\lightstream` | WiX source and command plan VERIFIED; real MSI install UNVERIFIED |
| macOS 11+ Apple Silicon | `LightStream-<version>-macos-arm64-unsigned.zip` | `LightStream.app`; drag it to Applications | Plan VERIFIED; real app UNVERIFIED |
| macOS 11+ Apple Silicon | `.dmg` with the same prefix | DMG containing the app and an Applications link | Plan VERIFIED; real DMG UNVERIFIED |
| macOS 11+ Apple Silicon | `.pkg` with the same prefix | Installs `LightStream.app` to `/Applications` | Plan VERIFIED; real PKG install UNVERIFIED |
| Linux x86_64 | `LightStream-<version>-linux-x86_64.tar.gz` | Portable executable without portable mode; settings use XDG paths | v0.18 tarball built, extracted, and self-tested on this Linux sandbox; desktop capture UNVERIFIED |
| Linux x86_64 | `.AppImage`, `.deb`, or `.rpm` with the same prefix | Desktop-integrated installed builds | Metadata and command plans VERIFIED; real packages and installs UNVERIFIED |
| Android, iPhone, iPad | Web companion from `/install/` | Home-screen guide, calculator, and overlay shell | Manifest, metadata, CSP, and offline rules VERIFIED by Node tests; real browser install UNVERIFIED |
| Android/iOS broadcaster | None | Not supported by the desktop codebase | Separate native product on the roadmap |

All native downloads are architecture-specific. Do not install the `arm64` macOS build on an Intel Mac. The v0.18 workflow does not produce an Intel macOS or Windows ARM build.

## Verify a download

Download `SHA256SUMS.txt` from the same release. In the folder that holds the downloads:

```sh
# Linux
sha256sum -c SHA256SUMS.txt

# macOS
shasum -a 256 -c SHA256SUMS.txt
```

On Windows PowerShell, compare the file's value with the matching line:

```powershell
Get-FileHash .\LightStream-0.18.0-windows-x86_64-unsigned.msi -Algorithm SHA256
```

A checksum detects a damaged or replaced download. An unsigned checksum file is not a substitute for code signing. Release assets say `unsigned` in the filename unless optional signing ran.

## FFmpeg is required and not bundled

No LightStream artifact contains FFmpeg. This avoids silently redistributing a large third-party binary and its license obligations.

On first run, LightStream searches beside the app, a previously chosen path, and the operating system `PATH`. If it finds nothing, the window links to FFmpeg downloads and offers **Choose ffmpeg file...**. A missing FFmpeg is a setup warning, not an application-integrity failure.

- **Windows:** download a build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), unzip it, and select `bin\ffmpeg.exe`. A portable user can instead place it in `LightStreamPortable\ffmpeg\`.
- **macOS:** install with `brew install ffmpeg`, restart LightStream, or choose the binary. The app also checks `/opt/homebrew/bin` and `/usr/local/bin`.
- **Debian/Ubuntu:** `sudo apt install ffmpeg`.
- **Fedora:** `sudo dnf install ffmpeg`.

The deb and rpm declare FFmpeg as a recommended external package. The AppImage and tarball use the host installation. None embeds it.

## Windows

### Portable ZIP

1. Download and unzip the portable ZIP to a folder you can write to.
2. Double-click `LightStream.exe`.
3. Keep `portable.flag`. Removing it changes where LightStream looks for settings.
4. Choose FFmpeg when prompted, or place `ffmpeg.exe` in the included `ffmpeg` folder.

Portable settings live in `data\`; scene collection files live in `scenes\`; default recordings live in `recordings\`. Copy the complete folder to move or back it up.

To update, stop LightStream, download the newer ZIP, and copy your `data`, `scenes`, and `recordings` folders into the new extracted folder. To uninstall, delete the folder. The portable build creates no Start Menu entry and no uninstaller.

### MSI

The MSI uses a PyInstaller on-directory build. It does not unpack a one-file executable on every launch.

1. Download the MSI.
2. Open it and complete the per-user installer.
3. Start **LightStream** from the Start Menu.
4. Choose FFmpeg on first run if needed.

The app installs under `%LOCALAPPDATA%\Programs\LightStream`. It does not contain `portable.flag`, so settings stay under `%APPDATA%\lightstream`.

To uninstall, open **Settings > Apps > Installed apps**, choose LightStream, and select **Uninstall**. User settings remain under `%APPDATA%\lightstream` so an upgrade does not erase them. Delete that folder only if you also want to erase settings, reports, and saved FFmpeg location.

### Unsigned SmartScreen warning

For an `unsigned` file, Windows may show **Windows protected your PC**. Confirm that the checksum matches, choose **More info**, then **Run anyway**. Do not bypass the warning for a file from any other source.

## macOS

The v0.18 workflow target is Apple Silicon (`arm64`) and macOS 11 or newer.

### App ZIP

1. Unzip the download.
2. Move `LightStream.app` to `/Applications`.
3. Open it and choose FFmpeg if prompted.

### DMG

1. Open the DMG.
2. Drag `LightStream.app` onto the **Applications** link in the DMG window.
3. Eject the DMG, then open LightStream from Applications.

### PKG

Open the PKG and follow the installer. It places `LightStream.app` in `/Applications`.

To uninstall any macOS format, quit LightStream and move `/Applications/LightStream.app` to the Trash. For a PKG, you may then forget its receipt with `sudo pkgutil --forget io.github.michaelinzo.lightstream`. Settings remain in `~/.config/lightstream`; remove that folder only if you want to erase them.

### Unsigned Gatekeeper warning

For an `unsigned` app, verify the checksum first. In Finder, Control-click `LightStream.app`, choose **Open**, then choose **Open** again. The command-line alternative is:

```sh
xattr -d com.apple.quarantine /Applications/LightStream.app
```

Do not remove quarantine from an unverified download. Signed and notarized artifacts use `signed-notarized` in their filename only when the optional secret-based release steps completed.

## Linux

The release workflow uses Ubuntu 22.04 x86_64 as its conservative build image. Its glibc baseline is 2.35. A distribution with older glibc may not start these binaries. The local tarball check in this sandbox used glibc 2.34, but the published workflow artifact must be judged by its own runner baseline.

Installed builds put the application under `/opt/lightstream`, a launcher at `/usr/bin/lightstream-gui`, a desktop entry under `/usr/share/applications`, and an SVG icon under the hicolor icon tree. Settings follow `$XDG_CONFIG_HOME/lightstream`, or `~/.config/lightstream` when `XDG_CONFIG_HOME` is unset. No Linux installed package contains `portable.flag`.

### tar.gz

```sh
tar xzf LightStream-0.18.0-linux-x86_64.tar.gz
./LightStream
```

Delete the extracted files to uninstall. Settings remain in the XDG config folder unless you remove them separately.

### AppImage

```sh
chmod +x LightStream-0.18.0-linux-x86_64.AppImage
./LightStream-0.18.0-linux-x86_64.AppImage
```

Delete the AppImage to uninstall. Desktop-menu integration is not added automatically.

### Debian or Ubuntu

```sh
sudo apt install ./LightStream-0.18.0-linux-x86_64.deb
lightstream-gui
sudo apt remove lightstream
```

### Fedora or another rpm-based distribution

```sh
sudo dnf install ./LightStream-0.18.0-linux-x86_64.rpm
lightstream-gui
sudo dnf remove lightstream
```

### Why Snap and Flatpak remain roadmap items

Current Linux capture uses FFmpeg `x11grab` and direct device access, and LightStream launches the host FFmpeg process. Strict Snap or Flatpak confinement cannot honestly support that design without more work. A confined build needs PipeWire plus the desktop ScreenCast portal for user-approved capture, and a tested policy for host FFmpeg, cameras, microphones, GPU devices, and encoder drivers. No manifest is shipped until those paths work end to end.

## Install the mobile web companion

### Android Chrome

1. Open the hosted LightStream `/install/` page in Chrome over HTTPS.
2. Open Chrome's menu.
3. Choose **Install app** or **Add to Home screen**.
4. Confirm **Install**.

### iPhone or iPad Safari

1. Open the hosted `/install/` page in Safari.
2. Tap **Share**.
3. Choose **Add to Home Screen**.
4. Tap **Add**.

To remove the web companion, remove its home-screen icon like any other installed web app. Browser-managed cached data can also be cleared in the browser's site-data settings.

The companion can cache its static guide, install help, calculator, and overlay shell. Live Twitch data still needs the network. The desktop phone-remote URL is separate and exists only while the desktop app is streaming with that opt-in feature enabled.

**The companion is not an APK, AAB, or IPA broadcaster.** Android screen capture needs a native MediaProjection foreground service and MediaCodec pipeline. iOS needs a ReplayKit Broadcast Upload Extension and VideoToolbox pipeline. Both require native lifecycle, permission, network, signing, and store work. See [ROADMAP.md](ROADMAP.md#native-mobile-broadcaster-roadmap-separate-product).

## Run the application self-test

The self-test does not open a GUI or start a stream. It checks frozen imports, Tcl/Tk availability, app and portable roots, writable state storage, and FFmpeg discovery. A missing FFmpeg produces a warning and exit code 0. Broken app imports or unwritable state produce a nonzero exit.

Windows release executables use the GUI subsystem, so they have no console stream. Write the structured report to a file, then read it:

```powershell
$report = Join-Path $env:TEMP "lightstream-self-test.json"

# Windows portable
.\LightStream.exe --self-test --self-test-json --self-test-output $report

# Or, for the Windows MSI install
& "$env:LOCALAPPDATA\Programs\LightStream\LightStream.exe" `
  --self-test --self-test-json --self-test-output $report

$exitCode = $LASTEXITCODE
Get-Content $report
$exitCode
```

`--self-test` without an output file still returns the integrity exit code in a windowed build, but it has nowhere to display the report.

```sh
# macOS
/Applications/LightStream.app/Contents/MacOS/LightStream --self-test

# Linux tar or installed on-directory payload
./LightStream --self-test

# Source install
lightstream gui --self-test
```

Add `--self-test-json` for one machine-readable JSON object. `--self-test-output FILE` writes either the plain or JSON form to a file and is the useful transport for a windowed Windows executable.

## Troubleshooting

| Symptom | Check |
|---|---|
| App does not start | Run `--self-test`; on a Windows release executable also use `--self-test-json --self-test-output FILE`. Verify that you downloaded the correct architecture |
| FFmpeg warning | Install FFmpeg or use **Choose ffmpeg file...**. Missing FFmpeg does not mean the app package is corrupt |
| Linux says `GLIBC_x.y not found` | The distribution is older than the build baseline. Use the Python source install or rebuild on that older supported distribution |
| Linux window does not open | Run from an X11 desktop session. Current capture is X11, not Wayland portal capture |
| Windows or macOS blocks the app | Verify `SHA256SUMS.txt`, then follow the unsigned warning steps above |
| Portable settings appear missing | Confirm that `portable.flag` stayed beside `LightStream.exe` and that the folder is writable |
| Installed settings remain after uninstall | This is intentional. Remove the documented config folder only if you want to erase user data |
| Phone icon opens a guide but cannot go live | Expected. The installed web companion is not a broadcaster |
