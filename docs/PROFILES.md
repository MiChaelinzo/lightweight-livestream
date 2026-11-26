# One-click profiles

Use with `lightstream start --profile NAME` or pick the name in the GUI "Performance profile" list.
All numbers below are design choices. Nothing here is a measured CPU saving.
Status: argv VERIFIED by golden files and a unit test, behavior on real PCs UNVERIFIED.

| Profile | Picture | Bitrate | Threads | Needs |
|---|---|---|---|---|
| `potato_pc` | 854x480 at 30 fps (the `light` preset) | 1000 kbps | at most 2, one core left free | any PC |
| `office_laptop` | 1600x900 at 30 fps | 3500 kbps | all but one core | a CPU with 4 or more threads |
| `budget_gaming` | 1920x1080 at 60 fps | 6000 kbps | all but one core | a hardware encoder (NVENC on a GTX 1650 class card) |

`lightstream optimize` and the setup wizard print the profile `perf_profiles.recommend_profile(cpu_count, ram_mb, gpu_name, hardware_profile)` picks for this PC. It is a pure function, first match wins:

1. At most 2048 MB of RAM: `potato_2000`. At most 2 CPU threads or at most 4096 MB: `potato_pc`.
2. Intel HD graphics: `potato_pc` (the hardware profile caps presets at 480p anyway).
3. NVIDIA GPU, 4 or more threads, 8192 MB or more: `budget_gaming`.
4. 4 or more threads and 8192 MB or more without NVENC: `office_laptop`.
5. Anything else, or unknown values: `balanced`.

## Why these numbers

- **No 40 fps for `office_laptop`.** A 60 Hz display shows 40 fps frames for uneven times (2 then 1 refresh), which looks like judder, and platforms expect 30 or 60 fps. So the profile uses 900p at 30 fps.
- **Not 720p at 600 to 1000 kbps for `potato_pc`.** This is design reasoning, not a measurement. x264 at 720p needs more bits per pixel than 1000 kbps gives in motion, so the picture blocks up, and a smaller frame costs the encoder less than a thinner bitrate. 480p30 at 1000 kbps (the `light` preset) spends the same bits on a quarter fewer pixels. If you want 720p, use `balanced` (2500 kbps).
- **`budget_gaming` needs a hardware encoder.** 1080p60 with x264 on the CPU will not keep up on the PCs this targets, so the profile says so in its description and `recommend_profile` only returns it for NVIDIA. 6000 kbps equals the Twitch cap in `bandwidth.PLATFORM_VIDEO_CAP_KBPS`. On Facebook (4000 kbps cap) the bitrate is lowered to the cap.
- `office_laptop` at 3500 kbps fits under every platform cap (the smallest is Facebook at 4000).
- The automatic upload recommendation (`bandwidth.recommend`) never picks `office_laptop` or `budget_gaming` (`presets.PROFILE_ONLY_PRESETS`), so a fast connection alone does not select 1080p60.

# Portable mode audit

`portable.flag` next to the app (or `LIGHTSTREAM_PORTABLE=1`) moves state out of the per-user config folder. `tests/test_portable.py` (`PortableStatePathTests`) writes one file of every kind through the real functions, with HOME, XDG_CONFIG_HOME and APPDATA pointed at an empty folder, and checks that folder stays empty. VERIFIED on Linux. No path escaped, so no code changed. Windows paths use the same `os.path` code but were not run.

| State | Portable location |
|---|---|
| config.json, ffmpeg choice, gui.json (profiles and saved settings), ui.json, scenes.json | `data/` |
| session history, performance snapshot (`reports/`), crash reports (`crashes/`), support bundle, plugins folder | `data/` |
| shareable one-scene collections | `scenes/` (next to `data/`, by design) |
| recordings (CLI default) and highlight clips (next to the recording) | `recordings/` |
| recordings from the GUI | `data/recordings/` (the GUI and CLI defaults differ; both stay in the app folder) |

Stream key: LightStream never writes it in plain text, portable or not.
- Windows: the DPAPI blob `stream-key.dpapi` is saved in `data/`. It is encrypted for the current Windows user, so copying the stick to another PC or account leaves a file that cannot be decrypted there (the key must be typed again). It does not protect against malware running as the same user.
- macOS and Linux: the key goes to the system keychain or `secret-tool`, which live outside the app folder, so they do not travel with the stick and are not removed when the folder is deleted. If the tool is missing, saving is refused and nothing is written.
- Saving needs an explicit opt-in. Backends are UNVERIFIED on real systems; the control flow is covered by tests with fakes.
