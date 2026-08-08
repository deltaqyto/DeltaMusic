from dataclasses import dataclass, field
from typing import Any

from protocol.types.event_type import EventType
from protocol.version import PROTOCOL_VERSION


@dataclass(frozen=True)
class Event:
    seq: int
    ts: str
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    v: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type.value,
            "payload": self.payload,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Event":
        return Event(
            v=raw.get("v", PROTOCOL_VERSION),
            seq=raw["seq"],
            ts=raw["ts"],
            type=EventType(raw["type"]),
            payload=raw.get("payload") or {},
        )
