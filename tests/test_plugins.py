"""Plugin runtime v1 against real subprocess plugins (python3 scripts)."""

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import cli, plugins  # noqa: E402

HAVE_PYTHON = shutil.which("python3") is not None
SEEDED_KEY = "live_SEEDED_SECRET_KEY_123"

PRELUDE = '''
import json, os, sys, time
def send(action, **f):
    m = {"v": 1, "action": action}
    m.update(f)
    sys.stdout.write(json.dumps(m) + "\\n")
    sys.stdout.flush()
'''

SCRIPTS = {
    "good": PRELUDE + '''
for line in sys.stdin:
    ev = json.loads(line)
    if ev["event"] == "hello":
        send("ready")
    elif ev["event"] == "stream_started":
        send("log", text="started " + ev["platform"])
    elif ev["event"] == "shutdown":
        open("shutdown.txt", "w").write("bye")
        break
''',
    "hang": "import time\ntime.sleep(60)\n",
    "violator": PRELUDE + '''
send("ready")
for _ in range(15):
    sys.stdout.write("garbage\\n")
    sys.stdout.flush()
time.sleep(60)
''',
    "noperm": PRELUDE + '''
send("ready")
for _ in range(12):
    send("notify", text="x")
time.sleep(60)
''',
    "oversize": PRELUDE + '''
send("ready")
sys.stdout.write("x" * 40000 + "\\n")
sys.stdout.flush()
send("log", text="after")
time.sleep(60)
''',
    "badfields": PRELUDE + '''
send("ready")
sys.stdout.write(json.dumps({"action": "log", "text": "no v"}) + "\\n")
sys.stdout.write(json.dumps({"v": 2, "action": "log", "text": "v2"}) + "\\n")
send("log", text="y" * 501)
send("launch_rockets")
send("log", text="fine")
sys.stdout.flush()
time.sleep(60)
''',
    "flood": PRELUDE + '''
send("ready")
for i in range(100):
    send("log", text=str(i))
time.sleep(60)
''',
    "exits": PRELUDE + '''
send("ready")
''',
    "env": PRELUDE + '''
send("ready")
send("log", text=json.dumps(sorted(os.environ)))
time.sleep(60)
''',
    "stderr": PRELUDE + '''
send("ready")
sys.stderr.write("A" * 10000 + "TAIL " + os.environ.get("X", "") + "\\n")
sys.stderr.write("secret=" + %r + "\\n")
sys.stderr.flush()
time.sleep(60)
''' % SEEDED_KEY,
    "deaf": PRELUDE + '''
send("ready")
time.sleep(60)
''',
}


