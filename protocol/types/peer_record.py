from dataclasses import dataclass
from datetime import datetime
from typing import Any

from protocol.timestamps import from_iso, to_iso


@dataclass(frozen=True)
class PeerRecord:
    """One peer, as `config/peers.json` holds it and `peer_list` gives it."""

    id: str
    name: str
    fingerprint: str
    port: int
    address: str | None = None
    paired_at: datetime | None = None
    last_seen_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "fingerprint": self.fingerprint,
            "address": self.address,
            "port": self.port,
            "paired_at": to_iso(self.paired_at),
            "last_seen_at": to_iso(self.last_seen_at),
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PeerRecord":
        return PeerRecord(
            id=raw["id"],
            name=raw["name"],
            fingerprint=raw["fingerprint"],
            address=raw.get("address"),
            port=int(raw["port"]),
            paired_at=from_iso(raw.get("paired_at")),
            last_seen_at=from_iso(raw.get("last_seen_at")),
        )
