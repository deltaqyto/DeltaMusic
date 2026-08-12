from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScannedFile:
    location: str
    """Relative to the library root, posix separators. Matches SongRow.location."""

    path: Path
    file_size: int
    uuid: str | None
    """What the file's tags say it is, read on the walk."""
