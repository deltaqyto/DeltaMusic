"""Checks run on raw audio after a capture closes, before it is worth saving."""

from __future__ import annotations

import numpy as np

# Long enough that the zero crossings of ordinary tracks never fill one.
_BLOCK_MS = 20.0


def silent_fraction(audio: "np.ndarray", samplerate: int, threshold: float) -> float:
    """Share of the capture whose peak amplitude stays below `threshold`, measured over short blocks because every waveform crosses zero and a per-sample count would call any recording mostly silent."""
    if audio is None or audio.size == 0 or samplerate <= 0:
        return 1.0

    peaks = np.abs(audio)
    if peaks.ndim > 1:
        peaks = peaks.max(axis=1)

    block = max(1, int(round(samplerate * _BLOCK_MS / 1000.0)))
    usable = peaks.shape[0] - peaks.shape[0] % block
    if usable == 0:
        return float(peaks.max() < threshold)

    blocks = peaks[:usable].reshape(-1, block).max(axis=1)
    return float(np.count_nonzero(blocks < threshold) / blocks.shape[0])
