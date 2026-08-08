"""The values that cross the backend seam. Nothing here may import from backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    import numpy as np

_MAX_TAG_LEN = 512


def _clean(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string, got {type(value).__name__}")
    # Strip control characters - they survive into tags and break parsers.
    value = "".join(ch for ch in value if ch == "\t" or ord(ch) >= 0x20)
    value = value.strip()
    if len(value) > _MAX_TAG_LEN:
        value = value[:_MAX_TAG_LEN].rstrip()
    return value or None


@dataclass(frozen=True)
class TrackMetadata:
    """Metadata for a captured track. `artist` and `title` drive the default filename.
    The rest is written into the file's tags where a writer is available."""

    artist: str
    title: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    track_number: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    comment: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        artist = _clean(self.artist, "artist")
        title = _clean(self.title, "title")
        if not artist:
            raise ValueError("artist must be a non-empty string")
        if not title:
            raise ValueError("title must be a non-empty string")
        object.__setattr__(self, "artist", artist)
        object.__setattr__(self, "title", title)
        for name in ("album", "album_artist", "genre", "comment"):
            object.__setattr__(self, name, _clean(getattr(self, name), name))

        if self.track_number is not None:
            if not isinstance(self.track_number, int) or not 0 < self.track_number < 10000:
                raise ValueError("track_number must be an int in 1..9999")
        if self.year is not None:
            if not isinstance(self.year, int) or not 1000 <= self.year <= 9999:
                raise ValueError("year must be a 4-digit int")

        cleaned_extra: Dict[str, str] = {}
        for key, value in dict(self.extra).items():
            key_c = _clean(str(key), "extra key")
            value_c = _clean(str(value), f"extra[{key}]")
            if key_c and value_c:
                cleaned_extra[key_c] = value_c
        object.__setattr__(self, "extra", cleaned_extra)

    def as_tags(self) -> Dict[str, str]:
        """Flatten to the generic tag names used by the writers."""
        tags: Dict[str, str] = {"artist": self.artist, "title": self.title}
        if self.album:
            tags["album"] = self.album
        if self.album_artist:
            tags["albumartist"] = self.album_artist
        if self.track_number is not None:
            tags["tracknumber"] = str(self.track_number)
        if self.year is not None:
            tags["date"] = str(self.year)
        if self.genre:
            tags["genre"] = self.genre
        if self.comment:
            tags["comment"] = self.comment
        tags.update(self.extra)
        return tags


@dataclass(frozen=True)
class TrackInfo:
    """One observation of what a player is doing.

    ``last_updated`` must be the instant the platform last refreshed `position` since - effective_position extrapolates from it.
    """

    title: str
    artist: str
    is_playing: bool
    duration: timedelta
    position: timedelta
    last_updated: datetime
    observed_at: datetime

    @property
    def key(self) -> tuple:
        return self.title, self.artist

    @property
    def is_identified(self) -> bool:
        """False for the blank properties a session reports mid-transition."""
        return bool(self.title.strip())

    def effective_position(self, now: Optional[datetime] = None) -> timedelta:
        """Extrapolate the play position from the last platform update.

        Sessions typically refresh position only on play, pause, seek and track change, so the reported value is stale by up to a poll interval.
        Extrapolate to determine it with higher accuracy for trimming audio.
        """
        position = self.position
        if self.is_playing:
            position += (now or datetime.now(timezone.utc)) - self.last_updated
        if position < timedelta(0):
            return timedelta(0)
        if timedelta(0) < self.duration < position:
            return self.duration
        return position

    def remaining(self, now: Optional[datetime] = None) -> timedelta:
        """Time left in the track, by extrapolated position."""
        if self.duration <= timedelta(0):
            return timedelta(0)
        return self.duration - self.effective_position(now)

    def __str__(self) -> str:  # pragma: no cover
        state = "playing" if self.is_playing else "paused"
        return f"[{state}] {self.artist} - {self.title}"


@dataclass
class CaptureResult:
    """Raw audio and what is known about it. Not frozen: the saver may release `audio`."""

    audio: "np.ndarray"
    samplerate: int
    channels: int
    duration_seconds: float
    requested_offset_ms: float
    granted_offset_ms: float
    trimmed_ms: float
    started_at: float
    stopped_at: float
    xruns: int
    truncated: bool

    @property
    def offset_shortfall_ms(self) -> float:
        """How much of the requested pre-roll the buffer could not supply."""
        return max(0.0, self.requested_offset_ms - self.granted_offset_ms)


@dataclass(frozen=True)
class SourceInfo:
    """What an AudioSource opened, for logging."""

    name: str
    backend: str
    samplerate: int
    channels: int
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover
        detail = f" ({self.detail})" if self.detail else ""
        return f"{self.name}{detail} at {self.samplerate} Hz, {self.channels} ch"
