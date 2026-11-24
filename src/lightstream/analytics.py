"""Opt-in session reports: one small JSON file per session in reports/.

Off unless the user turns it on (--analytics, "analytics": true in config.json,
or the GUI checkbox). A report holds numbers and the encoder name only. It
never holds the stream key, the stream URL or file paths. Nothing is sent
anywhere; the file stays on disk. Unit tests cover the report content; the
numbers themselves are only as good as ffmpeg's own progress lines (UNVERIFIED
against a real stream here).
"""

import json
import os
import time

from .config import config_path
from .fileio import create_private_text, write_private_text

REPORTS_DIRNAME = "reports"
REPORT_VERSION = 1
FLOAT_DIGITS = 3


def analytics_enabled(cli_flag, file_cfg):
    """Opt-in only: True when asked on the command line or in the config file."""
    return bool(cli_flag) or file_cfg.get("analytics") is True


def reports_dir(os_name=None, environ=None, root=None):
    """reports/ next to config.json (inside the app folder in portable mode)."""
    return os.path.join(os.path.dirname(config_path(os_name, environ, root)),
                        REPORTS_DIRNAME)


def _rounded(value):
    return None if value is None else round(value, FLOAT_DIGITS)


def build_session_report(summary, encoder, duration_seconds, recording,
                         preset=None, hardware_profile=None, now=None):
    """Report dict from HealthTracker.summary(). Only these fields, by design.

    recording: True when a local copy was written. recording_seconds then
    equals the session length, which is an approximation: the file starts
    with the first connection and each reconnect starts a numbered new file.
    """
    stamp = now or time.localtime()
    return {
        "report_version": REPORT_VERSION,
        "date": time.strftime("%Y-%m-%d", stamp),
        "encoder": encoder,
        "preset": preset,
        "hardware_profile": hardware_profile,
        "session_seconds": _rounded(duration_seconds),
        "avg_speed": _rounded(summary.get("avg_speed")),
        "avg_bitrate_kbps": _rounded(summary.get("avg_bitrate_kbps")),
        "dropped_frames": summary.get("dropped_frames", 0),
        "reconnect_count": summary.get("reconnects", 0),
        "recording_seconds": _rounded(duration_seconds) if recording else 0,
    }


def report_path(directory, now=None):
    """reports/session-YYYYMMDD.json; a second session that day gets -2, -3."""
    day = time.strftime("%Y%m%d", now or time.localtime())
    candidate = os.path.join(directory, "session-%s.json" % day)
    number = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "session-%s-%d.json" % (day, number))
        number += 1
    return candidate


def write_session_report(directory, report, now=None):
    """Write the report as indented JSON and return its path."""
    os.makedirs(directory, exist_ok=True)
    path = report_path(directory, now)
    # never overwrite an earlier report
    create_private_text(path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


# -- opt-in local history ----------------------------------------------------
HISTORY_FILENAME = "history.json"
HISTORY_LIMIT = 30   # newest sessions kept; older ones are dropped


def history_entry(summary, bottleneck=None, preset=None, now=None):
    """One compact history row. Numbers and class names only: no key, URL,
    path or audience data."""
    return {
        "date": time.strftime("%Y-%m-%d", now or time.localtime()),
        "preset": preset,
        "bottleneck": bottleneck,
        "avg_speed": _rounded(summary.get("avg_speed")),
        "dropped_frames": summary.get("dropped_frames", 0),
        "reconnect_count": summary.get("reconnects", 0),
    }


def load_history(directory):
    """Saved history rows, or [] when missing or unreadable."""
    try:
        with open(os.path.join(directory, HISTORY_FILENAME), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def append_history(directory, entry, limit=HISTORY_LIMIT):
    """Add entry, keep the newest `limit` rows, return the path."""
    rows = (load_history(directory) + [entry])[-limit:]
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, HISTORY_FILENAME)
    write_private_text(path, json.dumps(rows, indent=2, sort_keys=True) + "\n")
    return path


# -- opt-in support bundle ---------------------------------------------------
BUNDLE_VERSION = 1
BUNDLE_FILENAME = "support-bundle.json"
REDACTED = "****"
# Config keys whose values are dropped outright. Any key containing one of the
# SECRET_NAME_PARTS is dropped too; any string holding "://" is a stream address.
ADDRESS_KEYS = ("url", "backup_url")
SECRET_NAME_PARTS = ("key", "token", "secret", "password")


def redact_config(cfg):
    """Copy of a config dict with stream keys and addresses hidden.

    Addresses (and anything URL-shaped) can carry a key, so they become
    "****" when set. Secret-looking names are hidden whatever their value.
    Other values are kept: they are settings, not secrets.
    """
    out = {}
    for name, value in sorted(cfg.items()):
        lowered = str(name).lower()
        url_shaped = isinstance(value, str) and "://" in value
        secret_named = any(part in lowered for part in SECRET_NAME_PARTS)
        if (name in ADDRESS_KEYS or secret_named or url_shaped) and value not in (None, ""):
            out[name] = REDACTED
        else:
            out[name] = value
    return out


def build_support_bundle(version, platform_name, encoders, cfg, history,
                         known_secrets=()):
    """Plain dict a person can attach to a bug report. Opt-in: only built when
    asked for. Holds the version, platform, an encoder summary, the redacted
    config and recent history rows (numbers only). known_secrets (for example
    a key from the environment) are scrubbed from the finished text as well.
    """
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "version": version,
        "platform": platform_name,
        "encoders": sorted(encoders),
        "config": redact_config(cfg),
        "recent_history": list(history),
    }
    text = json.dumps(bundle, indent=2, sort_keys=True)
    for secret in known_secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return json.loads(text)


def write_support_bundle(path, bundle):
    """Write the bundle as indented JSON (owner-only file) and return the path."""
    write_private_text(path, json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return path
