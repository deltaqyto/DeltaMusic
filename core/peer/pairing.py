import hmac
import json
import secrets
import threading
from datetime import datetime, timedelta
from hashlib import sha256
from http.client import HTTPSConnection
from typing import Any

from core.event_bus import EventBus
from core.peer.discovery import Discovery
from core.peer.identity import CoreIdentity, presented_core
from core.peer.link import answer_from, decode, dial, presented
from core.peer.registry import DEFAULT_PEER_PORT, PeerRegistry
from core.peer.routes import PAIR_BEGIN, PAIR_PROVE
from core.peer.tls import client_context
from core.peer.types.pairing_session import PairingSession
from core.peer.types.presented_core import PresentedCore
from protocol.errors import ProtocolError, pairing_closed, pairing_refused, peer_unreachable, untrusted_peer
from protocol.timestamps import now, to_iso
from protocol.types.error_code import ErrorCode
from protocol.types.event_type import EventType
from protocol.types.pairing_candidate import PairingCandidate
from protocol.types.pairing_state import PairingState

CODE_MODULUS = 10000
ATTEMPTS = 3
IDLE_SECONDS = 120
OPEN_SESSIONS = 8
DIAL_TIMEOUT = 10.0
JSON_HEADERS = {"Content-Type": "application/json"}


