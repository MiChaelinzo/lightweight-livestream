"""Highlights: find loud, busy or sharply changing moments in a recording.

HEURISTIC. This module scores fixed time windows from three signals that
ffmpeg can measure: scene-change score, frame-to-frame motion (YDIF) and
audio loudness bursts (per 0.1 s RMS). It does not know what is happening in
the game. It does not detect boss fights, victories or kills, and machine
learning is out of scope. A "highlight" here only means "something got louder,
busier or changed fast", and the user must review the clips.

Scoring, peak picking and clip merging are pure and deterministic: the same
ffmpeg text always gives the same report. Running ffmpeg is a thin step on top
(analyze_file, cut_clip) that degrades to a plain message when ffmpeg or the
file is missing, as in audio_check.py.

Every signal is measured as an excess over the file's own typical level (the
median window), so a steadily busy or steadily loud recording does not score
high everywhere. Weights and ranges below are heuristics chosen for this
project, not a standard.

Clips made with -c copy start on a keyframe: ffmpeg snaps the start back to
the previous keyframe, so a copied clip can begin earlier than the report's
start time (by up to one keyframe interval). --vertical re-encodes and is
frame accurate.
"""

import json
import math
import os
import re
import subprocess
from collections import namedtuple

HEURISTIC_NOTICE = ("HEURISTIC: windows are ranked by scene change, motion and "
                    "loudness bursts only. No game events are detected; review "
                    "every clip.")
REPORT_VERSION = 1

WINDOW_SECONDS = 1.0
VIDEO_SAMPLE_FPS = 5          # frames analysed per second of video
ANALYSIS_WIDTH = 160          # frames are scaled to this width before analysis
AUDIO_RATE = 8000
AUDIO_STEP_SAMPLES = 800      # 0.1 s of audio per loudness reading
SILENCE_FLOOR_DB = -90.0      # stands in for -inf RMS

SCENE_WEIGHT = 0.4
MOTION_WEIGHT = 0.2
LOUDNESS_WEIGHT = 0.4
SCENE_FULL_SCORE = 0.3        # scene score at which the scene part is 1.0
MOTION_FULL_EXCESS = 20.0     # YDIF above the median that counts as 1.0
LOUDNESS_FULL_EXCESS_DB = 20.0  # dB above the median that counts as 1.0
MIN_SCORE = 0.05              # windows scoring at or below this are never picked

DEFAULT_TOP = 5
DEFAULT_CLIP_SECONDS = 30.0
DEFAULT_MIN_GAP_SECONDS = 20.0
VERTICAL_WIDTH = 1080
VERTICAL_HEIGHT = 1920
VERTICAL_CRF = "23"
BLUR_STRENGTH = 20
ANALYSIS_TIMEOUT_SECONDS = 3600
CUT_TIMEOUT_SECONDS = 1800

# Per-window signals, each already scaled to 0..1, and the combined score.
WindowScore = namedtuple("WindowScore", "index time scene motion loudness score")
Clip = namedtuple("Clip", "start length score")
Signals = namedtuple("Signals", "scene motion loudness")  # lists of (time, value)
StreamInfo = namedtuple("StreamInfo", "duration has_video has_audio")

_HEADER = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_VALUE = re.compile(r"^lavfi\.([\w.]+)=(-?(?:\d+(?:\.\d+)?|inf))\s*$")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_KEY_SCENE = "scene_score"
_KEY_MOTION = "signalstats.YDIF"
_KEY_LOUDNESS = "astats.Overall.RMS_level"


# -- parsing (pure) ----------------------------------------------------------
def parse_stream_info(text):
    """StreamInfo from the stderr of `ffmpeg -i FILE` (duration 0.0 if unknown)."""
    match = _DURATION.search(text)
    duration = 0.0
    if match:
        duration = (int(match.group(1)) * 3600 + int(match.group(2)) * 60
                    + float(match.group(3)))
    return StreamInfo(duration, bool(re.search(r"Stream #\S+: Video:", text)),
                      bool(re.search(r"Stream #\S+: Audio:", text)))


