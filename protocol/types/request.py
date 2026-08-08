from dataclasses import dataclass, field
from typing import Any

from protocol.version import PROTOCOL_VERSION


@dataclass(frozen=True)
class Request:
    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    v: int = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"v": self.v, "id": self.id, "method": self.method, "params": self.params}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Request":
        return Request(
            v=raw.get("v", PROTOCOL_VERSION),
            id=raw["id"],
            method=raw["method"],
            params=raw.get("params") or {},
        )
