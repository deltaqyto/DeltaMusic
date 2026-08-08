from dataclasses import dataclass
from typing import Any

from protocol.types.playback_status import PlaybackStatus
from protocol.types.repeat_mode import RepeatMode


@dataclass(frozen=True)
class PlaybackState:
    status: PlaybackStatus
    song_id: int | None
    position: float
    rate: float
    duration: float
    volume: float
    repeat: RepeatMode
    shuffle: bool
    queue_revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "song_id": self.song_id,
            "position": self.position,
            "rate": self.rate,
            "duration": self.duration,
            "volume": self.volume,
            "repeat": self.repeat.value,
            "shuffle": self.shuffle,
            "queue_revision": self.queue_revision,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PlaybackState":
        return PlaybackState(
            status=PlaybackStatus(raw["status"]),
            song_id=raw["song_id"],
            position=raw["position"],
            rate=raw["rate"],
            duration=raw["duration"],
            volume=raw["volume"],
            repeat=RepeatMode(raw["repeat"]),
            shuffle=raw["shuffle"],
            queue_revision=raw["queue_revision"],
        )