def write_plugin(root, name, script, events=("stream_started",),
                 permissions=("log",), command=None):
    folder = os.path.join(root, name)
    os.makedirs(folder)
    with open(os.path.join(folder, "main.py"), "w") as fh:
        fh.write(SCRIPTS[script])
    manifest = {"v": 1, "name": name, "version": "0.0.1",
                "command": command or ["python3", "main.py"],
                "events": list(events), "permissions": list(permissions)}
    with open(os.path.join(folder, "plugin.json"), "w") as fh:
        json.dump(manifest, fh)
    return folder


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@unittest.skipUnless(HAVE_PYTHON, "python3 not on PATH")
class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.started = []
        grace = mock.patch.object(plugins, "SHUTDOWN_GRACE_S", 0.3)
        grace.start()
        self.addCleanup(grace.stop)

    def tearDown(self):
        for proc in self.started:
            proc.stop()
            if proc._proc is not None and proc._proc.poll() is None:
                proc._proc.kill()
        shutil.rmtree(self.root, ignore_errors=True)

    def launch(self, name, script=None, start=True, **kwargs):
        script = script or name
        events = kwargs.pop("events", ("stream_started",))
        permissions = kwargs.pop("permissions", ("log",))
        folder = write_plugin(self.root, name, script, events, permissions)
        kwargs.setdefault("handshake_timeout", 5.0)
        proc = plugins.PluginProcess(folder, "0.15.0", **kwargs)
        self.started.append(proc)
        if start:
            proc.start()
        return proc

    def test_handshake_and_round_trip(self):
        proc = self.launch("good")
        self.assertEqual(proc.state, "running")
        self.assertTrue(proc.send_event("stream_started", platform="twitch"))
        self.assertTrue(wait_until(lambda: proc._actions))
        self.assertEqual(proc.drain_actions(), [{"action": "log", "text": "started twitch"}])
        self.assertEqual(proc.drain_actions(), [])

    def test_unlisted_event_is_not_sent(self):
        proc = self.launch("good", events=("health",))
        self.assertFalse(proc.send_event("stream_started", platform="twitch"))
        time.sleep(0.2)
        self.assertEqual(proc.drain_actions(), [])

    def test_shutdown_event_is_delivered_on_stop(self):
        proc = self.launch("good")
        proc.stop()
        self.assertEqual(proc.state, "stopped")
        with open(os.path.join(proc.folder, "shutdown.txt")) as fh:
            self.assertEqual(fh.read(), "bye")
        self.assertIsNotNone(proc._proc.poll())

    def test_handshake_timeout_disables_and_kills(self):
        proc = self.launch("hang", handshake_timeout=0.4)
        self.assertEqual(proc.state, "disabled")
        self.assertIn("no ready", proc.reason)
        self.assertTrue(wait_until(lambda: proc._proc.poll() is not None))

    def test_missing_program_disables(self):
        folder = write_plugin(self.root, "ghost", "good",
                              command=["definitely-not-a-program-xyz"])
        proc = plugins.PluginProcess(folder, "0.15.0")
        self.started.append(proc)
        self.assertFalse(proc.start())
        self.assertEqual(proc.state, "disabled")

    def test_ten_malformed_lines_disable_the_plugin(self):
        proc = self.launch("violator")
        self.assertTrue(wait_until(lambda: proc.state == "disabled"))
        self.assertEqual(proc.violations, plugins.MAX_VIOLATIONS)
        self.assertTrue(wait_until(lambda: proc._proc.poll() is not None))

    def test_actions_without_permission_are_violations(self):
        proc = self.launch("noperm", permissions=("log",))
        self.assertTrue(wait_until(lambda: proc.state == "disabled"))
        self.assertEqual(proc.drain_actions(), [])
        self.assertIn("without permission", proc.reason)

    def test_oversized_line_is_one_violation_and_stream_recovers(self):
        proc = self.launch("oversize")
        self.assertTrue(wait_until(lambda: proc._actions))
        self.assertEqual(proc.violations, 1)
        self.assertEqual(proc.drain_actions(), [{"action": "log", "text": "after"}])
        self.assertEqual(proc.state, "running")

    def test_bad_version_unknown_action_and_long_text_are_violations(self):
        proc = self.launch("badfields")
        self.assertTrue(wait_until(lambda: proc._actions))
        self.assertEqual(proc.drain_actions(), [{"action": "log", "text": "fine"}])
        self.assertEqual(proc.violations, 4)

    def test_flood_above_rate_limit_is_dropped(self):
        proc = self.launch("flood", clock=FakeClock())
        self.assertTrue(wait_until(lambda: proc.dropped_messages == 100 + 1 - plugins.MAX_MESSAGES_PER_SECOND))
        accepted = proc.drain_actions()
        self.assertEqual(len(accepted), plugins.MAX_MESSAGES_PER_SECOND - 1)  # ready used one slot
        self.assertEqual(proc.violations, 0)
        self.assertEqual(proc.state, "running")

    def test_crash_restarts_once_then_disables(self):
        clock = FakeClock()
        proc = self.launch("exits", clock=clock)
        self.assertTrue(wait_until(lambda: proc._proc.poll() is not None))
        self.assertEqual(proc.supervise(), "exited")
        clock.now += plugins.RESTART_DELAY_S - 1
        self.assertEqual(proc.supervise(), "exited")
        clock.now += 1
        self.assertEqual(proc.supervise(), "running")
        self.assertEqual(proc.restarts, 1)
        self.assertTrue(wait_until(lambda: proc._proc.poll() is not None))
        self.assertEqual(proc.supervise(), "disabled")

    def test_environment_is_minimal_and_has_no_key(self):
        with mock.patch.dict(os.environ, {"LIGHTSTREAM_KEY": SEEDED_KEY,
                                          "STREAM_KEY": SEEDED_KEY}):
            proc = self.launch("env")
            self.assertTrue(wait_until(lambda: proc._actions))
        names = json.loads(proc.drain_actions()[0]["text"])
        self.assertNotIn("LIGHTSTREAM_KEY", names)
        self.assertNotIn("STREAM_KEY", names)
        self.assertIn("LIGHTSTREAM_PLUGIN", names)
        self.assertIn("PATH", names)
        self.assertLessEqual(set(names) - {"PATH", "LIGHTSTREAM_PLUGIN"},
                             {"LC_CTYPE", "PWD", "SHLVL", "_"})  # added by the OS or python

    def test_stderr_is_truncated_and_redacted(self):
        proc = self.launch("stderr", secrets=(SEEDED_KEY,))
        self.assertTrue(wait_until(lambda: "secret=" in proc.stderr_tail()))
        tail = proc.stderr_tail()
        self.assertLessEqual(len(tail.encode()), plugins.STDERR_TAIL_BYTES)
        self.assertIn("***", tail)
        self.assertNotIn(SEEDED_KEY, tail)

    def test_plugin_that_never_reads_cannot_block_the_host(self):
        proc = self.launch("deaf", events=("insight",))
        started = time.monotonic()
        for i in range(500):
            proc.send_event("insight", text="x" * 4000, confidence="high")
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertLessEqual(len(proc._out), plugins.OUTBOUND_QUEUE_LIMIT)
        proc.stop()
        self.assertIsNotNone(proc._proc.poll())

    def test_event_with_key_is_refused(self):
        proc = self.launch("good", secrets=(SEEDED_KEY,))
        with self.assertRaises(ValueError):
            proc.send_event("stream_started", platform="rtmp://x/" + SEEDED_KEY)

    def test_host_starts_only_enabled_plugins(self):
        write_plugin(self.root, "one", "good")
        write_plugin(self.root, "two", "good")
        host = plugins.PluginHost(self.root, [], "0.15.0")
        self.assertEqual(host.start_all(), [])
        host = plugins.PluginHost(self.root, ["one", "missing"], "0.15.0", log=lambda t: None)
        try:
            self.assertEqual([p.name for p in host.start_all()], ["one"])
            host.broadcast("stream_started", platform="twitch")
            self.assertTrue(wait_until(lambda: host.collect_actions() or False))
        finally:
            host.stop_all()

    def test_host_refuses_enabled_names_that_leave_the_plugins_folder(self):
        outside = os.path.join(self.root, "outer")
        inside = os.path.join(outside, "plugins")
        os.makedirs(inside)
        write_plugin(outside, "one", "good")
        logs = []
        host = plugins.PluginHost(inside, ["../one", "..", 5], "0.15.0", log=logs.append)
        try:
            self.assertEqual(host.start_all(), [])
        finally:
            host.stop_all()
        self.assertEqual(len(logs), 3)
        self.assertTrue(all("not started" in line for line in logs))


