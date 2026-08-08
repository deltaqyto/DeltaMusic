from dataclasses import dataclass
from typing import Any

from protocol.types.playback_state import PlaybackState
from protocol.types.queue_state import QueueState


@dataclass(frozen=True)
class SessionState:
    """The whole snapshot `get_state` returns."""

    playback: PlaybackState
    queue: QueueState
    library_revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "playback": self.playback.to_dict(),
            "queue": self.queue.to_dict(),
            "library_revision": self.library_revision,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "SessionState":
        return SessionState(
            playback=PlaybackState.from_dict(raw["playback"]),
            queue=QueueState.from_dict(raw["queue"]),
            library_revision=raw["library_revision"],
        )
