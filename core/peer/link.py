import gzip
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from ssl import SSLContext
from typing import Any
from urllib.parse import quote

from core.peer.discovery import Discovery
from core.peer.identity import CoreIdentity, fingerprint_in
from core.peer.registry import PeerRegistry
from core.peer.routes import DIGEST_HEADER, PLAYLISTS, SONGS, TRACK
from core.peer.tls import client_context
from protocol.errors import ProtocolError, invalid_argument, peer_unreachable, untrusted_peer
from protocol.types.error_code import ErrorCode
from protocol.types.peer_playlist import PeerPlaylist
from protocol.types.peer_record import PeerRecord
from protocol.types.peer_song import PeerSong

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0


class PeerLink:
    """The outbound half: one peer, mutual TLS, the routes."""

    def __init__(
        self,
        identity: CoreIdentity,
        registry: PeerRegistry,
        peer: PeerRecord,
        discovery: Discovery | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._identity = identity
        self._registry = registry
        self._peer = peer
        self._discovery = discovery
        self._timeout = timeout
        self._context = client_context(identity)

    @property
    def peer(self) -> PeerRecord:
        return self._peer

    def songs(self) -> list[PeerSong]:
        return [PeerSong.from_dict(raw) for raw in self._read(SONGS).get("songs") or []]

    def playlists(self) -> list[PeerPlaylist]:
        return [PeerPlaylist.from_dict(raw) for raw in self._read(PLAYLISTS).get("playlists") or []]

    @contextmanager
    def track(self, uuid: str, start: int = 0) -> Iterator[tuple[HTTPResponse, str]]:
        """The file from `start`, and the digest of the whole of it. The body is read by the caller, inside the block."""
        connection = self._connect()
        try:
            headers = {"Range": f"bytes={start}-"} if start else {}
            response = answer_from(connection, "GET", f"{TRACK}/{quote(uuid)}", headers)
            yield response, response.headers.get(DIGEST_HEADER, "")
        finally:
            connection.close()

    # Internals

    def _read(self, path: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            return decode(answer_from(connection, "GET", path))
        finally:
            connection.close()

    def _connect(self) -> HTTPSConnection:
        refused: list[str] = []
        for address, port in self._targets():
            try:
                connection = dial(self._context, address, port, self._timeout)
            except OSError as failure:
                refused.append(f"{address}:{port} {failure}")
                continue
            try:
                self._confirm(connection, address, port)
            except ProtocolError:
                connection.close()
                raise
            return connection
        raise peer_unreachable(f"{self._peer.name} did not answer", peer_id=self._peer.id, tried=refused)

    def _targets(self) -> list[tuple[str, int]]:
        """The cached address first, then wherever discovery says the peer is now."""
        targets = [(self._peer.address, self._peer.port)] if self._peer.address else []
        candidate = self._discovery.find(self._peer.id) if self._discovery is not None else None
        if candidate is not None and (candidate.address, candidate.port) not in targets:
            targets.append((candidate.address, candidate.port))
        return targets

    def _confirm(self, connection: HTTPSConnection, address: str, port: int) -> None:
        """Whoever answered carries the key the record pins, and the handshake is dated and cached."""
        certificate = presented(connection)
        if certificate is None or fingerprint_in(certificate) != self._peer.fingerprint:
            raise untrusted_peer(f"{address}:{port} is not {self._peer.name}", peer_id=self._peer.id)
        self._registry.met(certificate, address, port)


def dial(context: SSLContext, address: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> HTTPSConnection:
    """Opens a connection and handshakes on it. What a failure means is the caller's to say."""
    connection = HTTPSConnection(address, port, context=context, timeout=timeout)
    try:
        connection.connect()
    except OSError:
        connection.close()
        raise
    return connection


def presented(connection: HTTPSConnection) -> bytes | None:
    """The certificate the other end handed over."""
    return connection.sock.getpeercert(binary_form=True) if connection.sock is not None else None


def answer_from(
    connection: HTTPSConnection,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> HTTPResponse:
    """The response, once it is known to carry one. A refusal is raised as the error the peer named."""
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
    except (HTTPException, OSError) as failure:
        raise peer_unreachable(f"the connection went away: {failure}")
    if response.status >= 400:
        raise _refusal_in(response)
    return response


def decode(response: HTTPResponse) -> dict[str, Any]:
    body = response.read()
    if (response.headers.get("Content-Encoding") or "").lower() == "gzip":
        body = gzip.decompress(body)
    answer = json.loads(body.decode("utf-8"))
    if not isinstance(answer, dict):
        raise invalid_argument("a peer answered with something other than an object")
    return answer


def _refusal_in(response: HTTPResponse) -> ProtocolError:
    try:
        carried = json.loads(response.read().decode("utf-8")).get("error") or {}
        return ProtocolError(ErrorCode(carried["code"]), carried.get("message") or "", carried.get("detail") or {})
    except (AttributeError, KeyError, TypeError, ValueError):
        return ProtocolError(ErrorCode.INTERNAL, f"a peer answered {response.status}")
