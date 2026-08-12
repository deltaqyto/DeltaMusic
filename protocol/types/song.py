from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from protocol.timestamps import from_iso, to_iso


@dataclass(frozen=True)
class Song:
    id: int
    uuid: str
    name: str
    artist: str
    duration: float
    file_size: int
    location: str | None
    found_on_disk: bool
    added_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    last_played_at: datetime | None = None
    play_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "name": self.name,
            "artist": self.artist,
            "duration": self.duration,
            "file_size": self.file_size,
            "location": self.location,
            "found_on_disk": self.found_on_disk,
            "metadata": self.metadata,
            "added_at": to_iso(self.added_at),
            "last_played_at": to_iso(self.last_played_at),
            "play_count": self.play_count,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Song":
        return Song(
            id=raw["id"],
            uuid=raw["uuid"],
            name=raw["name"],
            artist=raw["artist"],
            duration=raw["duration"],
            file_size=raw["file_size"],
            location=raw.get("location"),
            found_on_disk=raw["found_on_disk"],
            metadata=raw.get("metadata") or {},
            added_at=from_iso(raw["added_at"]),
            last_played_at=from_iso(raw.get("last_played_at")),
            play_count=raw.get("play_count", 0),
        )
