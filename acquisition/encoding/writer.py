"""Writing captured audio to disk."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from ..errors import WriteError
from .formats import resolve

log = logging.getLogger(__name__)

# libsndfile string fields soundfile exposes. Anything else is skipped.
_TAG_FIELDS = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "date": "date",
    "genre": "genre",
    "comment": "comment",
    "tracknumber": "tracknumber",
}


@dataclass(frozen=True)
class WriteReport:
    path: Path
    bytes_written: int
    peak: float
    clipped_samples: int
    tags_written: bool


def _sf():
    try:
        import soundfile  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - environment dependent
        raise WriteError(
            "the 'soundfile' package is required to write audio "
            "(pip install soundfile)"
        ) from exc
    return soundfile


def _dither(audio: np.ndarray, bits: int) -> np.ndarray:
    """TPDF dither at 1 LSB of the target depth. Only really worth doing for 16-bit"""
    lsb = 1.0 / (1 << (bits - 1))
    rng = np.random.default_rng()
    noise = rng.random(audio.shape, dtype=np.float32) - rng.random(
        audio.shape, dtype=np.float32
    )
    return audio + noise.astype(np.float32) * lsb


def write_audio(
    audio: np.ndarray,
    path: os.PathLike | str,
    samplerate: int,
    *,
    container: str = "opus",
    subtype: Optional[str] = None,
    dither: bool = True,
    tags: Optional[Dict[str, str]] = None,
) -> WriteReport:
    """Write `audio` (frames, channels) float32 in [-1, 1] to `path`.

    Written to a sibling temp file and moved into place, so an interrupted write never leaves a half-written track where a complete one is expected.
    """
    if audio.ndim != 2:
        raise WriteError(f"expected a 2-D (frames, channels) array, got {audio.shape}")
    if audio.shape[0] == 0:
        raise WriteError("refusing to write an empty recording")
    if samplerate <= 0:
        raise WriteError(f"invalid samplerate: {samplerate}")

    sf = _sf()
    path = Path(path)
    try:
        encoding = resolve(container, subtype)
    except ValueError as exc:
        raise WriteError(str(exc)) from exc

    data = np.ascontiguousarray(audio, dtype=np.float32)
    if not np.all(np.isfinite(data)):
        bad = int(np.count_nonzero(~np.isfinite(data)))
        log.warning("%d non-finite samples replaced with silence", bad)
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    peak = float(np.max(np.abs(data))) if data.size else 0.0
    clipped = int(np.count_nonzero(np.abs(data) > 1.0))
    if clipped:
        log.warning("%d samples exceed full scale and will be clipped", clipped)
        data = np.clip(data, -1.0, 1.0)

    # A lossy encoder's own noise floor is far above one 16-bit LSB.
    if dither and not encoding.lossy and encoding.sf_subtype == "PCM_16":
        data = np.clip(_dither(data, 16), -1.0, 1.0)

    tmp = path.with_name(path.name + ".part")
    try:
        with sf.SoundFile(
            str(tmp),
            mode="w",
            samplerate=int(samplerate),
            channels=int(data.shape[1]),
            format=encoding.sf_format,
            subtype=encoding.sf_subtype,
        ) as handle:
            handle.write(data)
            tags_written = _apply_tags(handle, tags)
        size = tmp.stat().st_size
        os.replace(tmp, path)  # atomic within a volume, on Windows too
    except WriteError:
        _discard(tmp)
        raise
    except Exception as exc:
        _discard(tmp)
        raise WriteError(f"could not write {path}: {exc}") from exc

    return WriteReport(
        path=path,
        bytes_written=size,
        peak=peak,
        clipped_samples=clipped,
        tags_written=tags_written,
    )


def _apply_tags(handle, tags: Optional[Dict[str, str]]) -> bool:
    if not tags:
        return False
    written = False
    for key, value in tags.items():
        attr = _TAG_FIELDS.get(key.lower())
        if attr is None:
            continue
        try:
            setattr(handle, attr, value)
            written = True
        except Exception as exc:  # libsndfile refuses some fields per format
            log.debug("could not write tag %s: %s", attr, exc)
    return written


def _discard(tmp: Path) -> None:
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError as exc:  # pragma: no cover - best effort cleanup
        log.warning("could not remove temp file %s: %s", tmp, exc)