class Pairing:
    """Windows, sessions, codes and proofs, and both ends of the exchange."""

    def __init__(
        self,
        identity: CoreIdentity,
        registry: PeerRegistry,
        discovery: Discovery,
        bus: EventBus,
        port: int,
        visibility_seconds: int,
    ):
        self._identity = identity
        self._registry = registry
        self._discovery = discovery
        self._bus = bus
        self._port = port
        self._limit = max(1, visibility_seconds)
        self._context = client_context(identity)

        self._lock = threading.RLock()
        self._inbound: dict[str, PairingSession] = {}
        self._outbound: dict[str, PairingSession] = {}
        self._expires_at: datetime | None = None
        self._timer: threading.Timer | None = None

    def stop(self) -> None:
        with self._lock:
            self._cancel_timer()
            self._inbound.clear()
            self._outbound.clear()

    # The window

    def window(self) -> dict[str, Any]:
        with self._lock:
            return {"open": self._discovery.pairing, "expires_at": to_iso(self._expires_at)}

    def publish(self, seconds: float) -> dict[str, Any]:
        span = min(max(1, int(seconds)), self._limit)
        with self._lock:
            self._cancel_timer()
            self._expires_at = now() + timedelta(seconds=span)
            self._timer = threading.Timer(span, self._close)
            self._timer.daemon = True
            self._timer.start()
        # Advertising reaches into zeroconf, which browses on its own thread and draws candidates back through here.
        self._discovery.set_pairing(True)
        return self._announce_window()

    def conceal(self) -> dict[str, Any]:
        return self._close()

    # Candidates

    def candidates(self) -> list[PairingCandidate]:
        """What discovery found, once the peers are taken out."""
        known = {peer.id for peer in self._registry.peers()}
        return [candidate for candidate in self._discovery.candidates() if candidate.id not in known]

    def discovered(self) -> None:
        """Discovery saw the network change, so what is left once the peers are taken out is announced."""
        candidates = self.candidates()
        self._bus.publish(
            EventType.PAIRING_CANDIDATES_CHANGED, {"candidates": [candidate.to_dict() for candidate in candidates]}
        )

    # Pairing, as the initiator

    def request(self, core_id: str, address: str | None) -> dict[str, Any]:
        target = self._target(core_id, address)
        connection = self._dial(target)
        try:
            core = self._identify(connection, target)
            self._matches_claim(core_id, core)
            answer = decode(answer_from(connection, "POST", PAIR_BEGIN, JSON_HEADERS, b"{}"))
        finally:
            connection.close()

        session_id = str(answer.get("session_id") or "")
        if not session_id:
            raise pairing_refused(f"{core.name} opened no pairing session", core_id=core_id)
        session = PairingSession(
            id=session_id,
            peer_id=core.id,
            peer_name=core.name,
            fingerprint=core.fingerprint,
            address=target[0],
            port=target[1],
            idle_until=now() + timedelta(seconds=IDLE_SECONDS),
            attempts_left=ATTEMPTS,
        )
        with self._lock:
            self._reap()
            self._outbound[session_id] = session
        self._announce(session, PairingState.AWAITING_CODE)
        return {"session_id": session_id, "state": PairingState.AWAITING_CODE.value}

    def submit_code(self, session_id: str, code: str) -> dict[str, Any]:
        session = self._live(self._outbound, session_id)
        proof = _proof(code, self._identity.fingerprint_bytes, bytes.fromhex(session.fingerprint))
        body = json.dumps({"session_id": session_id, "proof": proof}).encode("utf-8")

        target = (session.address, session.port)
        connection = self._dial(target)
        try:
            core = self._identify(connection, target)
            if core.fingerprint != session.fingerprint:
                raise untrusted_peer(f"{session.address} is no longer {session.peer_name}", session_id=session_id)
            answer = decode(answer_from(connection, "POST", PAIR_PROVE, JSON_HEADERS, body))
        except ProtocolError as failure:
            if failure.error.code is ErrorCode.PAIRING_REFUSED:
                raise self._spend(self._outbound, session, failure.error.detail.get("attempts_left"))
            raise
        finally:
            connection.close()

        described = answer.get("core") or {}
        self._registry.pair(
            peer_id=str(described.get("id") or core.id),
            name=str(described.get("name") or core.name),
            fingerprint=session.fingerprint,
            address=session.address,
            port=int(described.get("port") or session.port),
        )
        with self._lock:
            self._outbound.pop(session_id, None)
        self._announce(session, PairingState.PAIRED)
        return {"state": PairingState.PAIRED.value, "attempts_left": session.attempts_left}

    def cancel(self, session_id: str) -> None:
        with self._lock:
            session = self._outbound.pop(session_id, None) or self._inbound.pop(session_id, None)
        if session is not None:
            self._announce(session, PairingState.CANCELLED)

    # Pairing, as the responder

    def begin(self, certificate_der: bytes, address: str) -> dict[str, Any]:
        if not self._discovery.pairing:
            raise pairing_closed("this core is not accepting pairing")
        core = self._readable(certificate_der)
        session = PairingSession(
            id=secrets.token_hex(8),
            peer_id=core.id,
            peer_name=core.name,
            fingerprint=core.fingerprint,
            address=address,
            port=self._port_of(core.id),
            idle_until=now() + timedelta(seconds=IDLE_SECONDS),
            attempts_left=ATTEMPTS,
            code=f"{secrets.randbelow(CODE_MODULUS):04d}",
        )
        with self._lock:
            self._reap()
            if len(self._inbound) >= OPEN_SESSIONS:
                raise pairing_closed("this core is holding as many pairing sessions as it will")
            self._inbound[session.id] = session
        self._bus.publish(
            EventType.PAIRING_CODE_READY,
            {"session_id": session.id, "code": session.code, "peer_name": session.peer_name},
        )
        self._announce(session, PairingState.AWAITING_CODE)
        return {"session_id": session.id, "state": PairingState.AWAITING_CODE.value}

    def prove(self, certificate_der: bytes, session_id: str, proof: str, address: str) -> dict[str, Any]:
        core = self._readable(certificate_der)
        session = self._live(self._inbound, session_id)
        if session.fingerprint != core.fingerprint:
            raise pairing_refused("that session was opened by another core", session_id=session_id)

        expected = _proof(session.code or "", bytes.fromhex(session.fingerprint), self._identity.fingerprint_bytes)
        if not hmac.compare_digest(expected, proof):
            raise self._spend(self._inbound, session)

        self._registry.pair(
            peer_id=session.peer_id,
            name=session.peer_name,
            fingerprint=session.fingerprint,
            address=address or session.address,
            port=self._port_of(session.peer_id),
        )
        with self._lock:
            self._inbound.pop(session_id, None)
        self._announce(session, PairingState.PAIRED)
        # A pairing that lands closes the window behind it.
        self._close()
        return {
            "state": PairingState.PAIRED.value,
            "core": {"id": self._identity.uuid, "name": self._identity.name, "port": self._port},
        }

    # Internals

    def _target(self, core_id: str, address: str | None) -> tuple[str, int]:
        """Where to reach a core: the address a caller named, else wherever discovery says it is."""
        if address:
            return _split(address)
        candidate = self._discovery.find(core_id)
        if candidate is None:
            raise peer_unreachable(f"discovery has not surfaced {core_id}", core_id=core_id)
        return candidate.address, candidate.port

    def _dial(self, target: tuple[str, int]) -> HTTPSConnection:
        try:
            return dial(self._context, target[0], target[1], DIAL_TIMEOUT)
        except OSError as failure:
            raise peer_unreachable(f"{target[0]}:{target[1]} did not answer: {failure}")

    def _identify(self, connection: HTTPSConnection, target: tuple[str, int]) -> PresentedCore:
        """Who whoever answered says they are, off the certificate they handed over."""
        certificate = presented(connection)
        if certificate is None:
            raise untrusted_peer(f"{target[0]}:{target[1]} presented no certificate")
        return self._readable(certificate)

    def _matches_claim(self, core_id: str, core: PresentedCore) -> None:
        """A candidate's fingerprint is a claim, and whoever answers has to carry the key behind it."""
        claimed = self._discovery.find(core_id)
        if claimed is not None and claimed.fingerprint and claimed.fingerprint != core.fingerprint:
            raise untrusted_peer(f"{claimed.name} was announced under another key", core_id=core_id)

    @staticmethod
    def _readable(certificate_der: bytes) -> PresentedCore:
        core = presented_core(certificate_der)
        if core is None:
            raise untrusted_peer("that certificate could not be read")
        return core

    def _port_of(self, core_id: str) -> int:
        """An inbound connection names no listening port, so discovery is asked for one."""
        candidate = self._discovery.find(core_id)
        return candidate.port if candidate is not None else DEFAULT_PEER_PORT

    def _live(self, table: dict[str, PairingSession], session_id: str) -> PairingSession:
        """The session, with its idle clock pushed forward. A session that is gone is refused."""
        with self._lock:
            self._reap()
            session = table.get(session_id)
            if session is None:
                raise pairing_refused("that pairing session is not open", session_id=session_id)
            session.idle_until = now() + timedelta(seconds=IDLE_SECONDS)
            return session

    def _spend(self, table: dict[str, PairingSession], session: PairingSession, reported: Any = None) -> ProtocolError:
        """Burns an attempt, destroys the session when they are gone, and gives back the refusal to raise."""
        with self._lock:
            session.attempts_left = int(reported) if reported is not None else session.attempts_left - 1
            spent = session.attempts_left <= 0
            if spent:
                session.attempts_left = 0
                table.pop(session.id, None)
        self._announce(session, PairingState.REFUSED)
        message = "the attempts on that code are spent" if spent else "that code did not match"
        return pairing_refused(message, session_id=session.id, attempts_left=session.attempts_left)

    def _reap(self) -> None:
        moment = now()
        for table in (self._inbound, self._outbound):
            for session_id in [session.id for session in table.values() if session.idle_until <= moment]:
                table.pop(session_id, None)

    def _close(self) -> dict[str, Any]:
        with self._lock:
            self._cancel_timer()
            self._expires_at = None
            # A session lives inside the window it was opened in.
            self._inbound.clear()
        self._discovery.set_pairing(False)
        return self._announce_window()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _announce_window(self) -> dict[str, Any]:
        state = self.window()
        self._bus.publish(EventType.PAIRING_WINDOW_CHANGED, state)
        return state

    def _announce(self, session: PairingSession, state: PairingState) -> None:
        self._bus.publish(
            EventType.PAIRING_STATE_CHANGED,
            {"session_id": session.id, "state": state.value, "attempts_left": session.attempts_left},
        )


def _proof(code: str, initiator: bytes, responder: bytes) -> str:
    """HMAC-SHA256 under the code, over the two raw fingerprints, the initiator's first."""
    return hmac.new(code.encode("utf-8"), initiator + responder, sha256).hexdigest()


def _split(address: str) -> tuple[str, int]:
    """An address a caller named, which may carry a port after a colon."""
    host, separator, port = address.rpartition(":")
    if separator and port.isdigit():
        return host, int(port)
    return address, DEFAULT_PEER_PORT
