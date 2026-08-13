from dataclasses import dataclass, field
from typing import Any

from protocol.types.song import Song


@dataclass(frozen=True)
class PeerSong:
    """A song as a peer serves it."""

    uuid: str
    name: str
    artist: str
    duration: float
    file_size: int
    location: str | None
    available: bool
    """The sender's `found_on_disk`. False is a row the sender can describe and cannot serve bytes for."""

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "artist": self.artist,
            "duration": self.duration,
            "file_size": self.file_size,
            "location": self.location,
            "metadata": self.metadata,
            "available": self.available,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PeerSong":
        return PeerSong(
            uuid=raw["uuid"],
            name=raw["name"],
            artist=raw["artist"],
            duration=float(raw["duration"]),
            file_size=int(raw["file_size"]),
            location=raw.get("location"),
            metadata=raw.get("metadata") or {},
            available=bool(raw["available"]),
        )

    @staticmethod
    def from_song(song: Song) -> "PeerSong":
        return PeerSong(
            uuid=song.uuid,
            name=song.name,
            artist=song.artist,
            duration=song.duration,
            file_size=song.file_size,
            location=song.location,
            metadata=song.metadata,
            available=song.found_on_disk,
        )
