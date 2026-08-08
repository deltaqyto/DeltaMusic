from dataclasses import dataclass
from typing import Any

from protocol.types.queue_entry import QueueEntry
from protocol.types.source import Source


@dataclass(frozen=True)
class QueueState:
    entries: list[QueueEntry]
    cursor: int
    source: Source | None
    queue_revision: int

    @property
    def song_ids(self) -> list[int]:
        return [entry.song_id for entry in self.entries]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "cursor": self.cursor,
            "source": self.source.to_dict() if self.source else None,
            "queue_revision": self.queue_revision,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "QueueState":
        source = raw.get("source")
        return QueueState(
            entries=[QueueEntry.from_dict(entry) for entry in raw["entries"]],
            cursor=raw["cursor"],
            source=Source.from_dict(source) if source else None,
            queue_revision=raw["queue_revision"],
        )
