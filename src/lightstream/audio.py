"""Noise suppression filter chains. No ML model ships with this project."""

import os

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
