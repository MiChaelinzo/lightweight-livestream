"""Logic behind the beginner GUI. No tkinter here, so it is testable headlessly.

The stream key lives only in memory: it is never written to the preferences
file and it is redacted from the log shown on screen.
"""

import collections
import json
import os
import threading
import time

from .autoscale import AutoScaleSession, AutoScaler, build_ladder, top_step
from .command import (build_command, numbered_recording_path,
                      prepare_recording_path)
from .fileio import write_private_text
from .portable import data_dir, find_ffmpeg
from .config import config_path, detect_os, effective_preset_name, resolve_settings
from .config import scenes_path
from .encoders import choose_working_encoder, probe_encoders
from .adaptive import AdaptiveAdvisor
from .analytics import (CRASH_DIRNAME, append_history, build_crash_report,
                        write_crash_report, build_session_report, history_entry,
                        performance_snapshot, reports_dir, save_performance_snapshot,
                        write_session_report)
from .health import HealthTracker
from .network import KIND_RTMP, detect_congestion, output_kind
from .optimizer import (OptimizerContext, bottleneck_of, build_insights, health_line,
                        insight_line, session_health)
from .command import publisher_command
from .platforms import ingest_url
from .guardian import Guardian, SurvivalMonitor
from .timeline import Timeline
from .emergency import (POTATO_STREAM_PROFILES, emergency_settings, failover_settings,
                        potato_stream_settings)
from .perf_profiles import affinity_cpus
from .telemetry import TelemetrySampler
from .scenes import load_scenes
from .presets import DEFAULT_PRESET
from .runner import (STATUS_FAILOVER, STATUS_FALLBACK, STATUS_FAILED, STATUS_LIVE,
                     STATUS_RECONNECTING, STATUS_RESTARTING, STATUS_STARTING,
                     STATUS_STOPPED,
                     free_udp_port, is_lagging, redact, run_with_publisher,
                     run_with_reconnect)

MAX_QUICK_FAILURES = 5
TEST_FILENAME = "lightstream-test.mkv"
RECORDINGS_DIRNAME = "recordings"
NO_SCENE_LABEL = "Just my screen"
LOG_LINES = 200
STOP_JOIN_SECONDS = 10
MIN_SUBSTRING_KEY_LENGTH = 8
PREFS_FILENAME = "gui.json"
PREF_FIELDS = ("platform", "url", "preset", "fps", "bitrate", "window",
               "audio_device", "keep_trying", "mute", "scene", "record",
               "hardware", "noise", "analytics", "profile", "audio_profile",
               "auto_scale", "backup_url", "record_format", "rate_mode",
               "potato", "potato_grayscale", "potato_skip_static",
               "persistent_ingest", "guardian", "auto_survival",
               "remote")

# Recording and Potato Stream choices: (label shown, stored value).
RECORD_FORMAT_CHOICES = (("MKV (safest if the PC crashes)", "mkv"),
                         ("MP4 (fragmented, plays everywhere)", "mp4"))
RATE_MODE_CHOICES = (("Variable bitrate (default)", "vbr"),
                     ("Constant bitrate (software x264 only)", "cbr"))
POTATO_CHOICES = (("Off", ""), ("Potato Stream 2000 kbps", "2000"),
                  ("Potato Stream 4000 kbps", "4000"))

# (label shown to the user, value used internally)
PLATFORM_CHOICES = (("Twitch", "twitch"), ("YouTube", "youtube"),
                    ("Facebook Live", "facebook"),
                    ("Other site", "custom"))
STRENGTH_CHOICES = (
    ("Very old PC (potato)", "potato"),
    ("Old PC (light)", "light"),
    ("Normal PC (balanced)", "balanced"),
    ("Strong PC (720p60)", "720p60"),
)

# Banner states: (text, color name), plain words for beginners.
BANNER_OFFLINE = ("Offline. Press START when you are ready.", "grey")
BANNER_STARTING = ("Starting... please wait.", "orange")
BANNER_LIVE = ("YOU ARE LIVE!", "green")
BANNER_LAGGING = ("LIVE, but your PC is struggling. Try a weaker setting.",
                  "orange")
BANNER_RECONNECTING = ("Connection lost. Trying again...", "orange")
BANNER_FAILOVER = ("Main server keeps failing. Switching to your backup server...",
                   "orange")
