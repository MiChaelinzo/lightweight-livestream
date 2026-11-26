import http.client
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lightstream import remote

KEY = "live_SECRETKEY123"


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.log = "ffmpeg ok\n"

    def snapshot(self):
        return ("LIVE", "green", "all good", self.log, True)

    def emergency(self):
        self.calls.append("emergency")
        return "Emergency mode is on."

    def restore_after_emergency(self):
        self.calls.append("restore")
        return "Your previous settings are back."

    def emergency_active(self):
        return "emergency" in self.calls

    def stop(self, wait=True):
        self.calls.append(("stop", wait))

    def timeline_lines(self):
        return ["0:05 emergency Emergency button pressed"]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.clock = FakeClock()
        self.server = remote.RemoteServer(self.backend, token="tok", clock=self.clock)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.port = self.server._httpd.server_address[1]

    def req(self, method, path, token="tok", host=None, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = dict(headers or {})
        if token is not None:
            hdrs["Authorization"] = "Bearer " + token
        if host is not None:
            hdrs["Host"] = host
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        result = (resp.status, data, resp)
        conn.close()
        return result

    def test_binds_loopback_by_default(self):
        self.assertEqual("127.0.0.1", self.server._httpd.server_address[0])
        self.assertTrue(self.server.url.startswith("http://127.0.0.1:"))
        self.assertTrue(self.server.url.endswith("#tok"))

    def test_page_is_self_contained(self):
        status, body, resp = self.req("GET", "/", token=None)
        self.assertEqual(200, status)
        self.assertNotIn(b"http://", body)
        self.assertNotIn(b"https://", body)
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    def test_status_requires_token(self):
        self.assertEqual(200, self.req("GET", "/api/status")[0])
        status, body, _ = self.req("GET", "/api/status", token="wrong")
        self.assertEqual((401, b""), (status, body))
        self.assertEqual(401, self.req("GET", "/api/status", token=None)[0])

    def test_actions_call_backend(self):
        for path in ("/api/emergency", "/api/restore", "/api/stop"):
            self.assertEqual(200, self.req("POST", path)[0])
        self.assertEqual(["emergency", "restore", ("stop", False)], self.backend.calls)

    def test_bad_token_never_calls_backend(self):
        self.assertEqual(401, self.req("POST", "/api/emergency", token="x")[0])
        self.assertEqual([], self.backend.calls)

    def test_wrong_method_is_405(self):
        self.assertEqual(405, self.req("GET", "/api/emergency")[0])
        self.assertEqual(405, self.req("POST", "/api/status")[0])
        self.assertEqual(405, self.req("PUT", "/api/stop")[0])
        self.assertEqual([], self.backend.calls)

    def test_no_start_endpoint(self):
        self.assertEqual(404, self.req("POST", "/api/start")[0])

    def test_oversized_body_rejected(self):
        status = self.req("POST", "/api/emergency",
                          body=b"x" * (remote.MAX_BODY_BYTES + 1))[0]
        self.assertEqual(413, status)
        self.assertEqual([], self.backend.calls)

    def test_foreign_host_header_refused(self):
        self.assertEqual(403, self.req("GET", "/", host="evil.example")[0])
        self.assertEqual(403, self.req("POST", "/api/emergency",
                                       host="evil.example:80")[0])
        self.assertEqual(200, self.req("GET", "/", host="localhost:1234")[0])
        self.assertEqual([], self.backend.calls)

    def test_key_never_in_response(self):
        self.backend.log = "rtmp://x/app?passphrase=%s\n" % KEY
        _, body, _ = self.req("GET", "/api/status")
        self.assertNotIn(KEY.encode(), body)
        self.assertIn(b"passphrase=****", body)

    def test_status_fields(self):
        import json
        data = json.loads(self.req("GET", "/api/status")[1])
        self.assertEqual("LIVE", data["banner"])
        self.assertFalse(data["emergency"])
        self.assertEqual(1, len(data["timeline"]))

    def test_lockout_and_expiry_use_injected_clock(self):
        for _ in range(remote.MAX_FAILURES):
            self.assertEqual(401, self.req("GET", "/api/status", token="bad")[0])
        # locked: even the right token is refused
        self.assertEqual(401, self.req("GET", "/api/status")[0])
        self.clock.now += remote.LOCKOUT_SECONDS + 1
        self.assertEqual(200, self.req("GET", "/api/status")[0])

    def test_stop_is_clean_and_idempotent(self):
        self.server.stop()
        self.server.stop()
        self.assertIsNone(self.server.url)

    def test_random_token_when_not_given(self):
        a = remote.RemoteServer(self.backend)
        b = remote.RemoteServer(self.backend)
        self.assertNotEqual(a.token, b.token)
        self.assertGreaterEqual(len(a.token), 24)


class FakeServer:
    instances = []

    def __init__(self, backend, host="127.0.0.1"):
        self.host = host
        self.token = "tok"
        self.started = self.stopped = False
        FakeServer.instances.append(self)

    @property
    def url(self):
        return "http://%s:1/#tok" % self.host if self.started and not self.stopped else None

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class RemoteSessionTests(unittest.TestCase):
    def setUp(self):
        FakeServer.instances = []
        self.session = remote.RemoteSession(FakeBackend(), FakeServer)

    def test_off_by_default_never_starts(self):
        self.assertIsNone(self.session.sync(True, False, False))
        self.assertEqual([], FakeServer.instances)

    def test_starts_only_while_running_and_stops_after(self):
        self.assertIsNone(self.session.sync(False, True, False))
        self.assertIn("127.0.0.1", self.session.sync(True, True, False))
        self.session.sync(True, True, False)
        self.assertEqual(1, len(FakeServer.instances))
        self.assertIsNone(self.session.sync(False, True, False))
        self.assertTrue(FakeServer.instances[0].stopped)

    def test_lan_binds_all_interfaces_only_when_true(self):
        self.assertEqual("0.0.0.0", remote.bind_host(True))
        self.assertEqual("127.0.0.1", remote.bind_host(False))
        self.assertEqual("127.0.0.1", remote.bind_host("yes"))

    def test_untick_and_close_stop_the_server(self):
        self.session.sync(True, True, False)
        self.session.sync(True, False, False)
        self.assertTrue(FakeServer.instances[0].stopped)
        self.session.sync(True, True, False)
        self.session.close()
        self.assertTrue(FakeServer.instances[1].stopped)
        self.assertIsNone(self.session.url)

    def test_port_failure_is_not_fatal(self):
        class Busy(FakeServer):
            def start(self):
                raise OSError("in use")
        session = remote.RemoteSession(FakeBackend(), Busy)
        self.assertIsNone(session.sync(True, True, False))

    def test_timeline_text(self):
        self.assertEqual("a\nb", remote.timeline_text(["a", "b"]))
        self.assertIn("nothing recorded", remote.timeline_text([]))


class RemotePrefsTests(unittest.TestCase):
    def test_flags_round_trip_and_token_never_saved(self):
        import tempfile
        from lightstream import gui_controller as gc
        server = remote.RemoteServer(FakeBackend(), token="SECRETTOKEN123")
        prefs = {"remote": True, "remote_lan": False, "token": server.token,
                 "remote_url": "http://x/#" + server.token}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            gc.save_prefs(path, prefs)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            loaded = gc.load_prefs(path)
        self.assertNotIn("SECRETTOKEN123", text)
        self.assertEqual({"remote": True, "remote_lan": False}, loaded)


if __name__ == "__main__":
    unittest.main()
