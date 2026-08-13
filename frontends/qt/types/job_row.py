from dataclasses import dataclass, field
from typing import Any

from protocol.types.peer_job import PeerJob
from protocol.types.peer_job_kind import PeerJobKind
from protocol.types.peer_job_state import SETTLED, PeerJobState


@dataclass(frozen=True)
class Transfer:
    """One track file moving for this job."""

    uuid: str
    bytes_done: int
    bytes_total: int

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Transfer":
        return Transfer(
            uuid=raw["uuid"],
            bytes_done=int(raw.get("bytes_done") or 0),
            bytes_total=int(raw.get("bytes_total") or 0),
        )


@dataclass
class JobRow:
    """One fetch of this run, as the job bar draws it."""

    job_id: str
    kind: PeerJobKind
    peer_id: str
    state: PeerJobState
    items_done: int = 0
    items_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    active: list[Transfer] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    @staticmethod
    def from_job(job: PeerJob) -> "JobRow":
        return JobRow(
            job_id=job.job_id,
            kind=job.kind,
            peer_id=job.peer_id,
            state=job.state,
            items_done=job.items_done,
            items_total=job.items_total,
            bytes_done=job.bytes_done,
            bytes_total=job.bytes_total,
        )

    def apply_progress(self, payload: dict[str, Any]) -> None:
        self.state = PeerJobState(payload["state"])
        self.items_done = int(payload.get("items_done") or 0)
        self.items_total = int(payload.get("items_total") or 0)
        self.bytes_done = int(payload.get("bytes_done") or 0)
        self.bytes_total = int(payload.get("bytes_total") or 0)
        self.active = [Transfer.from_dict(raw) for raw in payload.get("active") or []]

    @property
    def settled(self) -> bool:
        return self.state in SETTLED

    @property
    def unknown(self) -> list[str]:
        return list((self.result or {}).get("unknown") or [])

    @property
    def given_up(self) -> list[dict[str, Any]]:
        return list((self.result or {}).get("given_up") or [])

    @property
    def clean(self) -> bool:
        """A settled job that named nothing it could not do."""
        return self.error is None and not self.unknown and not self.given_up
