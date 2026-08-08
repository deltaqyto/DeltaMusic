"""Turning a capture into a tagged file on disk.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..types import CaptureResult, TrackMetadata
from .naming import DEFAULT_TEMPLATE, extension_for, resolve_destination
from .writer import write_audio

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingResult:
    path: Path
    metadata: TrackMetadata
    duration_seconds: float
    samplerate: int
    channels: int
    requested_offset_ms: float
    granted_offset_ms: float
    trimmed_ms: float
    peak: float
    clipped_samples: int
    xruns: int
    bytes_written: int
    tags_written: bool

    @property
    def offset_shortfall_ms(self) -> float:
        """Pre-roll the buffer could not supply."""
        return max(0.0, self.requested_offset_ms - self.granted_offset_ms)


def save_capture(
    capture: CaptureResult,
    metadata: TrackMetadata,
    destination: os.PathLike | str,
    *,
    container: str = "opus",
    subtype: Optional[str] = None,
    filename_template: str = DEFAULT_TEMPLATE,
    overwrite: bool = False,
    create_dirs: bool = True,
    dither: bool = True,
) -> RecordingResult:
    """Write a capture to disk and return what happened.

    `destination` is a directory to save into or an explicit file path.
    `filename_template` takes `{title}`, `{artist}`, `{album}`, `{album_artist}`, `{track_number}`, `{year}` and `{genre}`.
    """
    if destination is None:
        raise ValueError("destination is required")
    container = container.lstrip(".").lower()

    path = resolve_destination(
        destination,
        metadata,
        extension_for(container, subtype),
        template=filename_template,
        overwrite=overwrite,
        create_dirs=create_dirs,
    )
    report = write_audio(
        capture.audio,
        path,
        capture.samplerate,
        container=container,
        subtype=subtype,
        dither=dither,
        tags=metadata.as_tags(),
    )

    if capture.xruns:
        log.warning(
            "%d stream dropout(s) occurred during capture. Audio may have gaps",
            capture.xruns,
        )
    log.debug("wrote %.2fs to %s", capture.duration_seconds, report.path)

    return RecordingResult(
        path=report.path,
        metadata=metadata,
        duration_seconds=capture.duration_seconds,
        samplerate=capture.samplerate,
        channels=capture.channels,
        requested_offset_ms=capture.requested_offset_ms,
        granted_offset_ms=capture.granted_offset_ms,
        trimmed_ms=capture.trimmed_ms,
        peak=report.peak,
        clipped_samples=report.clipped_samples,
        xruns=capture.xruns,
        bytes_written=report.bytes_written,
        tags_written=report.tags_written,
    )
