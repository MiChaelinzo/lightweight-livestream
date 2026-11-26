"""Phone remote: a tiny local control API (opt-in, off by default).

Binds 127.0.0.1 unless the caller passes another host explicitly. Every API
call needs a random bearer token (secrets, compared with hmac.compare_digest).
The Host header must be loopback, the bound host or an IP literal (an
attacker's DNS name can never be an IP literal, so DNS rebinding stays
blocked; hostnames other than localhost are refused). No CORS headers are sent. Repeated bad tokens from one address
lock that address out for a growing, deterministic delay (injected clock).

Start is deliberately not exposed: starting needs the stream key, and the key
never travels through this server. The backend is any object with snapshot(),
emergency(), restore_after_emergency(), emergency_active(), stop(wait) and
timeline_lines() (StreamController fits), so tests use a fake.
"""

import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .runner import redact

DEFAULT_HOST = "127.0.0.1"
MAX_BODY_BYTES = 1024
MAX_FAILURES = 5            # bad tokens from one address before lockout
LOCKOUT_SECONDS = 30.0
SOCKET_TIMEOUT_SECONDS = 10
STATUS_LOG_CHARS = 2000
STATUS_TIMELINE_LINES = 10
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
LAN_HOST = "0.0.0.0"

REMOTE_LABEL = "Phone remote (this PC network only, off by default)"
REMOTE_LAN_LABEL = "Allow my home network"
REMOTE_LAN_WARNING = ("Anyone on your home network who gets the link below can "
                      "press Emergency or Stop. Keep the link private. The remote "
                      "can never start a stream or see your key.")
REMOTE_HINT = ("Starts when you start a stream and stops when it ends. "
               "The link holds a one-time token. It is not saved.")
TIMELINE_EMPTY = ("Session timeline: nothing recorded yet. Events appear here "
                  "when Guardian or Auto-survival is on.")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LightStream remote</title>
