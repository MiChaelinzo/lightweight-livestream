"""Audio check: clipping and loudness from ffmpeg's own analysis filters.

The parser is pure and deterministic: the same ffmpeg text always gives the
same AudioCheck. Running ffmpeg is a thin step on top (analyze_file) that
degrades to a plain message when ffmpeg or the file is missing.

Filters used: volumedetect (max_volume, histogram_0db) and ebur128 (integrated
loudness, true peak). Nothing here changes the audio.

Thresholds are heuristics chosen for this project, not a broadcast standard:
CLIP_PEAK_DBFS marks a peak close enough to full scale to risk clipping, and
the loudness bounds only say "much louder / quieter than most streams".
FFmpeg has no echo canceller, so this module cannot detect or remove echo.
"""

import os
import re
import subprocess
from collections import namedtuple

CLIP_PEAK_DBFS = -1.0
LOUD_ABOVE_LUFS = -12.0
QUIET_BELOW_LUFS = -24.0
ANALYSIS_TIMEOUT_SECONDS = 600

LOUDNESS_LOUD = "loud"
LOUDNESS_QUIET = "quiet"
LOUDNESS_OK = "ok"

# peak_dbfs / integrated_lufs / true_peak_dbfs are None when ffmpeg did not
# report them (for example silence reports -inf). clipped_samples counts
# samples at 0 dB from volumedetect and is None when not reported.
AudioCheck = namedtuple(
    "AudioCheck", "peak_dbfs clipped_samples integrated_lufs true_peak_dbfs")

_NUMBER = r"(-?(?:\d+(?:\.\d+)?|inf))"
_MAX_VOLUME = re.compile(r"max_volume:\s*" + _NUMBER + r"\s*dB")
_HIST_0DB = re.compile(r"histogram_0db:\s*(\d+)")
_INTEGRATED = re.compile(r"\bI:\s+" + _NUMBER + r"\s+LUFS")
_TRUE_PEAK = re.compile(r"\bPeak:\s+" + _NUMBER + r"\s+dBFS")
_SUMMARY_MARK = "Summary:"


def _number(text):
    if text is None or text.endswith("inf"):
        return None
    return float(text)


def _last(pattern, text):
    found = pattern.findall(text)
    return found[-1] if found else None


def parse_analysis(text):
    """AudioCheck from the stderr text of volumedetect plus ebur128."""
    summary = text.rsplit(_SUMMARY_MARK, 1)[1] if _SUMMARY_MARK in text else ""
    hist = _last(_HIST_0DB, text)
    return AudioCheck(
        peak_dbfs=_number(_last(_MAX_VOLUME, text)),
        clipped_samples=None if hist is None else int(hist),
        integrated_lufs=_number(_last(_INTEGRATED, summary)),
        true_peak_dbfs=_number(_last(_TRUE_PEAK, summary)))


def is_clipping(check):
    """True when the file has samples at full scale or a peak at or above
    CLIP_PEAK_DBFS. Unknown values never count as clipping."""
    if check.clipped_samples:
        return True
    return check.peak_dbfs is not None and check.peak_dbfs >= CLIP_PEAK_DBFS


def loudness_class(check):
    """loud, quiet, ok, or None when no loudness was measured."""
    if check.integrated_lufs is None:
        return None
    if check.integrated_lufs > LOUD_ABOVE_LUFS:
        return LOUDNESS_LOUD
    if check.integrated_lufs < QUIET_BELOW_LUFS:
        return LOUDNESS_QUIET
    return LOUDNESS_OK


def check_lines(check):
    """Plain report lines for the CLI."""
    lines = []
    if check.peak_dbfs is None:
        lines.append("Peak level: not measured (silence or no audio)")
    else:
        lines.append("Peak level: %.1f dBFS" % check.peak_dbfs)
    if check.clipped_samples is not None:
        lines.append("Samples at full scale: %d" % check.clipped_samples)
    if check.integrated_lufs is not None:
        lines.append("Integrated loudness: %.1f LUFS" % check.integrated_lufs)
    if check.true_peak_dbfs is not None:
        lines.append("True peak: %.1f dBFS" % check.true_peak_dbfs)
    if is_clipping(check):
        lines.append("Clipping: YES. Lower the microphone or input gain, or use "
                     "an audio profile with a limiter.")
    else:
        lines.append("Clipping: no")
    kind = loudness_class(check)
    if kind == LOUDNESS_LOUD:
        lines.append("Loudness: loud (above %.0f LUFS). Consider lowering the gain."
                     % LOUD_ABOVE_LUFS)
    elif kind == LOUDNESS_QUIET:
        lines.append("Loudness: quiet (below %.0f LUFS). Consider the autogain "
                     "option or raising the input." % QUIET_BELOW_LUFS)
    elif kind == LOUDNESS_OK:
        lines.append("Loudness: in a normal range for speech")
    lines.append("Echo is not checked: FFmpeg cannot detect or remove echo. "
                 "Use headphones or a microphone with echo cancellation.")
    return lines


def analysis_argv(ffmpeg, path):
    return [ffmpeg, "-hide_banner", "-nostats", "-i", path, "-vn",
            "-af", "volumedetect,ebur128=peak=true", "-f", "null", "-"]


def analyze_file(ffmpeg, path, run=subprocess.run):
    """AudioCheck for a file. Raises ValueError with a plain message when
    ffmpeg is missing, the file is missing, or ffmpeg fails."""
    if not ffmpeg:
        raise ValueError("ffmpeg was not found. Install it or pass --ffmpeg PATH.")
    if not os.path.isfile(path):
        raise ValueError("Audio file not found: %s" % path)
    try:
        result = run(analysis_argv(ffmpeg, path), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                     timeout=ANALYSIS_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Could not run ffmpeg: %s" % exc)
    text = result.stderr.decode("utf-8", "replace")
    if result.returncode != 0:
        tail = (text.strip().splitlines() or ["unknown error"])[-1]
        raise ValueError("ffmpeg could not analyze %s: %s" % (path, tail))
    return parse_analysis(text)
