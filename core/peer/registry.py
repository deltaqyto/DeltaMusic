import json
import logging
import threading
from dataclasses import replace
from pathlib import Path

from cryptography import x509

from core.event_bus import EventBus
from core.peer.identity import CoreIdentity, name_in
from core.peer.keys import digest_of
from protocol.errors import peer_unknown
from protocol.timestamps import now
from protocol.types.event_type import EventType
from protocol.types.peer_record import PeerRecord

log = logging.getLogger(__name__)

PEERS_FILE = "peers.json"
DEFAULT_PEER_PORT = 47822


class PeerRegistry:
    """`peers.json`, and the only thing that decides whether a presented certificate is trusted."""

    def __init__(self, config_dir: Path, identity: CoreIdentity, bus: EventBus):
        self._path = config_dir / PEERS_FILE
        self._identity = identity
        self._bus = bus
        self._lock = threading.RLock()
        self._peers: dict[str, PeerRecord] = self._load()

    # Reading

    def peers(self) -> list[PeerRecord]:
        with self._lock:
            return sorted(self._peers.values(), key=lambda peer: (peer.name, peer.id))

    def get(self, peer_id: str) -> PeerRecord | None:
        with self._lock:
            return self._peers.get(peer_id)

    def require(self, peer_id: str) -> PeerRecord:
        peer = self.get(peer_id)
        if peer is None:
            raise peer_unknown(peer_id)
        return peer

    def by_fingerprint(self, fingerprint: str) -> PeerRecord | None:
        with self._lock:
            return next((peer for peer in self._peers.values() if peer.fingerprint == fingerprint), None)

    # Trust

    def met(self, certificate_der: bytes, address: str | None = None, port: int | None = None) -> PeerRecord | None:
        """The record for a presented certificate, dated and addressed at this handshake. None when no record pins it."""
        try:
            certificate = x509.load_der_x509_certificate(certificate_der)
        except ValueError as failure:
            log.warning("could not read a presented certificate: %s", failure)
            return None
        fingerprint = digest_of(certificate.public_key()).hex()

        with self._lock:
            held = self.by_fingerprint(fingerprint)
            if held is None:
                return None
            peer = replace(
                held,
                name=name_in(certificate) or held.name,
                address=address or held.address,
                port=port or held.port,
                last_seen_at=now(),
            )
            self._peers[peer.id] = peer
            self._save()
            # Serving a pull leaves a client's peer list still, so `last_seen_at` moving on its own announces nothing.
            worth_drawing = (peer.name, peer.address) != (held.name, held.address)
        if worth_drawing:
            self._announce()
        return peer

    # Writing

    def pair(self, peer_id: str, name: str, fingerprint: str, address: str | None, port: int) -> PeerRecord:
        """The record a completed pairing leaves, on either side of the exchange."""
        moment = now()
        with self._lock:
            held = self._peers.get(peer_id)
            peer = PeerRecord(
                id=peer_id,
                name=name,
                fingerprint=fingerprint,
                port=port,
                address=address,
                paired_at=held.paired_at if held is not None else moment,
                last_seen_at=moment,
            )
            self._peers[peer_id] = peer
            self._save()
        self._announce()
        return peer

    def forget(self, peer_id: str) -> None:
        with self._lock:
            self.require(peer_id)
            del self._peers[peer_id]
            self._save()
        self._announce()

    def note_address(self, peer_id: str, address: str, port: int) -> None:
        """Where a peer answered, cached for the first attempt of the next connection."""
        with self._lock:
            peer = self._peers.get(peer_id)
            if peer is None or (peer.address == address and peer.port == port):
                return
            self._peers[peer_id] = replace(peer, address=address, port=port)
            self._save()

    # Internals

    def _announce(self) -> None:
        self._bus.publish(EventType.PEER_CHANGED, {"peers": [peer.to_dict() for peer in self.peers()]})

    def _load(self) -> dict[str, PeerRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            records = [PeerRecord.from_dict(entry) for entry in raw.get("peers") or []]
        except (OSError, KeyError, TypeError, ValueError) as failure:
            log.error("could not read %s, carrying on with no peers: %s", self._path, failure)
            return {}
        return {record.id: record for record in records}

    def _save(self) -> None:
        payload = {
            "core": {"id": self._identity.uuid, "name": self._identity.name},
            "peers": [peer.to_dict() for peer in self.peers()],
        }
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self._path)
        except OSError as failure:
            log.error("could not write %s: %s", self._path, failure)
