from enum import Enum


class PeerJobState(str, Enum):
    PLANNING = "planning"
    """Reading from the peer, before anything is written."""

    RUNNING = "running"
    """Rows are written and transfers are queued or in flight."""

    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


SETTLED = frozenset({PeerJobState.FINISHED, PeerJobState.FAILED, PeerJobState.CANCELLED})