BANNER_EMERGENCY = ("LIVE in EMERGENCY mode (lowest quality). Press Restore to go "
                    "back.", "orange")
BANNER_PROBLEM = ("Problem. Could not stream. See 'What is wrong?'", "red")

HELP_TEXT = {
    "no_key": "Step 2 is empty. Copy your stream key from your streaming "
              "website and paste it in the box.",
    "no_url": "You picked 'Other site'. Type the address it gave you, "
              "starting with rtmp://",
    "no_ffmpeg": "FFmpeg is missing. It is the free program that sends your "
                 "screen. Install it, then press 'Check my PC'.",
    "failed": "The stream stopped again and again. Check that your key is "
              "right and your internet works. Try 'Normal' or a weaker PC "
              "setting.",
}


def suggest_strength(cpu_count):
    """Preset name for a PC with this many CPU threads (None means unknown)."""
    if not cpu_count or cpu_count <= 2:
        return "potato"
    if cpu_count <= 4:
        return DEFAULT_PRESET
    if cpu_count <= 8:
        return "balanced"
    return "720p60"


def label_for(choices, value):
    for label, val in choices:
        if val == value:
            return label
    return choices[0][0]


def value_for(choices, label):
    for lab, val in choices:
        if lab == label:
            return val
    return choices[0][1]


def banner_for(state, detail=None):
    """(text, color) for a runner status."""
    if state in (STATUS_STARTING, STATUS_FALLBACK, STATUS_RESTARTING):
        return BANNER_STARTING
    if state == STATUS_LIVE:
        return BANNER_LAGGING if is_lagging(detail or {}) else BANNER_LIVE
    if state == STATUS_RECONNECTING:
        return BANNER_RECONNECTING
    if state == STATUS_FAILOVER:
        return BANNER_FAILOVER
    if state == STATUS_FAILED:
        return BANNER_PROBLEM
    return BANNER_OFFLINE


def prefs_path(os_name=None):
    return os.path.join(os.path.dirname(config_path(os_name)), PREFS_FILENAME)


def _contains_key(value, key):
    """Short keys could match innocent text ("1" in "30"), so below
    MIN_SUBSTRING_KEY_LENGTH only a whole-value match counts."""
    if not key:
        return False
    text = str(value)
    if len(key) < MIN_SUBSTRING_KEY_LENGTH:
        return text == key
    return key in text


def report_gui_crash(error, key="", directory=None, os_name=None):
    """Save a local, redacted crash report for an uncaught GUI callback error.

    Same module and rules as the CLI: the file stays on this PC, and addresses
    and the current stream key are replaced by "****". A key shorter than
    MIN_SUBSTRING_KEY_LENGTH is not scrubbed as a substring because it would
    mask innocent text. Returns a short friendly message for the status line.
    Never raises, so the handler cannot take the window down.
    """
    from . import __version__
    name = type(error).__name__
    secrets = (os.environ.get("STREAM_KEY"),)
    if key and len(key) >= MIN_SUBSTRING_KEY_LENGTH:
        secrets += (key,)
    try:
        os_name = os_name or detect_os()
        report = build_crash_report(error, __version__, os_name, known_secrets=secrets)
        directory = directory or os.path.join(
            os.path.dirname(config_path(os_name)), CRASH_DIRNAME)
        path = write_crash_report(directory, report)
    except Exception as exc:
        return ("Something went wrong (%s). The crash report could not be saved (%s)."
                % (name, type(exc).__name__))
    return ("Something went wrong (%s). A crash report was saved to %s. It stays on "
            "this PC and is never sent anywhere; check it before sharing."
            % (name, path))