class EventCase(unittest.TestCase):
    def test_extra_field_wrong_type_and_unknown_event_are_refused(self):
        with self.assertRaises(ValueError):
            plugins.build_event("stream_started", {"platform": "twitch", "url": "x"})
        with self.assertRaises(ValueError):
            plugins.build_event("health", {"fps": "30", "bitrate_kbps": 1, "dropped": 0})
        with self.assertRaises(ValueError):
            plugins.build_event("status", {"state": "weird"})
        with self.assertRaises(ValueError):
            plugins.build_event("set_bitrate", {})

    def test_valid_event_has_version(self):
        message = plugins.build_event("health", {"fps": 30.0, "bitrate_kbps": 4500, "dropped": 0})
        self.assertEqual(message["v"], 1)
        self.assertEqual(message["event"], "health")

    def test_secret_with_json_escaped_characters_is_refused(self):
        for secret in ('ab"cd', "ab\\cd", "k\u00e9y-12345"):
            with self.assertRaises(ValueError, msg=secret):
                plugins.build_event("insight", {"text": "oops " + secret, "confidence": "high"},
                                    secrets=[secret])

    def test_minimal_env(self):
        self.assertEqual(plugins.minimal_env({"PATH": "/bin", "LIGHTSTREAM_KEY": "k"}),
                         {"PATH": "/bin", "LIGHTSTREAM_PLUGIN": "1"})


class ManifestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.folder = os.path.join(self.root, "demo")
        os.makedirs(self.folder)
        self.good = {"v": 1, "name": "demo", "version": "1", "command": ["python3", "main.py"],
                     "events": ["health"], "permissions": ["log"]}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def problems(self, **changes):
        manifest = dict(self.good)
        manifest.update(changes)
        return plugins.validate_manifest(manifest, self.folder)

    def test_good_manifest(self):
        self.assertEqual(self.problems(), [])

    def test_bad_manifests(self):
        for changes in (
                {"v": 2}, {"name": "Demo"}, {"name": "other"}, {"name": "x" * 33},
                {"version": ""}, {"command": []}, {"command": "python3 main.py"},
                {"command": ["/usr/bin/python3"]}, {"command": ["../evil.sh"]},
                {"command": ["sub/../../evil"]}, {"command": ["C:\\evil.exe"]},
                {"events": ["set_bitrate"]}, {"events": ["hello"]}, {"events": "health"},
                {"permissions": ["network"]}):
            self.assertTrue(self.problems(**changes), changes)

    def test_not_an_object(self):
        self.assertTrue(plugins.validate_manifest([], self.folder))

    def test_symlink_escape_is_refused(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlinks")
        outside = os.path.join(self.root, "outside.sh")
        open(outside, "w").close()
        os.symlink(outside, os.path.join(self.folder, "link"))
        self.assertTrue(self.problems(command=["./link"]))

    def test_load_manifest_errors(self):
        with self.assertRaises(plugins.ManifestError):
            plugins.load_manifest(self.folder)  # missing file
        path = os.path.join(self.folder, "plugin.json")
        with open(path, "w") as fh:
            fh.write("{nope")
        with self.assertRaises(plugins.ManifestError):
            plugins.load_manifest(self.folder)
        with open(path, "w") as fh:
            json.dump(dict(self.good, events=["x"]), fh)
        with self.assertRaises(plugins.ManifestError) as ctx:
            plugins.load_manifest(self.folder)
        self.assertIn("unknown events", str(ctx.exception))

    def test_discover_marks_enabled_and_invalid(self):
        with open(os.path.join(self.folder, "plugin.json"), "w") as fh:
            json.dump(self.good, fh)
        os.makedirs(os.path.join(self.root, "broken"))
        found = plugins.discover(self.root, enabled=["demo"])
        self.assertEqual([(f["name"], f["enabled"], f["error"] is None) for f in found],
                         [("broken", False, False), ("demo", True, True)])
        self.assertEqual(plugins.discover(os.path.join(self.root, "none")), [])


@unittest.skipUnless(HAVE_PYTHON, "python3 not on PATH")
class CliCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_cli(self, *argv):
        out = io.StringIO()
        code = cli.main(["plugins"] + list(argv), out)
        return code, out.getvalue()

    def test_run_demo_uses_the_example_plugin(self):
        code, text = self.run_cli("run-demo")
        self.assertEqual(code, 0, text)
        self.assertIn("stream started on demo", text)

    def test_check_and_list_example(self):
        examples = os.path.join(os.path.dirname(__file__), "..", "examples", "plugins")
        code, text = self.run_cli("check", "hello", "--plugins-dir", examples)
        self.assertEqual(code, 0)
        self.assertIn("manifest valid", text)
        code, text = self.run_cli("list", "--plugins-dir", examples)
        self.assertIn("off", text)  # not enabled in any config

    def test_check_invalid_and_empty_list(self):
        code, text = self.run_cli("check", "nothere", "--plugins-dir", self.root)
        self.assertEqual(code, 1)
        self.assertIn("INVALID", text)
        code, text = self.run_cli("list", "--plugins-dir", self.root)
        self.assertEqual(code, 0)
        self.assertIn("off unless", text)

    def test_check_rejects_traversal_name(self):
        code, text = self.run_cli("check", "../hello", "--plugins-dir", self.root)
        self.assertNotEqual(code, 0)
        self.assertNotIn("manifest valid", text)

    def test_list_rejects_non_list_plugins_setting(self):
        config = os.path.join(self.root, "config.json")
        for bad in ("hello", [1], {"a": 1}):
            with open(config, "w", encoding="utf-8") as fh:
                json.dump({"plugins": bad}, fh)
            args = argparse.Namespace(action="list", name=None, plugins_dir=self.root)
            with self.assertRaises(ValueError, msg=repr(bad)):
                cli.cmd_plugins(args, io.StringIO(), config_file=config)


if __name__ == "__main__":
    unittest.main()
