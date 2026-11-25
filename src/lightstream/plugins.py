"""Plugin runtime v1, implementing docs/architecture/PLUGIN-PROTOCOL.md.

A plugin is a separate OS process that talks JSON lines on stdin and stdout.
The host never imports plugin code. This is NOT OS isolation: a plugin runs
with the user's own privileges, and the permission list limits only what the
host does on the plugin's behalf.

Plugins are off by default: nothing starts unless its name is in the
`plugins` list of config.json. This module is a library plus the
`lightstream plugins` command; it is not wired into the stream runner yet.
"""

import json
import os
import re
import subprocess
import threading
import time
from collections import deque

PROTOCOL_VERSION = 1
HANDSHAKE_TIMEOUT_S = 5.0
SHUTDOWN_GRACE_S = 3.0
KILL_WAIT_S = 2.0
RESTART_DELAY_S = 5.0
MAX_RESTARTS = 1
MAX_LINE_BYTES = 16 * 1024
MAX_MESSAGES_PER_SECOND = 20
RATE_WINDOW_S = 1.0
MAX_VIOLATIONS = 10
STDERR_TAIL_BYTES = 4 * 1024
OUTBOUND_QUEUE_LIMIT = 64
PLUGINS_DIRNAME = "plugins"
MANIFEST_FILENAME = "plugin.json"
ENV_MARKER = "LIGHTSTREAM_PLUGIN"
REDACTED = "***"

NAME_PATTERN = re.compile(r"[a-z0-9-]{1,32}")  # use fullmatch: "$" would accept a trailing newline

# Events the host may send, with the only fields each may carry.
STATE_VALUES = ("live", "reconnecting", "failover", "stopped")
EVENT_FIELDS = {
    "hello": {"host": str, "host_version": str, "permissions": list},
    "stream_started": {"platform": str},
    "stream_stopped": {"reason": str},
    "status": {"state": str},
    "insight": {"text": str, "confidence": (str, int, float)},
    "health": {"fps": (int, float), "bitrate_kbps": (int, float), "dropped": int},
    "shutdown": {},
}
ALWAYS_SENT_EVENTS = ("hello", "shutdown")
MANIFEST_EVENTS = tuple(e for e in EVENT_FIELDS if e not in ALWAYS_SENT_EVENTS)

# Action name -> (permission needed or None, max text length or None).
ACTION_RULES = {
    "ready": (None, None),
    "log": ("log", 500),
    "overlay_text": ("overlay_text", 120),
    "notify": ("notify", 200),
}
PERMISSIONS = ("log", "overlay_text", "notify")


class ManifestError(ValueError):
    """A plugin.json that breaks a rule of the protocol."""


def plugins_dir(config_file_path):
    """plugins/ folder next to config.json."""
    return os.path.join(os.path.dirname(config_file_path), PLUGINS_DIRNAME)


def _command_error(command, folder):
    if not isinstance(command, list) or not command or \
            not all(isinstance(part, str) and part for part in command):
        return "command must be a non-empty list of strings"
    program = command[0]
    if "/" not in program and "\\" not in program:
        return None  # bare program name, found on PATH
    if os.path.isabs(program) or re.match(r"^[A-Za-z]:", program):
        return "command[0] must not be an absolute path"
    parts = re.split(r"[\\/]", program)
    if ".." in parts:
        return "command[0] must not contain '..'"
    root = os.path.realpath(folder)
    target = os.path.realpath(os.path.join(folder, program))
    if target != root and not target.startswith(root + os.sep):
        return "command[0] resolves outside the plugin folder"
    return None


