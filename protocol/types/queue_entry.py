from dataclasses import dataclass
from typing import Any

from protocol.types.queue_origin import QueueOrigin


@dataclass(frozen=True)
class QueueEntry:
    """One slot in the queue. `entry_id` lasts as long as the slot and only within one run of core."""

    entry_id: int
    song_id: int
    origin: QueueOrigin

    def to_dict(self) -> dict[str, Any]:
        return {"entry_id": self.entry_id, "song_id": self.song_id, "origin": self.origin.value}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "QueueEntry":
        return QueueEntry(entry_id=raw["entry_id"], song_id=raw["song_id"], origin=QueueOrigin(raw["origin"]))
