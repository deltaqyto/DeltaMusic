from dataclasses import dataclass
from typing import Any

from protocol.types.source_kind import SourceKind


@dataclass(frozen=True)
class Source:
    kind: SourceKind
    playlist_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "playlist_id": self.playlist_id}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Source":
        return Source(kind=SourceKind(raw["kind"]), playlist_id=raw.get("playlist_id"))
