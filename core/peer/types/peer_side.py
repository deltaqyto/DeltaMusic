from dataclasses import dataclass

from core.peer.discovery import Discovery
from core.peer.identity import CoreIdentity
from core.peer.jobs import PeerJobs
from core.peer.pairing import Pairing
from core.peer.registry import PeerRegistry
from core.peer.transfers import Transfers


@dataclass(frozen=True)
class PeerSide:
    """The peer components of one core, wired to each other and handed to `CoreService` as one thing."""

    identity: CoreIdentity
    registry: PeerRegistry
    discovery: Discovery
    pairing: Pairing
    transfers: Transfers
    jobs: PeerJobs
