"""Typed data models for future multi-device viewing. Data only: nothing here
opens a socket, starts a server or is called by the streaming path.

They exist so the shapes are agreed before any viewer, relay or browser page is
built (see docs/architecture/MULTI-DEVICE.md). Every kind below is a plan
(UNVERIFIED, not implemented). Models never hold a stream key.
"""

from typing import NamedTuple, Optional

VIEWER_KINDS = ("lan_preview", "tablet", "mobile", "browser")
TRANSPORTS = ("srt", "udp", "hls", "webrtc")
RELAY_ROLES = ("self_hosted", "third_party")
LAN_TRANSPORTS = ("srt", "udp")   # the only ones the current ffmpeg build can output (FEAT-003)


class ViewerEndpoint(NamedTuple):
    """Where one viewer device receives a preview. host is an address on the
    local network for lan_preview, otherwise a relay address."""
    kind: str
    transport: str
    host: str
    port: int
    label: str = ""


class RelayConfig(NamedTuple):
    """A relay that would fan one stream out to several viewers. The relay
    address is public data; credentials are never stored in this model."""
    role: str
    endpoint: ViewerEndpoint
    max_viewers: int = 1
    note: Optional[str] = None


def validate_endpoint(endpoint):
    """The endpoint, or ValueError saying what is wrong."""
    if endpoint.kind not in VIEWER_KINDS:
        raise ValueError("viewer kind must be one of %s, got %r"
                         % (", ".join(VIEWER_KINDS), endpoint.kind))
    if endpoint.transport not in TRANSPORTS:
        raise ValueError("transport must be one of %s, got %r"
                         % (", ".join(TRANSPORTS), endpoint.transport))
    if endpoint.kind == "lan_preview" and endpoint.transport not in LAN_TRANSPORTS:
        raise ValueError("LAN preview can use only %s" % " or ".join(LAN_TRANSPORTS))
    if not endpoint.host or "://" in endpoint.host or "/" in endpoint.host:
        raise ValueError("host must be a bare host name or address (no scheme or path)")
    if not 1 <= endpoint.port <= 65535:
        raise ValueError("port must be 1 to 65535, got %r" % endpoint.port)
    return endpoint


def validate_relay(relay):
    """The relay, or ValueError saying what is wrong."""
    if relay.role not in RELAY_ROLES:
        raise ValueError("relay role must be one of %s, got %r"
                         % (", ".join(RELAY_ROLES), relay.role))
    if relay.max_viewers < 1:
        raise ValueError("max_viewers must be at least 1")
    validate_endpoint(relay.endpoint)
    return relay