def save_prefs(path, prefs, key=""):
    """Write only whitelisted fields, and never any value containing the key.

    The key check covers a user pasting a full rtmp://.../KEY address into the
    "Other site" box.
    """
    safe = {k: prefs[k] for k in PREF_FIELDS if k in prefs
            and not _contains_key(prefs[k], key)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_private_text(path, json.dumps(safe, indent=2) + "\n")


def load_prefs(path):
    """Saved choices, or {} when missing or unreadable (never crash the GUI)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in PREF_FIELDS if k in data}


def validate(prefs, key, ffmpeg, test_local=False):
    """Friendly error text for the first problem found, else None."""
    if not test_local and not (key or "").strip():
        return HELP_TEXT["no_key"]
    if prefs.get("platform") == "custom" and not (prefs.get("url") or "").strip():
        return HELP_TEXT["no_url"]
    if not ffmpeg:
        return HELP_TEXT["no_ffmpeg"]
    return None


PERSISTENT_BACKUP_CONFLICT = (
    "Persistent ingest cannot be combined with a backup server address. "
    "Turn one of them off.")
def persistent_requested(prefs, test_local=False):
    """True when the opt-in persistent ingest checkbox applies to this run."""
    return prefs.get("persistent_ingest") is True and not test_local


def persistent_conflict(prefs, test_local=False):
    """Plain message when persistent ingest is on together with a backup
    address (same rule as the command line), else None."""
    if persistent_requested(prefs, test_local) and _blank_to_none(prefs.get("backup_url")):
        return PERSISTENT_BACKUP_CONFLICT
    return None


def scene_choices(path=None):
    """Scene names for the dropdown, always starting with 'no scene'.

    A missing or broken scenes file just gives no extra choices; 'lightstream
    scenes validate' explains the problem."""
    try:
        names = list(load_scenes(path or scenes_path()))
    except (OSError, ValueError):
        names = []
    return [NO_SCENE_LABEL] + names


def one_click_setup(os_name=None, platform="twitch", upload_mbps=None,
                    cpu_count=None, ram_mb=None, gpu_text=None, facts=None):
    """Safe settings for this PC as (fields, plain-words message).

    fields uses the same names as the saved preferences. Nothing is written
    here and no stream key is involved."""
    from . import bandwidth, wizard  # lazy: wizard imports this module
    from .hardware import detect_gpu_names
    os_name = os_name or detect_os()
    if gpu_text is None:
        gpu_text = "\n".join(detect_gpu_names(os_name))
    cpu_count = cpu_count if cpu_count is not None else (os.cpu_count() or 0)
    ram_mb = ram_mb if ram_mb is not None else wizard.detect_ram_mb(os_name)
    upload_kbps = bandwidth.mbps_to_kbps(upload_mbps) if upload_mbps else None
    config = wizard.build_recommended_config(gpu_text, cpu_count, ram_mb,
                                             upload_kbps, platform)
    fields = {"preset": config["preset"], "hardware": config["hardware"],
              "noise": config["noise"], "bitrate": config.get("bitrate", "")}
    message = "Done. PC type: %s. Strength: %s." % (
        config["hardware"].replace("_", " "), label_for(STRENGTH_CHOICES, config["preset"]))
    if config.get("bitrate"):
        message += " Video speed set to %d kbps for your internet." % config["bitrate"]
    if facts is None:  # probes ffmpeg briefly, like the Check button
        facts = wizard.gather_readiness_facts(os_name, cpu_count, ram_mb, upload_kbps)
    message += " Stream readiness: %d/100 (run 'lightstream readiness' for details)." % (
        wizard.readiness_report(facts).score)
    return fields, message


def optimize_proposal(os_name=None, platform="twitch", upload_mbps=None,
                      cpu_count=None, ram_mb=None, gpu_text=None, facts=None,
                      tier=None, current=None):
    """One-click optimize for the GUI: (OptimizeProposal, plain-words message).

    Proposes only. The window must ask the person and then call
    apply_optimization; nothing is written here."""
    from . import bandwidth, wizard  # lazy: wizard imports this module
    from .hardware import detect_gpu_names
    os_name = os_name or detect_os()
    if gpu_text is None:
        gpu_text = "\n".join(detect_gpu_names(os_name))
    cpu_count = cpu_count if cpu_count is not None else (os.cpu_count() or 0)
    ram_mb = ram_mb if ram_mb is not None else wizard.detect_ram_mb(os_name)
    upload_kbps = bandwidth.mbps_to_kbps(upload_mbps) if upload_mbps else None
    if facts is None:
        facts = wizard.gather_readiness_facts(os_name, cpu_count, ram_mb, upload_kbps)
    if current is None:
        from .config import load_file_config
        current = load_file_config(config_path(os_name))
    proposal = wizard.propose_optimization(current, gpu_text, cpu_count, ram_mb,
                                           upload_kbps, platform, facts, tier)
    lines = ["%s: %s -> %s" % d for d in proposal.diff] or ["no changes"]
    return proposal, "\n".join(proposal.notes + lines)


def apply_optimization(proposal, os_name=None, path=None):
    """Write a confirmed proposal to config.json. Call only after the person says yes."""
    from . import wizard
    wizard.save_config(path or config_path(os_name or detect_os()), proposal.config)


def _blank_to_none(value):
    value = (value or "").strip() if isinstance(value, str) else value
    return value or None


def recording_path(now=None, record_format="mkv"):
    """Timestamped file in the app data folder, one per session. Anything but
    mp4 falls back to mkv (webm is not offered, see ROADMAP)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", now or time.localtime())
    ext = "mp4" if record_format == "mp4" else "mkv"
    return os.path.join(data_dir(), RECORDINGS_DIRNAME, "lightstream-%s.%s" % (stamp, ext))


def cli_values_from_prefs(prefs, display=None):
    """The resolve_settings 'command line' dict for GUI fields.

    A chosen performance profile supplies the strength (preset) too, so the
    Strength dropdown is not passed in that case. Explicit fps and bitrate
    boxes still win over the profile."""
    profile = _blank_to_none(prefs.get("profile"))
    return {
        "platform": prefs.get("platform"),
        "url": _blank_to_none(prefs.get("url")),
        "preset": None if profile else prefs.get("preset"),
        "profile": profile,
        "audio_profile": _blank_to_none(prefs.get("audio_profile")),
        "fps": _blank_to_none(prefs.get("fps")),
        "bitrate": _blank_to_none(prefs.get("bitrate")),
        "window": _blank_to_none(prefs.get("window")),
        "audio_device": _blank_to_none(prefs.get("audio_device")),
        "mute": bool(prefs.get("mute")) or None,
        "scene": _blank_to_none(prefs.get("scene")),
        "record": (recording_path(record_format=prefs.get("record_format"))
                   if prefs.get("record") else False),
        "rate_mode": _blank_to_none(prefs.get("rate_mode")),
        "hardware": _blank_to_none(prefs.get("hardware")),
        "backup_url": _blank_to_none(prefs.get("backup_url")),
        "noise": _blank_to_none(prefs.get("noise")),
        "display": display,
    }


def settings_from_prefs(prefs, display=None, cpu_count=None):
    """StreamSettings from GUI fields. Raises ValueError with plain words."""
    try:
        settings = resolve_settings(cli_values_from_prefs(prefs, display), {}, cpu_count)
        potato = _blank_to_none(prefs.get("potato"))
        if potato:
            if int(potato) not in POTATO_STREAM_PROFILES:
                raise ValueError("unknown Potato Stream choice %r" % potato)
            settings = potato_stream_settings(
                settings, int(potato), bool(prefs.get("potato_grayscale")),
                bool(prefs.get("potato_skip_static")))
        return settings
    except ValueError as exc:
        raise ValueError("One of your settings looks wrong (%s). Leave "
                         "Advanced boxes empty if unsure." % exc)


class StreamController:
    """Runs one stream in a background thread and exposes status to the GUI.

    The GUI only calls start/stop and reads snapshot() from its timer, so no
    tkinter object is ever touched from the worker thread.
    """

    def __init__(self, runner=run_with_reconnect, which=lambda _name: find_ffmpeg(),
                 os_name=None, display=None, probe=probe_encoders,
                 pick_encoder=choose_working_encoder, clock=time.monotonic,
                 report_dir=None, sampler=None):
        self._runner = runner
        self._which = which
        self._os_name = os_name or detect_os()
        self._display = display
        self._probe = probe
        self._pick_encoder = pick_encoder
        self._clock = clock
        self._report_dir = report_dir
        self._analytics = False
        self._preset_name = None
        self._lock = threading.Lock()
        self._log = collections.deque(maxlen=LOG_LINES)
        self._banner = BANNER_OFFLINE
        self._help = ""
        self._thread = None
        self._stop = None
        self._restart = None
        self._key = ""
        self._health = HealthTracker()
        self._advisor = AdaptiveAdvisor()
        self._sampler = sampler or TelemetrySampler(self._os_name)
        self._scale = None
        self._before_emergency = None
        self._context = OptimizerContext()
        self._ingest_kind = KIND_RTMP
        self._persistent = False
        self._timeline = None

    # -- state for the GUI -------------------------------------------------
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self):
        """(banner_text, color, help_text, log_text, running)."""
        with self._lock:
            text, color = self._banner
            return (text, color, self._help, "".join(self._log),
                    self.is_running())

    # -- worker callbacks (called from the worker thread) -------------------
    def _write(self, text):
        with self._lock:
            self._log.append(redact(text, self._key))

    def _write_locked(self, text):
        """Log write for callers that already hold self._lock (deque append is
        atomic, and the lock is not re-entrant)."""
        self._log.append(redact(text, self._key))

    def health_advice(self):
        """One plain-words line of advice, or '' when nothing looks wrong."""
        with self._lock:
            return " ".join(self._health.diagnose())

    def health_summary(self):
        """Running health numbers for the dashboard cards."""
        with self._lock:
            return self._health.summary()

    def recommendations(self):
        """Suggestions (list of adaptive.Recommendation). The GUI shows them;
        only the user decides whether to change a setting."""
        with self._lock:
            return self._advisor.recommendations()

    def insights(self):
        """Explained suggestions (list of optimizer.Insight), most confident first."""
        with self._lock:
            context = self._context
            if self._scale is not None:
                current = self._scale.current_settings
                context = context._replace(video_kbps=current.video_kbps, fps=current.fps)
            summary = self._health.summary()
            congestion = detect_congestion(
                summary, context.video_kbps, self._ingest_kind,
                getattr(self._sampler.latest, "cpu_percent", None))
            return build_insights(self._advisor, summary,
                                  list(self._sampler.history),
                                  self._health.network_stability(), context,
                                  congestion=congestion)

    def health_line(self):
        """'Health: 82/100 (Good)' from live readings (heuristic, see optimizer)."""
        with self._lock:
            health = session_health(self._health.summary(), self._sampler.latest,
                                    self._health.network_stability())
        return health_line(health)

    def comparison_lines(self):
        """Plain lines comparing the last two saved sessions (opt-in history)."""
        from .analytics import comparison_lines, load_history
        return comparison_lines(load_history(
            self._report_dir or reports_dir(self._os_name)))

    def performance_snapshot(self):
        """Numbers-only snapshot for the support bundle (opt-in sessions only)."""
        with self._lock:
            summary = self._health.summary()
            sample = self._sampler.latest
            health = session_health(summary, sample, self._health.network_stability())
        return performance_snapshot(summary, sample, health)

    def insight_lines(self):
        """Plain-words insight lines with confidence, for the dashboard."""
        return [insight_line(i) for i in self.insights()]

    def _on_status(self, state, detail):
        if state == STATUS_LIVE:
            self._sampler.tick_if_due()  # outside the lock: nvidia-smi can block
        with self._lock:
            self._health.on_status(state, detail)
            self._advisor.on_status(state, detail)
            if self._scale is not None:
                self._scale.on_status(state, detail)
            self._banner = (BANNER_EMERGENCY if self._before_emergency is not None
                            and state == STATUS_LIVE and not is_lagging(detail or {})
                            else banner_for(state, detail))
            if state == STATUS_FAILED:
                self._help = HELP_TEXT["failed"]
            elif state == STATUS_LIVE:
                self._help = ""

    def _on_publisher_status(self, state, detail):
        """Publisher thread: a drop counts as a reconnect, giving up fails."""
        if state in (STATUS_RECONNECTING, STATUS_FAILED):
            self._on_status(state, detail)

    class _LogSink:
        def __init__(self, write):
            self.write = write

    # -- actions ------------------------------------------------------------
    def start(self, prefs, key, test_local=False):
        """Begin streaming, or with test_local record a short file instead
        (no key needed, nothing goes live). Returns None or an error message."""
        if self.is_running():
            return "You are already streaming."
        ffmpeg = self._which("ffmpeg")
        problem = validate(prefs, key, ffmpeg, test_local)
        if problem:
            with self._lock:
                self._help = problem
            return problem
        try:
            settings = settings_from_prefs(prefs, self._display)
            cli_values = cli_values_from_prefs(prefs, self._display)
        except ValueError as exc:
            with self._lock:
                self._help = str(exc)
            return str(exc)
        conflict = persistent_conflict(prefs, test_local)
        if conflict:
            with self._lock:
                self._help = conflict
            return conflict
        persistent = persistent_requested(prefs, test_local)
        if persistent:
            settings = settings._replace(local_ingest_port=free_udp_port())
        key = key.strip() or "test"
        self._key = key
        with self._lock:
            self._health = HealthTracker(target_kbps=settings.video_kbps)
            self._preset_name = effective_preset_name(
                cli_values, {}, _blank_to_none(prefs.get("hardware")))
            self._advisor = AdaptiveAdvisor(
                self._preset_name, settings.video_kbps, settings.fps)
            self._stop = threading.Event()
            self._restart = threading.Event()
            guardian_on = prefs.get("guardian") is True and not test_local  # opt-in only
            survival_on = prefs.get("auto_survival") is True and not test_local
            enabled = ((prefs.get("auto_scale") is True or guardian_on)
                       and not test_local)  # opt-in only
            guardian = (Guardian(settings.video_kbps, self._clock)
                        if guardian_on else None)
            self._timeline = (Timeline(self._clock) if (enabled or survival_on)
                              else None)
            self._scale = AutoScaleSession(
                settings, self._advisor,
                AutoScaler(build_ladder(top_step(settings), constant_size=persistent),
                           self._clock, enabled=enabled),
                self._restart, self._write_locked, self._sampler,
                gaming_first=bool(settings.reserved_cores),
                monitors=(self._health, self._advisor) + ((guardian,) if guardian else ()),
                guardian=guardian,
                survival=(SurvivalMonitor(self._clock, enabled=True)
                          if survival_on else None),
                timeline=self._timeline)
            self._context = OptimizerContext(self._preset_name, settings.video_kbps,
                                             settings.fps, None, settings.noise)
            self._ingest_kind = output_kind(
                ingest_url(settings.platform, "x", settings.custom_url))
            self._analytics = prefs.get("analytics") is True  # opt-in only
            self._help = ""
            self._before_emergency = None
            self._persistent = persistent
            self._banner = BANNER_STARTING
            self._log.clear()
        keep_trying = bool(prefs.get("keep_trying"))
        self._thread = threading.Thread(
            target=self._work, args=(settings, key, ffmpeg, keep_trying,
                  TEST_FILENAME if test_local else None),
            daemon=True)
        self._thread.start()
        return None

    def _work(self, settings, key, ffmpeg, keep_trying, record_path=None):
        started = self._clock()
        encoder = None
        try:
            try:
                available = self._probe(ffmpeg)
            except RuntimeError as exc:
                self._write("Warning: %s. Using libx264.\n" % exc)
                available = set()
            encoder = self._pick_encoder(ffmpeg, available)
            self._write("Encoder: %s\n" % encoder)
            if settings.record_to and not record_path:
                prepare_recording_path(settings.record_to)
                self._write("Recording a copy to %s\n" % settings.record_to)
            self._context = self._context._replace(encoder=encoder)
            argv = build_command(settings, key, self._os_name, encoder, ffmpeg,
                                 record_path)
            scale = self._scale
            auto_scale = scale.scaler.enabled

            def attempt_settings(attempt):
                current = scale.current_settings
                if current.record_to:  # a new file per attempt, footage never truncated
                    current = current._replace(
                        record_to=numbered_recording_path(current.record_to, attempt))
                return current

            def run_encoder():
                return self._runner(
                    argv, key, self._os_name,
                    max_failures=(1 if record_path else
                                  None if keep_trying else MAX_QUICK_FAILURES),
                    stop=self._stop, on_status=self._on_status, encoder=encoder,
                    out=self._LogSink(self._write),
                    cpu_affinity=affinity_cpus(os.cpu_count() or 1, settings.reserved_cores),
                    restart=self._restart,
                    argv_factory=lambda enc: build_command(
                        scale.current_settings, key, self._os_name, enc, ffmpeg, record_path),
                    argv_for_attempt=(None if record_path else
                                      lambda n, enc: build_command(
                                          attempt_settings(n), key, self._os_name, enc,
                                          ffmpeg)),
                    backup_argv_for_attempt=(
                        lambda n, enc: build_command(
                            failover_settings(attempt_settings(n)), key, self._os_name,
                            enc, ffmpeg))
                    if settings.backup_url and not record_path else None)

            if self._persistent and not record_path:
                self._write("Persistent ingest (opt in): the connection stays up "
                            "while the encoder restarts. The picture size stays fixed.\n")
                run_with_publisher(
                    publisher_command(settings.local_ingest_port,
                                      ingest_url(settings.platform, key,
                                                 settings.custom_url), ffmpeg),
                    key, self._os_name, run_encoder, out=self._LogSink(self._write),
                    on_publisher_status=self._on_publisher_status,
                    max_failures=None if keep_trying else MAX_QUICK_FAILURES,
                    encoder_stop=self._stop)
            else:
                run_encoder()
        except (OSError, ValueError) as exc:
            self._write("Could not start: %s\n" % exc)
            self._on_status(STATUS_FAILED, None)
        finally:
            self._key = ""
            if self._timeline is not None:
                for line in self._timeline.report_lines():
                    self._write(line + "\n")
            self._save_report(settings, encoder, self._clock() - started, record_path)

    def _save_report(self, settings, encoder, seconds, test_file):
        """Opt-in session report; failures go to the log, never crash the worker."""
        with self._lock:
            summary = self._health.summary()
        if not self._analytics or test_file or not (summary["samples"] or summary["reconnects"]):
            return
        try:
            directory = self._report_dir or reports_dir(self._os_name)
            insights = self.insights()
            with self._lock:
                health = session_health(summary, self._sampler.latest,
                                        self._health.network_stability())
            append_history(directory, history_entry(
                summary, bottleneck_of(insights), self._preset_name,
                health_score=health.score))
            save_performance_snapshot(directory, performance_snapshot(
                summary, self._sampler.latest, health))
            path = write_session_report(
                directory,
                build_session_report(summary, encoder, seconds, bool(settings.record_to),
                                     preset=self._preset_name,
                                     hardware_profile=settings.hardware_profile))
            self._write("Session report saved to %s (no stream key inside)\n" % path)
        except OSError as exc:
            self._write("Could not save the session report: %s\n" % exc)

    def emergency(self):
        """Switch the running stream to the safest settings. Pressing the
        button is the opt-in: ffmpeg restarts briefly through the runner's
        restart event, auto-scale is paused so it cannot undo the step, and
        the previous settings are kept for restore_after_emergency().
        Returns a plain-words message."""
        with self._lock:
            if not self.is_running() or self._scale is None:
                return "Emergency mode works while you are streaming."
            if self._scale.in_survival:
                return "Auto-survival is already on."
            if self._before_emergency is not None:
                return "Emergency mode is already on."
            scale = self._scale
            self._before_emergency = (scale.current_settings, scale.scaler.enabled)
            # Persistent ingest keeps the picture size, so it gets the constant-size variant.
            scale.current_settings = emergency_settings(
                scale.current_settings, constant_size=self._persistent)
            scale.scaler.enabled = False
            scale.manual_hold = True
            if self._timeline is not None:
                self._timeline.record("emergency", "Emergency button pressed")
            self._retarget(scale.current_settings)
            self._write_locked("Emergency mode: lowest quality settings. "
                               "Restarting ffmpeg (a brief interruption).\n")
            scale.restart.set()
        return "Emergency mode is on. Press Restore to go back."

    def restore_after_emergency(self):
        """Undo emergency(): previous settings and auto-scale choice return."""
        with self._lock:
            if self._before_emergency is None or self._scale is None:
                return "Emergency mode is not on."
            scale = self._scale
            settings, enabled = self._before_emergency
            self._before_emergency = None
            scale.current_settings = settings
            scale.scaler.enabled = enabled
            scale.manual_hold = False
            if self._timeline is not None:
                self._timeline.record("config change", "Restore button pressed")
            self._retarget(settings)
            self._write_locked("Restored your previous settings. Restarting "
                               "ffmpeg (a brief interruption).\n")
            scale.restart.set()
        return "Your previous settings are back."

    def emergency_active(self):
        with self._lock:
            return self._before_emergency is not None

    def timeline_lines(self):
        """Plain-words event lines for the remote page, [] when the timeline
        is off. The timeline never holds the stream key."""
        with self._lock:
            if self._timeline is None:
                return []
            return list(self._timeline.report_lines())

    def _retarget(self, settings):
        for monitor in self._scale.monitors:
            monitor.retarget(settings.video_kbps, settings.fps)

    def stop(self, wait=True):
        """Stop the stream. wait=False returns at once (for the GUI thread);
        the status poll then sees running turn False."""
        if self._stop is not None:
            self._stop.set()
        thread = self._thread
        if not wait:
            return
        if thread is not None:
            thread.join(STOP_JOIN_SECONDS)
        if not self.is_running():
            self._on_status(STATUS_STOPPED, None)
