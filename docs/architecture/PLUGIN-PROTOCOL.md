# Plugin protocol (version 1, implemented as a library and CLI)

Status: **implemented v1 as a library and a CLI; not wired into the stream runner.** `src/lightstream/plugins.py` implements the manifest rules, process model, transport, limits and permissions below, and `lightstream plugins list|check|run-demo` exposes them. The example plugin is `examples/plugins/hello`. Roadmap rank 31 in [TOP-100.md](../audit/TOP-100.md).

| Part | Status |
|---|---|
| Manifest validation, minimal env, no shell, working directory | VERIFIED by tests with real `python3` subprocess plugins |
| Handshake (5 s), 16 KiB lines, `v` check, permissions, rate limit (20 msg/s, extra dropped and counted), 10 violations disable, one restart after 5 s, `shutdown` then terminate then kill, bounded write queue (64), stderr tail 4 KiB with key redaction | VERIFIED by the same tests |
| Event whitelist: only the fields in the Events table, wrong types refused, any value containing a known key or URL refused | VERIFIED (unit tests; a seeded `LIGHTSTREAM_KEY` is absent from the plugin environment) |
| Wiring into `start` (sending `stream_started`, `stream_stopped`, `insight`, `health`), `overlay_text` and `notify` effects, GUI "Disable plugins" button, `--no-plugins` flag, saved kill switch | Roadmap, not implemented |
| Windows, macOS | UNVERIFIED (only Linux was run) |

Implementation notes: plugins are enabled only by name in the `plugins` list of `config.json` (default none). `hello` and `shutdown` are always sent; other events only if listed in the manifest. A plugin that misses the handshake is disabled for the session, with no restart. Accepted actions are returned to the caller (`PluginProcess.drain_actions`); the host decides what to do with them. Subprocess isolation is not an OS sandbox: the plugin runs with the user's privileges, and in-process Python cannot be sandboxed at all. Limits are design choices, not measured.

## Goals and non-goals

- A plugin is a separate OS process. The host never imports plugin code, because in-process Python cannot be sandboxed.
- The host stays stdlib only and the plugin can be written in any language that reads and writes lines.
- Non-goals for v1: a GUI for plugins, a plugin store, network permissions beyond a yes or no, access to FFmpeg arguments, and any access to the stream key or ingest URL.

## Process model

1. Plugins live in a `plugins/<name>/` folder inside the user config directory. Nothing is loaded unless the user enabled that plugin by name (default: none enabled).
2. The host reads `plugin.json` (see Manifest), checks it, then starts the command with `subprocess.Popen(argv_list, stdin=PIPE, stdout=PIPE, stderr=PIPE)`. No shell, no string commands.
3. The child gets a minimal environment: `PATH` and `LIGHTSTREAM_PLUGIN=1`. The host environment is not inherited, so `LIGHTSTREAM_KEY` and similar variables are not visible to it.
4. The working directory is the plugin folder.
5. The host sends events on the child's stdin and reads actions from its stdout. stderr is captured, truncated to the last 4 KiB and shown in the log (after the host's key redaction).

This spec does not claim OS level isolation. A plugin runs with the user's own privileges, so enabling one is the same trust decision as running any program. The permission manifest limits what the host does for the plugin, not what the plugin process can do on its own.

## Transport

- UTF-8, one JSON object per line, ended by `\n`. Maximum line length 16 KiB; longer lines are dropped and counted as a violation.
- Every message has `"v": 1`. Unknown `v` is a violation. Unknown extra fields are ignored.
- Host to plugin: `{"v":1,"event":"<name>", ...}`. Plugin to host: `{"v":1,"action":"<name>", ...}`.
- The first host message is `{"v":1,"event":"hello","host":"lightstream","host_version":"...","permissions":["..."]}`. The plugin must answer `{"v":1,"action":"ready"}` within 5 seconds, or it is stopped.

## Events (host to plugin)

Sent only if the manifest lists the event in `events`. Unlisted events are never sent.

| Event | Fields | When |
|---|---|---|
| `hello` | `host`, `host_version`, `permissions` | Once after start |
| `stream_started` | `platform` (name only, for example `twitch`) | ffmpeg launched |
| `stream_stopped` | `reason` | ffmpeg ended |
| `status` | `state` (`live`, `reconnecting`, `failover`, `stopped`) | State change |
| `insight` | `text`, `confidence` | Optimizer produced an explained insight |
| `health` | `fps`, `bitrate_kbps`, `dropped` | At most once per 5 seconds |
| `shutdown` | none | Host is stopping the plugin; exit within 3 seconds |

Never present in any event: the stream key, the ingest URL, file paths, config contents.

## Actions (plugin to host)

Each needs the matching permission. An action without permission is dropped and counted as a violation.

| Action | Fields | Permission | Effect |
|---|---|---|---|
| `ready` | none | none | Handshake done |
| `log` | `text` (max 500 chars) | `log` | Line in the host log, prefixed with the plugin name |
| `overlay_text` | `text` (max 120 chars) | `overlay_text` | Text shown in the next overlay slot; applied at the next restart, never mid-stream |
| `notify` | `text` (max 200 chars) | `notify` | Message in the window status area |

The protocol has no action that changes bitrate, scenes, start or stop. Those stay user decisions.

## Manifest (`plugin.json`)

```json
{
  "v": 1,
  "name": "chat-goal",
  "version": "0.1.0",
  "command": ["python3", "main.py"],
  "events": ["stream_started", "health"],
  "permissions": ["log", "overlay_text"]
}
```

Rules the host enforces: `name` is `[a-z0-9-]{1,32}` and equals the folder name; `command` is a non-empty list of strings, and the first element is either a bare program name found on `PATH` or a relative path inside the plugin folder (no `..`, no absolute path); `events` and `permissions` contain only known names. A manifest that fails any rule is not started and the reason is shown.

## Limits and failure handling

| Limit | Value (design choice, not measured) |
|---|---|
| Handshake timeout | 5 s |
| Max line length | 16 KiB |
| Max messages from plugin | 20 per second; excess dropped |
| Max violations before disable | 10 |
| Crash or hang | one restart after 5 s, then disabled for the session |
| Memory | not limited by the host in v1 (stated gap) |

A plugin that does not read stdin must not block the host: writes to the child use a bounded queue (64 messages, oldest dropped) on a separate thread.

## Kill switch

- GUI: one button "Disable plugins" and the CLI flag `--no-plugins`. Either stops every plugin (send `shutdown`, wait 3 seconds, then `terminate`, then `kill`) and prevents loading until cleared.
- The kill switch never interrupts the stream; ffmpeg keeps running.
- The setting is saved, so a restart does not silently re-enable plugins.

## Security review checklist (before any code ships)

- Key never reaches the child: no key in env, events, or the working directory files.
- Command built from a list; manifest paths validated against traversal.
- Output size, rate and malformed JSON are bounded.
- Plugin text shown in the GUI is plain text, never evaluated.
- A malicious plugin can still use the user's privileges. State this plainly in the enable dialog.

## Test plan (written; see `tests/test_plugins.py`)

Round trip with fake pipes, malformed line, oversized line, unknown `v`, action without permission, flood above the rate limit, a plugin that hangs during handshake, a plugin that exits, manifest traversal attempts, and a check that no event payload contains a fake key set in the test environment.