<style>
body{font-family:system-ui,sans-serif;background:#12121a;color:#e8e8f0;margin:0;padding:16px}
h1{font-size:1.2rem}#banner{font-size:1.4rem;margin:12px 0}
button{display:block;width:100%;font-size:1.1rem;padding:16px;margin:10px 0;border:0;
border-radius:10px;background:#3b3b5c;color:#fff}
button.danger{background:#a33}pre{white-space:pre-wrap;font-size:.8rem;color:#aab}
</style></head><body>
<h1>LightStream remote</h1><div id="banner">...</div><div id="help"></div>
<button class="danger" onclick="act('emergency')">Emergency mode</button>
<button onclick="act('restore')">Restore settings</button>
<button onclick="if(confirm('Stop the stream?'))act('stop')">Stop stream</button>
<pre id="lines"></pre><div id="msg"></div>
<script>
var token=location.hash.slice(1);
function call(path,method){return fetch(path,{method:method,
headers:{Authorization:'Bearer '+token}}).then(function(r){
if(!r.ok)throw new Error('Request refused ('+r.status+')');return r.json();});}
function show(s){document.getElementById('banner').textContent=s.banner;
document.getElementById('help').textContent=s.help;
document.getElementById('lines').textContent=s.timeline.join('\\n');}
function refresh(){call('/api/status','GET').then(show).catch(function(e){
document.getElementById('msg').textContent=e.message;});}
function act(name){call('/api/'+name,'POST').then(function(r){
document.getElementById('msg').textContent=r.message;refresh();}).catch(function(e){
document.getElementById('msg').textContent=e.message;});}
refresh();setInterval(refresh,3000);
</script></body></html>
"""


def lan_address():
    """This PC's LAN IPv4 address for the phone link, or None when unknown.
    A UDP connect sends no packets; it only asks the OS which interface would
    be used."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))     # TEST-NET-1, never routed
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address == LAN_HOST else address


def is_ip_literal(name):
    """True for 10.0.0.5 or [fe80::1]; False for any DNS name."""
    try:
        ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        return False
    return True


class LockoutTracker:
    """Per-address failed-auth counter. Deterministic: time is injected."""

    def __init__(self, clock=time.monotonic, max_failures=MAX_FAILURES,
                 lockout_seconds=LOCKOUT_SECONDS):
        self._clock = clock
        self._max = max_failures
        self._seconds = lockout_seconds
        self._failures = {}
        self._locked_until = {}
        self._lock = threading.Lock()

    def _prune(self, now):
        for address in [a for a, until in self._locked_until.items() if now >= until]:
            del self._locked_until[address]
            self._failures.pop(address, None)

    def locked(self, address):
        with self._lock:
            self._prune(self._clock())
            until = self._locked_until.get(address)
            if until is None:
                return False
            if self._clock() >= until:
                del self._locked_until[address]
                self._failures.pop(address, None)
                return False
            return True

    def record_failure(self, address):
        with self._lock:
            count = self._failures.get(address, 0) + 1
            self._failures[address] = count
            if count >= self._max:
                self._locked_until[address] = self._clock() + self._seconds

    def record_success(self, address):
        with self._lock:
            self._failures.pop(address, None)


def build_status(backend):
    """The /api/status payload. Log text goes through redact (it also masks SRT
    passphrases); the stream key is never in the backend's reach here."""
    banner, _color, help_text, log_text, running = backend.snapshot()
    return {
        "banner": redact(str(banner), ""),
        "help": redact(str(help_text), ""),
        "running": bool(running),
        "emergency": bool(backend.emergency_active()),
        "log": redact(str(log_text), "")[-STATUS_LOG_CHARS:],
        "timeline": [redact(str(line), "")
                     for line in backend.timeline_lines()][-STATUS_TIMELINE_LINES:],
    }


class RemoteServer:
    """Opt-in local HTTP control server. start() once, stop() when done."""

    def __init__(self, backend, host=DEFAULT_HOST, port=0, token=None,
                 clock=time.monotonic, advertise_host=None):
        self._backend = backend
        self._advertise = advertise_host
        self._host = host
        self._port = port
        self.token = token or secrets.token_urlsafe(24)
        self._lockout = LockoutTracker(clock)
        self._httpd = None
        self._thread = None

    @property
    def url(self):
        """Address plus the token in the fragment (fragments are not sent to
        the server, so the token stays out of access logs)."""
        if self._httpd is None:
            return None
        host, port = self._httpd.server_address[:2]
        if host == LAN_HOST:
            host = self._advertise or lan_address() or "<this-PC-address>"
        return "http://%s:%d/#%s" % (host, port, self.token)

    def start(self):
        if self._httpd is not None:
            return
        server = self
        allowed = set(LOOPBACK_HOSTS) | {self._host}

        class Handler(BaseHTTPRequestHandler):
            server_version = "LightStreamRemote"
            protocol_version = "HTTP/1.0"
            timeout = SOCKET_TIMEOUT_SECONDS    # stalled clients free their thread

            def log_message(self, *_args):
                pass    # never log request lines

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code, payload):
                self._send(code, json.dumps(payload).encode("utf-8"))

            def _host_ok(self):
                host = self.headers.get("Host", "")
                if host.startswith("["):
                    name = host[:host.find("]") + 1]
                else:
                    name = host.rsplit(":", 1)[0] if ":" in host else host
                return name in allowed or is_ip_literal(name)

            def _authorized(self):
                address = self.client_address[0]
                if server._lockout.locked(address):
                    return False
                header = self.headers.get("Authorization", "")
                supplied = header[7:] if header.startswith("Bearer ") else ""
                if hmac.compare_digest(supplied.encode("utf-8"),
                                       server.token.encode("utf-8")):
                    server._lockout.record_success(address)
                    return True
                server._lockout.record_failure(address)
                return False

            def _drain_body(self):
                """False when the body is missing a valid length or too big."""
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return False
                if length < 0 or length > MAX_BODY_BYTES:
                    return False
                if length:
                    self.rfile.read(length)
                return True

            def do_GET(self):
                if not self._host_ok():
                    return self._send(403)
                if self.path == "/":
                    return self._send(200, PAGE.encode("utf-8"),
                                      "text/html; charset=utf-8")
                if self.path == "/api/status":
                    if not self._authorized():
                        return self._send(401)
                    return self._json(200, build_status(server._backend))
                if self.path in ("/api/emergency", "/api/restore", "/api/stop"):
                    return self._send(405)
                self._send(404)

            def do_POST(self):
                if not self._host_ok():
                    return self._send(403)
                actions = {"/api/emergency": self._emergency,
                           "/api/restore": self._restore,
                           "/api/stop": self._stop}
                if self.path not in actions:
                    return self._send(405 if self.path in ("/", "/api/status") else 404)
                if not self._authorized():
                    return self._send(401)
                if not self._drain_body():
                    return self._send(413)
                self._json(200, {"message": actions[self.path]()})

            def _emergency(self):
                return str(server._backend.emergency())

            def _restore(self):
                return str(server._backend.restore_after_emergency())

            def _stop(self):
                server._backend.stop(wait=False)
                return "Stopping the stream."

            def do_PUT(self):
                self._send(405)

            do_DELETE = do_PATCH = do_PUT

        self._httpd = ThreadingHTTPServer((self._host, self._port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="lightstream-remote", daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(5)
        self._httpd = None
        self._thread = None


def bind_host(lan):
    """Loopback unless the user explicitly allowed the home network."""
    return LAN_HOST if lan is True else DEFAULT_HOST


def timeline_text(lines):
    """Text for the read-only timeline area."""
    return "\n".join(lines) if lines else TIMELINE_EMPTY


class RemoteSession:
    """Owns the optional RemoteServer for the GUI. sync() is called from the
    tkinter timer, so no extra threads are created here. The token lives only
    in the server object, never in prefs."""

    def __init__(self, backend, server_factory=RemoteServer):
        self._backend = backend
        self._factory = server_factory
        self._server = None

    @property
    def url(self):
        return self._server.url if self._server is not None else None

    def sync(self, running, enabled, lan):
        """Start while a stream runs and the remote is enabled; stop otherwise.
        Returns the current URL or None."""
        wanted = bool(running) and enabled is True
        if wanted and self._server is None:
            server = self._factory(self._backend, host=bind_host(lan))
            try:
                server.start()
            except OSError:
                return None
            self._server = server
        elif not wanted and self._server is not None:
            self.close()
        return self.url

    def close(self):
        if self._server is not None:
            self._server.stop()
            self._server = None