def _name_list_error(manifest, key, known):
    values = manifest.get(key, [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        return "%s must be a list of strings" % key
    unknown = sorted(set(values) - set(known))
    if unknown:
        return "unknown %s: %s" % (key, ", ".join(unknown))
    return None


def validate_manifest(manifest, folder):
    """Return a list of problems (empty when the manifest is valid)."""
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    problems = []
    if manifest.get("v") != PROTOCOL_VERSION:
        problems.append("v must be %d" % PROTOCOL_VERSION)
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        problems.append("name must match [a-z0-9-]{1,32}")
    elif name != os.path.basename(os.path.normpath(folder)):
        problems.append("name must equal the folder name")
    if not isinstance(manifest.get("version"), str) or not manifest.get("version"):
        problems.append("version must be a non-empty string")
    problem = _command_error(manifest.get("command"), folder)
    if problem:
        problems.append(problem)
    for key, known in (("events", MANIFEST_EVENTS), ("permissions", PERMISSIONS)):
        problem = _name_list_error(manifest, key, known)
        if problem:
            problems.append(problem)
    return problems


def load_manifest(folder):
    """Read and validate plugin.json. Raises ManifestError with every problem."""
    path = os.path.join(folder, MANIFEST_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except OSError as exc:
        raise ManifestError("cannot read %s: %s" % (MANIFEST_FILENAME, exc.strerror or exc))
    except ValueError as exc:
        raise ManifestError("%s is not valid JSON: %s" % (MANIFEST_FILENAME, exc))
    problems = validate_manifest(manifest, folder)
    if problems:
        raise ManifestError("; ".join(problems))
    return manifest


def discover(directory, enabled=()):
    """List plugin folders as dicts: name, folder, enabled, error (None if valid)."""
    found = []
    if not os.path.isdir(directory):
        return found
    for entry in sorted(os.listdir(directory)):
        folder = os.path.join(directory, entry)
        if not os.path.isdir(folder):
            continue
        try:
            load_manifest(folder)
            error = None
        except ManifestError as exc:
            error = str(exc)
        found.append({"name": entry, "folder": folder,
                      "enabled": entry in enabled, "error": error})
    return found


def minimal_env(environ=None):
    """The only environment a plugin gets: PATH and the marker."""
    environ = os.environ if environ is None else environ
    return {"PATH": environ.get("PATH", ""), ENV_MARKER: "1"}


def build_event(name, fields, secrets=()):
    """Check an event against the protocol and return the message dict.

    Raises ValueError for an unknown event, a field that is not in the
    protocol table, a wrong type, or a value containing a known secret
    (stream key or ingest URL). Strict on purpose: nothing extra can leak.
    """
    allowed = EVENT_FIELDS.get(name)
    if allowed is None:
        raise ValueError("unknown event %r" % name)
    extra = sorted(set(fields) - set(allowed))
    if extra:
        raise ValueError("event %s has fields outside the protocol: %s" % (name, ", ".join(extra)))
    for key, value in fields.items():
        if isinstance(value, bool) or not isinstance(value, allowed[key]):
            raise ValueError("event %s field %s has the wrong type" % (name, key))
    if name == "status" and fields.get("state") not in STATE_VALUES:
        raise ValueError("status state must be one of %s" % ", ".join(STATE_VALUES))
    # Check raw string values and both JSON forms: json.dumps escapes quotes,
    # backslashes and (by default) non-ASCII, so a secret with such characters
    # would not match the serialized text alone.
    raw_values = [v for v in fields.values() if isinstance(v, str)]
    serialized_forms = (json.dumps(fields), json.dumps(fields, ensure_ascii=False))
    for secret in secrets:
        if not secret:
            continue
        if (any(secret in value for value in raw_values)
                or any(secret in form for form in serialized_forms)):
            raise ValueError("event %s would expose a protected value" % name)
    message = {"v": PROTOCOL_VERSION, "event": name}
    message.update(fields)
    return message


def _redact(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class PluginProcess:
    """One running plugin: handshake, rate limit, violations, bounded writes."""

    def __init__(self, folder, host_version, secrets=(), clock=time.monotonic,
                 handshake_timeout=HANDSHAKE_TIMEOUT_S, environ=None):
        self.folder = folder
        self.manifest = load_manifest(folder)
        self.name = self.manifest["name"]
        self._host_version = host_version
        self._secrets = tuple(s for s in secrets if s)
        self._clock = clock
        self._handshake_timeout = handshake_timeout
        self._environ = environ
        self.state = "new"  # new, running, exited, disabled, stopped
        self.reason = ""
        self.violations = 0
        self.dropped_messages = 0
        self.restarts = 0
        self._exited_at = None
        self._lock = threading.Lock()
        self._actions = []
        self._proc = None
        self._stderr_tail = bytearray()
        self._times = deque()
        self._out = deque(maxlen=OUTBOUND_QUEUE_LIMIT)
        self._out_cond = threading.Condition()
        self._closing = False
        self._ready = threading.Event()
        self._threads = []

    # public API

    def start(self):
        """Launch the process and wait for `ready`. False means it was disabled."""
        if self.state in ("running", "disabled", "stopped"):
            return self.state == "running"
        self._reset_run()
        argv = list(self.manifest["command"])
        try:
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=self.folder, shell=False,
                env=minimal_env(self._environ))
        except OSError as exc:
            self._disable("cannot start: %s" % (exc.strerror or exc))
            return False
        self.state = "running"
        self._spawn(self._read_stdout)
        self._spawn(self._read_stderr)
        self._spawn(self._write_stdin)
        self._queue(build_event("hello", {
            "host": "lightstream", "host_version": self._host_version,
            "permissions": list(self.manifest.get("permissions", []))}))
        if not self._ready.wait(self._handshake_timeout):
            self._disable("no ready within %g s" % self._handshake_timeout)
            return False
        return self.state == "running"

    def send_event(self, name, **fields):
        """Queue an event if the manifest asked for it. True when queued."""
        if self.state != "running":
            return False
        if name not in ALWAYS_SENT_EVENTS and name not in self.manifest.get("events", []):
            return False
        self._queue(build_event(name, fields, self._secrets))
        return True

    def drain_actions(self):
        """Return and clear the accepted actions: dicts with `action` and `text`."""
        with self._lock:
            actions, self._actions = self._actions, []
        return actions

    def stderr_tail(self):
        with self._lock:
            text = bytes(self._stderr_tail).decode("utf-8", "replace")
        return _redact(text, self._secrets)

    def supervise(self):
        """Call now and then: restart a crashed plugin once after 5 s, then disable."""
        proc = self._proc
        if self.state == "running" and proc is not None and proc.poll() is not None:
            self.state = "exited"
            self._exited_at = self._clock()
            self._reap()
        if self.state == "exited":
            if self.restarts >= MAX_RESTARTS:
                self._disable("exited again after a restart")
            elif self._clock() - self._exited_at >= RESTART_DELAY_S:
                self.restarts += 1
                self.state = "new"
                self.start()
        return self.state

    def stop(self):
        """shutdown event, wait 3 s, then terminate, then kill."""
        if self.state == "stopped":
            return
        proc = self._proc
        if self.state == "running" and proc is not None and proc.poll() is None:
            self._queue(build_event("shutdown", {}))
        self._finish(graceful=self.state == "running")
        if self.state != "disabled":
            self.state = "stopped"

    # internals

    def _reset_run(self):
        self._ready.clear()
        self._closing = False
        self._out.clear()
        self._threads = []
        self.reason = ""

    def _spawn(self, target):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _queue(self, message):
        with self._out_cond:
            self._out.append(json.dumps(message, separators=(",", ":")) + "\n")
            self._out_cond.notify()

    def _write_stdin(self):
        stdin = self._proc.stdin
        while True:
            with self._out_cond:
                while not self._out and not self._closing:
                    self._out_cond.wait()
                if not self._out:
                    return
                line = self._out.popleft()
            try:
                stdin.write(line.encode("utf-8"))
                stdin.flush()
            except (OSError, ValueError):
                return

    def _read_stderr(self):
        stream = self._proc.stderr
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                return
            with self._lock:
                self._stderr_tail.extend(chunk)
                del self._stderr_tail[:-STDERR_TAIL_BYTES]

    def _read_stdout(self):
        stream = self._proc.stdout
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if line.endswith(b"\n"):
                body = line[:-1]
                oversized = len(body) > MAX_LINE_BYTES
            else:
                oversized = len(line) > MAX_LINE_BYTES
                body = line
            if oversized and not line.endswith(b"\n"):
                self._drain_line(stream)
            if oversized:
                self._violation("line longer than %d bytes" % MAX_LINE_BYTES)
            elif body.strip():
                self._handle(body)
            if self.state == "disabled":
                return

    @staticmethod
    def _drain_line(stream):
        while True:
            rest = stream.readline(MAX_LINE_BYTES + 1)
            if not rest or rest.endswith(b"\n"):
                return

    def _rate_ok(self):
        now = self._clock()
        while self._times and now - self._times[0] >= RATE_WINDOW_S:
            self._times.popleft()
        if len(self._times) >= MAX_MESSAGES_PER_SECOND:
            self.dropped_messages += 1
            return False
        self._times.append(now)
        return True

    def _handle(self, body):
        if not self._rate_ok():
            return
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._violation("malformed JSON")
            return
        if not isinstance(message, dict) or message.get("v") != PROTOCOL_VERSION:
            self._violation("missing or unknown v")
            return
        action = message.get("action")
        rule = ACTION_RULES.get(action) if isinstance(action, str) else None
        if rule is None:
            self._violation("unknown action")
            return
        permission, max_text = rule
        if permission and permission not in self.manifest.get("permissions", []):
            self._violation("action %s without permission" % action)
            return
        if not self._ready.is_set() and action != "ready":
            self._violation("action %s before ready" % action)
            return
        if action == "ready":
            self._ready.set()
            return
        text = message.get("text")
        if not isinstance(text, str) or len(text) > max_text:
            self._violation("action %s needs text of at most %d chars" % (action, max_text))
            return
        with self._lock:
            self._actions.append({"action": action, "text": text})

    def _violation(self, reason):
        self.violations += 1
        if self.violations >= MAX_VIOLATIONS and self.state != "disabled":
            self._disable("%d violations, last: %s" % (self.violations, reason))

    def _disable(self, reason):
        self.reason = reason
        self.state = "disabled"
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()
        self._ready.set()  # release a waiting start()
        with self._out_cond:
            self._closing = True
            self._out_cond.notify()

    def _reap(self):
        with self._out_cond:
            self._closing = True
            self._out_cond.notify()
        self._close_pipes()

    def _finish(self, graceful):
        proc = self._proc
        if proc is None:
            return
        with self._out_cond:
            self._closing = True
            self._out_cond.notify()
        writer = self._threads[2] if len(self._threads) > 2 else None
        if writer is not None and writer is not threading.current_thread():
            writer.join(1.0)
        try:
            if proc.poll() is None:
                try:
                    proc.wait(SHUTDOWN_GRACE_S if graceful else 0)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(KILL_WAIT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
        finally:
            self._close_pipes()
            for thread in self._threads:
                if thread is not threading.current_thread():
                    thread.join(1.0)

    def _close_pipes(self):
        proc = self._proc
        if proc is None:
            return
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass


class PluginHost:
    """The enabled plugins of one session. Empty unless names are enabled."""

    def __init__(self, directory, enabled, host_version, secrets=(), log=None):
        self.directory = directory
        self.enabled = tuple(enabled)
        self.host_version = host_version
        self.secrets = tuple(secrets)
        self.log = log or (lambda text: None)
        self.processes = []

    def start_all(self):
        """Start each enabled plugin; a bad one is reported and skipped."""
        for name in self.enabled:
            if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
                self.log("plugin %r not started: name must match [a-z0-9-]{1,32}" % (name,))
                continue
            folder = os.path.join(self.directory, name)
            try:
                plugin = PluginProcess(folder, self.host_version, self.secrets)
            except ManifestError as exc:
                self.log("plugin %s not started: %s" % (name, exc))
                continue
            if plugin.start():
                self.processes.append(plugin)
            else:
                self.log("plugin %s disabled: %s" % (name, plugin.reason))
        return list(self.processes)

    def broadcast(self, name, **fields):
        for plugin in self.processes:
            plugin.send_event(name, **fields)

    def collect_actions(self):
        """Pairs of (plugin name, action dict) from every plugin."""
        pairs = []
        for plugin in self.processes:
            plugin.supervise()
            pairs.extend((plugin.name, action) for action in plugin.drain_actions())
        return pairs

    def stop_all(self):
        for plugin in self.processes:
            plugin.stop()
        self.processes = []

