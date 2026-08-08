from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlaylistEntry:
    entry_id: int
    song_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"entry_id": self.entry_id, "song_id": self.song_id}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PlaylistEntry":
        return PlaylistEntry(entry_id=raw["entry_id"], song_id=raw["song_id"])
