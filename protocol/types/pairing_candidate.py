from dataclasses import dataclass
from typing import Any

from protocol.version import PEER_PROTOCOL_VERSION


@dataclass(frozen=True)
class PairingCandidate:
    """A core discovered over mDNS, as its service record describes it."""

    id: str
    name: str
    fingerprint: str
    address: str
    port: int
    pairing: bool
    version: int = PEER_PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "fingerprint": self.fingerprint,
            "address": self.address,
            "port": self.port,
            "pairing": self.pairing,
            "version": self.version,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PairingCandidate":
        return PairingCandidate(
            id=raw["id"],
            name=raw["name"],
            fingerprint=raw["fingerprint"],
            address=raw["address"],
            port=int(raw["port"]),
            pairing=bool(raw["pairing"]),
            version=int(raw.get("version") or PEER_PROTOCOL_VERSION),
        )
