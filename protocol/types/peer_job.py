from dataclasses import dataclass
from typing import Any

from protocol.types.peer_job_kind import PeerJobKind
from protocol.types.peer_job_state import PeerJobState


@dataclass(frozen=True)
class PeerJob:
    """One job of this run, as `peer_jobs` gives it."""

    job_id: str
    kind: PeerJobKind
    peer_id: str
    state: PeerJobState
    items_done: int = 0
    items_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind.value,
            "peer_id": self.peer_id,
            "state": self.state.value,
            "items_done": self.items_done,
            "items_total": self.items_total,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PeerJob":
        return PeerJob(
            job_id=raw["job_id"],
            kind=PeerJobKind(raw["kind"]),
            peer_id=raw["peer_id"],
            state=PeerJobState(raw["state"]),
            items_done=int(raw.get("items_done") or 0),
            items_total=int(raw.get("items_total") or 0),
            bytes_done=int(raw.get("bytes_done") or 0),
            bytes_total=int(raw.get("bytes_total") or 0),
        )
