from dataclasses import dataclass


@dataclass(frozen=True)
class SongPatch:
    """A change the scanner wants made to an existing song."""

    song_id: int
    found_on_disk: bool
    location: str | None = None
    file_size: int | None = None
    duration: float | None = None
