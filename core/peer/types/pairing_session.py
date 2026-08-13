from dataclasses import dataclass
from datetime import datetime


@dataclass
class PairingSession:
    """One side of one exchange. The responder draws the code, and the initiator holds none."""

    id: str
    peer_id: str
    peer_name: str
    fingerprint: str
    """The other core's, hex."""

    address: str
    port: int
    idle_until: datetime
    attempts_left: int
    code: str | None = None
