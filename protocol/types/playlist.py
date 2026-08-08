from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from protocol.timestamps import from_iso, to_iso
from protocol.types.playlist_entry import PlaylistEntry


@dataclass(frozen=True)
class Playlist:
    id: int
    name: str
    created_at: datetime
    modified_at: datetime
    entries: list[PlaylistEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "metadata": self.metadata,
            "created_at": to_iso(self.created_at),
            "modified_at": to_iso(self.modified_at),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Playlist":
        return Playlist(
            id=raw["id"],
            name=raw["name"],
            metadata=raw.get("metadata") or {},
            created_at=from_iso(raw["created_at"]),
            modified_at=from_iso(raw["modified_at"]),
            entries=[PlaylistEntry.from_dict(entry) for entry in raw.get("entries", [])],
        )
