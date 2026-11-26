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


if __name__ == "__main__":
    unittest.main()
