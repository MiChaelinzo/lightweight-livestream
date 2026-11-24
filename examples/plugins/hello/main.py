"""Example plugin: answers the handshake and logs two events.

Protocol: docs/architecture/PLUGIN-PROTOCOL.md. One JSON object per line.
"""

import json
import sys


def send(action, **fields):
    message = {"v": 1, "action": action}
    message.update(fields)
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        event = json.loads(line)
    except ValueError:
        continue
    name = event.get("event")
    if name == "hello":
        send("ready")
    elif name == "stream_started":
        send("log", text="stream started on %s" % event.get("platform", "?"))
    elif name == "health":
        send("log", text="fps %s" % event.get("fps"))
    elif name == "shutdown":
        break