def parse_signals(text):
    """Signals from the metadata=print text (a `frame: pts_time:` header line
    followed by `lavfi.KEY=VALUE` lines). Unknown lines are ignored."""
    lists = {_KEY_SCENE: [], _KEY_MOTION: [], _KEY_LOUDNESS: []}
    current = None
    for line in text.splitlines():
        header = _HEADER.search(line)
        if line.startswith("frame:") and header:
            current = float(header.group(1))
            continue
        value = _VALUE.match(line)
        if value and current is not None and value.group(1) in lists:
            raw = value.group(2)
            number = SILENCE_FLOOR_DB if raw.endswith("inf") else float(raw)
            if value.group(1) == _KEY_LOUDNESS:
                number = max(number, SILENCE_FLOOR_DB)
            lists[value.group(1)].append((current, number))
    return Signals(lists[_KEY_SCENE], lists[_KEY_MOTION], lists[_KEY_LOUDNESS])


# -- scoring (pure) ----------------------------------------------------------
def _median(values):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _per_window(samples, count, window, reduce):
    buckets = [[] for _ in range(count)]
    for time, value in samples:
        index = int(time // window)
        if 0 <= index < count:
            buckets[index].append(value)
    return [reduce(b) if b else None for b in buckets]


def _mean(values):
    return sum(values) / len(values)


def _excess(values, full):
    """0..1 per window: how far each value is above the file's median value."""
    known = [v for v in values if v is not None]
    base = _median(known)
    return [0.0 if v is None else min(1.0, max(0.0, (v - base) / full))
            for v in values]


def score_windows(signals, duration, window=WINDOW_SECONDS):
    """One WindowScore per `window` seconds of the file. `time` is the
    window's centre in seconds."""
    if duration <= 0 or window <= 0:
        return []
    count = int(math.ceil(duration / window))
    scene = [0.0 if v is None else min(1.0, v / SCENE_FULL_SCORE)
             for v in _per_window(signals.scene, count, window, max)]
    motion = _excess(_per_window(signals.motion, count, window, _mean),
                     MOTION_FULL_EXCESS)
    loudness = _excess(_per_window(signals.loudness, count, window, max),
                       LOUDNESS_FULL_EXCESS_DB)
    scores = []
    for i in range(count):
        total = (SCENE_WEIGHT * scene[i] + MOTION_WEIGHT * motion[i]
                 + LOUDNESS_WEIGHT * loudness[i])
        scores.append(WindowScore(i, round((i + 0.5) * window, 3), scene[i],
                                  motion[i], loudness[i], total))
    return scores


def pick_peaks(scores, top, min_gap):
    """Best windows first: highest score, earlier window on ties. A window is
    skipped when its centre is closer than min_gap seconds to a picked one or
    when its score is at or below MIN_SCORE. At most `top` are returned."""
    ranked = sorted(scores, key=lambda s: (-s.score, s.index))
    picked = []
    for candidate in ranked:
        if len(picked) >= top or candidate.score <= MIN_SCORE:
            break
        if all(abs(candidate.time - p.time) >= min_gap for p in picked):
            picked.append(candidate)
    return picked


def clip_for_peak(peak, length, duration):
    """Clip centred on the peak, moved inside [0, duration]."""
    length = min(length, duration)
    start = min(max(0.0, peak.time - length / 2.0), max(0.0, duration - length))
    return Clip(round(start, 3), round(length, 3), peak.score)


def merge_clips(clips):
    """Merge clips that overlap in time into one longer clip that keeps the
    best score. Result is ordered by start time."""
    merged = []
    for clip in sorted(clips, key=lambda c: (c.start, c.length)):
        if merged and clip.start < merged[-1].start + merged[-1].length:
            last = merged[-1]
            end = max(last.start + last.length, clip.start + clip.length)
            merged[-1] = Clip(last.start, round(end - last.start, 3),
                              max(last.score, clip.score))
        else:
            merged.append(clip)
    return merged


def build_report(source_name, info, scores, peaks, clips, params):
    """JSON-ready report. `clips` is a list of dicts (start, length, score,
    file) or None when no clips were cut."""
    return {
        "report_version": REPORT_VERSION,
        "heuristic": HEURISTIC_NOTICE,
        "source": source_name,
        "duration_seconds": round(info.duration, 3),
        "has_video": info.has_video,
        "has_audio": info.has_audio,
        "parameters": dict(params),
        "windows_scored": len(scores),
        "peaks": [{
            "rank": rank,
            "time_seconds": peak.time,
            "score": round(peak.score, 3),
            "scene": round(peak.scene, 3),
            "motion": round(peak.motion, 3),
            "loudness": round(peak.loudness, 3),
        } for rank, peak in enumerate(peaks, 1)],
        "clips": [dict(c) for c in (clips or [])],
    }


# -- file names (pure) -------------------------------------------------------
def safe_stem(path):
    """File name without extension, reduced to letters, digits and . _ -."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "video"


def unique_path(directory, base, extension, exists=os.path.exists):
    """directory/base.ext, or base-2.ext, base-3.ext... so nothing is overwritten."""
    candidate = os.path.join(directory, base + extension)
    number = 2
    while exists(candidate):
        candidate = os.path.join(directory, "%s-%d%s" % (base, number, extension))
        number += 1
    return candidate


def default_out_dir(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)),
                        safe_stem(path) + "-highlights")


# -- ffmpeg commands ---------------------------------------------------------
def analysis_argv(ffmpeg, path, info):
    parts, maps = [], []
    if info.has_video:
        parts.append(
            "[0:v]fps=%d,scale=%d:-2,select=gte(scene\\,0),"
            "metadata=print:key=lavfi.%s:file=-,signalstats,"
            "metadata=print:key=lavfi.%s:file=-[v]"
            % (VIDEO_SAMPLE_FPS, ANALYSIS_WIDTH, _KEY_SCENE, _KEY_MOTION))
        maps += ["-map", "[v]", "-f", "null", "-"]
    if info.has_audio:
        parts.append(
            "[0:a]aresample=%d,asetnsamples=n=%d:p=0,astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.%s:file=-[a]"
            % (AUDIO_RATE, AUDIO_STEP_SAMPLES, _KEY_LOUDNESS))
        maps += ["-map", "[a]", "-f", "null", "-"]
    return [ffmpeg, "-hide_banner", "-nostats", "-i", path,
            "-filter_complex", ";".join(parts)] + maps


def _vertical_graph(blur):
    """(filter arguments, video map arguments) for the 1080x1920 centre crop,
    or a sharp centred picture over a blurred copy when blur is set."""
    size = "%d:%d" % (VERTICAL_WIDTH, VERTICAL_HEIGHT)
    fill = "scale=%s:force_original_aspect_ratio=increase,crop=%s" % (size, size)
    if not blur:
        return ["-vf", fill + ",setsar=1"], ["-map", "0:v"]
    graph = ("[0:v]split[a][b];[a]%s,boxblur=%d[bg];[b]scale=%d:-2[fg];"
             "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
             % (fill, BLUR_STRENGTH, VERTICAL_WIDTH))
    return ["-filter_complex", graph], ["-map", "[v]"]


def cut_argv(ffmpeg, path, clip, out_path, vertical=False, blur=False):
    """-n means ffmpeg refuses to overwrite even if the name was taken in between."""
    base = [ffmpeg, "-hide_banner", "-nostats", "-v", "error", "-n",
            "-ss", "%.3f" % clip.start, "-i", path, "-t", "%.3f" % clip.length]
    if not vertical:
        return base + ["-c", "copy", "-avoid_negative_ts", "make_zero", out_path]
    graph, video_map = _vertical_graph(blur)
    return (base + graph + video_map + ["-map", "0:a?"] +
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", VERTICAL_CRF,
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
             out_path])


# -- running ffmpeg ----------------------------------------------------------
def _require(ffmpeg, path):
    if not ffmpeg:
        raise ValueError("ffmpeg was not found. Install it or pass --ffmpeg PATH.")
    if not os.path.isfile(path):
        raise ValueError("File not found: %s" % path)


def _run(argv, timeout, run, capture_stdout=False):
    try:
        return run(argv, stdin=subprocess.DEVNULL,
                   stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Could not run ffmpeg: %s" % exc)


def _failure(result, path):
    text = result.stderr.decode("utf-8", "replace")
    tail = (text.strip().splitlines() or ["unknown error"])[-1]
    return ValueError("ffmpeg could not process %s: %s" % (path, tail))


def probe_file(ffmpeg, path, run=subprocess.run):
    """StreamInfo for a file. ffmpeg -i with no output exits 1; that is normal."""
    _require(ffmpeg, path)
    result = _run([ffmpeg, "-hide_banner", "-i", path], 60, run)
    info = parse_stream_info(result.stderr.decode("utf-8", "replace"))
    if not (info.has_video or info.has_audio) or info.duration <= 0:
        raise ValueError("ffmpeg found no playable audio or video in %s" % path)
    return info


def analyze_file(ffmpeg, path, info, run=subprocess.run):
    """Signals for a file (one ffmpeg pass; nothing is written)."""
    _require(ffmpeg, path)
    result = _run(analysis_argv(ffmpeg, path, info), ANALYSIS_TIMEOUT_SECONDS, run,
                  capture_stdout=True)
    if result.returncode != 0:
        raise _failure(result, path)
    return parse_signals(result.stdout.decode("utf-8", "replace"))


def cut_clip(ffmpeg, path, clip, out_path, vertical=False, blur=False,
             run=subprocess.run):
    result = _run(cut_argv(ffmpeg, path, clip, out_path, vertical, blur),
                  CUT_TIMEOUT_SECONDS, run)
    if result.returncode != 0:
        raise _failure(result, path)
    return out_path


def find_highlights(ffmpeg, path, top=DEFAULT_TOP, length=DEFAULT_CLIP_SECONDS,
                    min_gap=DEFAULT_MIN_GAP_SECONDS, out_dir=None, cut=True,
                    vertical=False, blur=False, probe=probe_file,
                    analyze=analyze_file, cutter=cut_clip):
    """Analyse, pick peaks, optionally cut clips, write the JSON report.
    Returns (report, report_path). Raises ValueError with a plain message."""
    for name, value in (("top", top), ("length", length), ("min-gap", min_gap)):
        if value <= 0:
            raise ValueError("--%s must be greater than 0" % name)
    info = probe(ffmpeg, path)
    scores = score_windows(analyze(ffmpeg, path, info), info.duration)
    peaks = pick_peaks(scores, top, min_gap)
    out_dir = out_dir or default_out_dir(path)
    stem = safe_stem(path)
    entries = []
    if peaks and cut:
        os.makedirs(out_dir, exist_ok=True)
        for rank, clip in enumerate(
                (clip_for_peak(p, length, info.duration) for p in peaks), 1):
            target = unique_path(out_dir, "%s-clip-%02d-%ds" % (
                stem, rank, int(clip.start)), ".mp4")
            cutter(ffmpeg, path, clip, target, vertical, blur)
            entries.append({"start_seconds": clip.start, "length_seconds": clip.length,
                            "score": round(clip.score, 3),
                            "file": os.path.basename(target),
                            "mode": "vertical-1080x1920" if vertical else "copy"})
    params = {"top": top, "clip_length_seconds": length, "min_gap_seconds": min_gap,
              "window_seconds": WINDOW_SECONDS, "vertical": bool(vertical),
              "blurred_background": bool(blur)}
    report = build_report(os.path.basename(path), info, scores, peaks,
                          entries if cut else None, params)
    os.makedirs(out_dir, exist_ok=True)
    report_path = unique_path(out_dir, stem + "-highlights", ".json")
    with open(report_path, "x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    return report, report_path


def report_lines(report, report_path):
    lines = [report["heuristic"], "Source: %s (%.1f s)" % (
        report["source"], report["duration_seconds"])]
    if not report["peaks"]:
        lines.append("No window stood out from the rest of the file.")
    for peak in report["peaks"]:
        lines.append("  #%d at %.1f s  score %.2f (scene %.2f, motion %.2f, loudness %.2f)"
                     % (peak["rank"], peak["time_seconds"], peak["score"],
                        peak["scene"], peak["motion"], peak["loudness"]))
    for clip in report["clips"]:
        lines.append("  clip %s  from %.1f s, %.1f s long (%s)" % (
            clip["file"], clip["start_seconds"], clip["length_seconds"], clip["mode"]))
    if any(c["mode"] == "copy" for c in report["clips"]):
        lines.append("Copied clips start on a keyframe, so they can begin a little "
                     "before the time shown. Use --vertical for exact cuts.")
    lines.append("Report: %s" % report_path)
    return lines


# -- dashboard (pure formatting + small readers) ------------------------------
MEDIA_EXTENSIONS = (".mkv", ".mp4", ".flv", ".ts", ".mov", ".webm")
CLIP_DIR_SUFFIX = "-highlights"
RECENT_SESSIONS = 5
RECENT_FILES = 10
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")
_SIZE_STEP = 1024.0


def human_size(num_bytes):
    value = float(num_bytes)
    for unit in _SIZE_UNITS[:-1]:
        if value < _SIZE_STEP:
            return "%.0f %s" % (value, unit) if unit == "B" else "%.1f %s" % (value, unit)
        value /= _SIZE_STEP
    return "%.1f %s" % (value, _SIZE_UNITS[-1])


def list_media(directory):
    """[(name, bytes)] for media files directly in directory, newest name last
    in sort order. Missing or unreadable folders give []."""
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    found = []
    for name in names:
        full = os.path.join(directory, name)
        if name.lower().endswith(MEDIA_EXTENSIONS) and os.path.isfile(full):
            found.append((name, os.path.getsize(full)))
    return found


def list_clips(directory):
    """[(relative name, bytes)] for media inside NAME-highlights subfolders."""
    try:
        subdirs = sorted(n for n in os.listdir(directory)
                         if n.endswith(CLIP_DIR_SUFFIX)
                         and os.path.isdir(os.path.join(directory, n)))
    except OSError:
        return []
    return [(os.path.join(sub, name), size) for sub in subdirs
            for name, size in list_media(os.path.join(directory, sub))]


def _file_block(title, rows):
    if not rows:
        return [title + ": none"]
    lines = ["%s: %d file(s), %s" % (title, len(rows),
                                     human_size(sum(s for _, s in rows)))]
    lines += ["  %s  %s" % (name, human_size(size)) for name, size in rows[-RECENT_FILES:]]
    return lines


def dashboard_lines(history, recordings, clips, recordings_dir, disk):
    """One-page text summary. history: rows from analytics.history_entry,
    disk: (free_bytes, total_bytes) or None."""
    lines = ["LightStream creator dashboard (local files only, nothing is uploaded)",
             ""]
    if history:
        lines.append("Recent sessions (newest last):")
        for row in history[-RECENT_SESSIONS:]:
            lines.append("  %s  preset %s  health %s  dropped %s  reconnects %s" % (
                row.get("date", "?"), row.get("preset") or "?",
                row.get("health_score", "?"), row.get("dropped_frames", "?"),
                row.get("reconnect_count", "?")))
    else:
        lines.append("Recent sessions: none (history is opt-in with --analytics)")
    lines += [""] + _file_block("Recordings in %s" % recordings_dir, recordings)
    lines += [""] + _file_block("Highlight clips", clips)
    lines.append("")
    if disk:
        lines.append("Free disk space: %s of %s" % (human_size(disk[0]),
                                                    human_size(disk[1])))
    else:
        lines.append("Free disk space: unknown")
    return lines
