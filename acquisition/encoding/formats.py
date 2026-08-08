"""Output format selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..errors import WriteError

# Opus is defined only at these rates.
OPUS_RATES = (8000, 12000, 16000, 24000, 48000)

LOSSLESS_CONTAINERS = ("wav", "flac")
LOSSY_CONTAINERS = ("ogg", "opus", "mp3")


@dataclass(frozen=True)
class Encoding:
    container: str
    sf_format: str
    sf_subtype: str
    extension: str
    lossy: bool

    def __str__(self) -> str:  # pragma: no cover
        kind = "lossy" if self.lossy else "lossless"
        return f"{self.container} ({self.sf_format}/{self.sf_subtype}, {kind})"


# container -> (sf format, fixed subtype or None if the caller chooses)
_CONTAINERS: Dict[str, Tuple[str, Optional[str], str]] = {
    "wav": ("WAV", None, "wav"),
    "flac": ("FLAC", None, "flac"),
    "ogg": ("OGG", "VORBIS", "ogg"),
    "opus": ("OGG", "OPUS", "opus"),
    "mp3": ("MP3", "MPEG_LAYER_III", "mp3"),
}

_SUBTYPES = {
    "wav": ("PCM_16", "PCM_24", "PCM_32", "FLOAT"),
    "flac": ("PCM_16", "PCM_24"),
}


def containers() -> Tuple[str, ...]:
    return tuple(_CONTAINERS)


def is_lossy(container: str) -> bool:
    return container.strip().lstrip(".").lower() in LOSSY_CONTAINERS


def resolve(container: str, subtype: Optional[str] = None) -> Encoding:
    """Map a container name to a libsndfile encoding.

    For lossy containers the subtype is implied, and one passed alongside is ignored.
    """
    key = (container or "").strip().lstrip(".").lower()
    if key not in _CONTAINERS:
        raise ValueError(
            f"unknown container {container!r}; choose from {', '.join(_CONTAINERS)}"
        )

    sf_format, fixed_subtype, extension = _CONTAINERS[key]
    if fixed_subtype is not None:
        return Encoding(key, sf_format, fixed_subtype, extension, lossy=True)

    allowed = _SUBTYPES[key]
    chosen = (subtype or allowed[0]).upper()
    if chosen not in allowed:
        raise ValueError(
            f"{key} cannot store subtype {chosen!r}; choose from {', '.join(allowed)}"
        )
    return Encoding(key, sf_format, chosen, extension, lossy=False)


def validate(encoding: Encoding, samplerate: int, channels: int) -> None:
    """Check an encoding can actually be written on this machine. Called once at startup, with the samplerate the device settled on."""
    if encoding.sf_subtype == "OPUS" and samplerate not in OPUS_RATES:
        raise WriteError(
            f"Opus cannot encode {samplerate} Hz - it supports only "
            f"{', '.join(str(rate) for rate in OPUS_RATES)} Hz. Either set the "
            f"device to 48000 Hz, set samplerate in the config, or use the 'ogg' "
            f"container, which takes any rate."
        )
    if encoding.sf_format == "MP3" and channels > 2:
        raise WriteError(f"MP3 cannot store {channels} channels")

    try:
        import soundfile as sf
    except Exception as exc:
        raise WriteError(
            "the 'soundfile' package is required to write audio "
            "(pip install soundfile)"
        ) from exc

    if not sf.check_format(encoding.sf_format, encoding.sf_subtype):
        available = ", ".join(sorted(sf.available_subtypes(encoding.sf_format)))
        raise WriteError(
            f"this build of libsndfile cannot write "
            f"{encoding.sf_format}/{encoding.sf_subtype}. It offers: {available}. "
            f"Upgrade soundfile, or pick another container."
        )
