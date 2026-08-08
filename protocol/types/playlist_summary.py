from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from protocol.timestamps import from_iso, to_iso


@dataclass(frozen=True)
class PlaylistSummary:
    """A playlist as `list_playlists`"""

    id: int
    name: str
    created_at: datetime
    modified_at: datetime
    song_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "metadata": self.metadata,
            "created_at": to_iso(self.created_at),
            "modified_at": to_iso(self.modified_at),
            "song_count": self.song_count,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PlaylistSummary":
        return PlaylistSummary(
            id=raw["id"],
            name=raw["name"],
            metadata=raw.get("metadata") or {},
            created_at=from_iso(raw["created_at"]),
            modified_at=from_iso(raw["modified_at"]),
            song_count=raw["song_count"],
        )
