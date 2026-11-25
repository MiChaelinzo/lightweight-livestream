"""Noise suppression filter chains. No ML model ships with this project."""

import os
from collections import namedtuple

from .filtergraph import filter_path

NOISE_LEVELS = ("off", "light", "ai")

# Mechanism only: a rumble cut plus FFmpeg's built-in FFT denoiser. No model file.
LIGHT_CHAIN = "highpass=f=80,afftdn=nr=10:nf=-45"


def noise_filter_args(level, model_path=None):
    """Extra ffmpeg args for the audio filter. 'ai' uses arnndn with a
    user-supplied RNNoise .rnnn model (see README for the download step)."""
    if level == "off":
        return []
    if level == "light":
        return ["-af", LIGHT_CHAIN]
    if level == "ai":
        if not model_path:
            raise ValueError("noise 'ai' needs noise_model: the path to an .rnnn file")
        return ["-af", "arnndn=m=" + filter_path(model_path, "noise_model")]
    raise ValueError("Unknown noise level %r. Choose one of: %s"
                     % (level, ", ".join(NOISE_LEVELS)))


def require_model_file(model_path, isfile=os.path.isfile):
    """Raise a clear error when the model file is not on disk."""
    if not model_path or not isfile(model_path):
        raise ValueError(
            "Noise model file not found: %r. Download an RNNoise .rnnn model "
            "yourself and point noise_model at it." % (model_path,))


# -- audio profiles ----------------------------------------------------------
# Built only from FFmpeg filters (highpass, afftdn, acompressor, equalizer,
# alimiter). "light" is the cheaper chain for weak PCs; "full" adds the
# denoiser and tone shaping. Cost notes are mechanisms (afftdn runs an FFT per
# block, the others are simple per-sample filters), not measured numbers.
AudioProfile = namedtuple("AudioProfile", "name light full description cost_note")

CHAIN_LIGHT = "light"
CHAIN_FULL = "full"
AUDIO_CHAINS = (CHAIN_LIGHT, CHAIN_FULL)

_COMPRESSOR = "acompressor=threshold=-18dB:ratio=3:attack=10:release=200"
_VOICE_COMPRESSOR = "acompressor=threshold=-20dB:ratio=3:attack=20:release=250"

AUDIO_PROFILES = {
    p.name: p
    for p in (
        AudioProfile(
            "gaming", "highpass=f=100,alimiter=limit=0.9",
            "highpass=f=100,afftdn=nr=8:nf=-45,%s,alimiter=limit=0.9" % _COMPRESSOR,
            "Voice over game sound: rumble cut, steady level, peaks limited.",
            "light: two simple filters. full: adds afftdn (FFT denoiser) and a compressor."),
        AudioProfile(
            "podcast", "highpass=f=80,%s" % _VOICE_COMPRESSOR,
            "highpass=f=80,afftdn=nr=10:nf=-45,%s,equalizer=f=3000:t=q:w=1:g=2,"
            "alimiter=limit=0.95" % _VOICE_COMPRESSOR,
            "Spoken voice: even level, a little presence, clean background.",
            "light: highpass and compressor. full: adds afftdn, an equalizer band and a limiter."),
        AudioProfile(
            "music", "alimiter=limit=0.95",
            "highpass=f=30,equalizer=f=60:t=q:w=1:g=1,alimiter=limit=0.95",
            "Music: no denoiser and no compressor, only a gentle low-end lift and a limiter.",
            "light: a limiter only. full: highpass, one equalizer band and a limiter."),
        AudioProfile(
            "commentary", "highpass=f=90,%s" % _VOICE_COMPRESSOR,
            "highpass=f=90,afftdn=nr=10:nf=-45,%s,equalizer=f=3500:t=q:w=1:g=2,"
            "alimiter=limit=0.92" % _VOICE_COMPRESSOR,
            "Talking over video: clear voice that stays above the content.",
            "light: highpass and compressor. full: adds afftdn, an equalizer band and a limiter."),
        AudioProfile(
            "asmr", "highpass=f=40,afftdn=nr=6:nf=-50",
            "highpass=f=40,afftdn=nr=6:nf=-50,equalizer=f=8000:t=q:w=1:g=2,"
            "alimiter=limit=0.97",
            "Quiet detail: gentle denoise, no compressor so soft sounds stay soft.",
            "light: highpass and afftdn. full: adds one equalizer band and a limiter."),
    )
}


def get_audio_profile(name):
    try:
        return AUDIO_PROFILES[name]
    except KeyError:
        raise ValueError("Unknown audio profile %r. Choose one of: %s"
                         % (name, ", ".join(AUDIO_PROFILES)))


def audio_profile_chain(name, chain=CHAIN_FULL):
    """The -af filter chain string for an audio profile at the given cost level."""
    if chain not in AUDIO_CHAINS:
        raise ValueError("Unknown audio chain %r. Choose one of: %s"
                         % (chain, ", ".join(AUDIO_CHAINS)))
    profile = get_audio_profile(name)
    return profile.light if chain == CHAIN_LIGHT else profile.full
