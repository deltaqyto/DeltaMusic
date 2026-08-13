from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from protocol.timestamps import from_iso, to_iso


@dataclass(frozen=True)
class PeerPlaylist:
    """A playlist as a peer serves it, carrying its membership as track uuids."""

    uuid: str
    name: str
    created_at: datetime
    modified_at: datetime
    songs: list[str] = field(default_factory=list)
    """Position is the index, and a repeated uuid is a duplicate entry."""

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "metadata": self.metadata,
            "created_at": to_iso(self.created_at),
            "modified_at": to_iso(self.modified_at),
            "songs": list(self.songs),
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PeerPlaylist":
        return PeerPlaylist(
            uuid=raw["uuid"],
            name=raw["name"],
            metadata=raw.get("metadata") or {},
            created_at=from_iso(raw["created_at"]),
            modified_at=from_iso(raw["modified_at"]),
            songs=list(raw.get("songs") or []),
        )
