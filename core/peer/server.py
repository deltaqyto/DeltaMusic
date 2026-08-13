import gzip
import hashlib
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from core.peer.discovery import Discovery
from core.peer.identity import CoreIdentity
from core.peer.pairing import Pairing
from core.peer.registry import PeerRegistry
from core.peer.routes import DIGEST_HEADER, ROOT
from core.peer.tls import server_context
from protocol.errors import ProtocolError, invalid_argument
from protocol.types.error import Error
from protocol.types.error_code import ErrorCode
from protocol.types.peer_record import PeerRecord

if TYPE_CHECKING:
    from core.service import CoreService

log = logging.getLogger(__name__)

CHUNK = 1 << 16
HANDSHAKE_TIMEOUT = 10.0
REQUEST_TIMEOUT = 30.0
MAX_BODY = 1 << 16

STATUS = {
    ErrorCode.INVALID_ARGUMENT: HTTPStatus.BAD_REQUEST,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.UNTRUSTED_PEER: HTTPStatus.FORBIDDEN,
    ErrorCode.PAIRING_CLOSED: HTTPStatus.CONFLICT,
    ErrorCode.PAIRING_REFUSED: HTTPStatus.FORBIDDEN,
}


class PeerServer:
    """The inbound half. Answers the peer routes by asking `CoreService` for library data."""

    def __init__(
        self,
        service: "CoreService",
        identity: CoreIdentity,
        registry: PeerRegistry,
        discovery: Discovery,
        pairing: Pairing,
        port: int,
    ):
        self.service = service
        self.registry = registry
        self.discovery = discovery
        self.pairing = pairing
        self._port = port
        self._context = server_context(identity)
        self._http: _Listener | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._http is not None:
            return
        try:
            self._http = _Listener(("", self._port), _Handler, self._context, self)
        except OSError as failure:
            log.error("the peer listener could not take port %d: %s", self._port, failure)
            return
        self._thread = threading.Thread(target=self._http.serve_forever, name="peer-listener", daemon=True)
        self._thread.start()
        log.info("the peer listener is up on %d", self._port)
        # The service is advertised while the listener is up.
        self.discovery.start()

    def stop(self) -> None:
        # An exchange cannot land once the listener is down, so the window and its sessions go with it.
        self.pairing.stop()
        self.discovery.stop()
        http, thread = self._http, self._thread
        self._http, self._thread = None, None
        if http is None:
            return
        http.shutdown()
        http.server_close()
        if thread is not None:
            thread.join(timeout=5.0)


class _Listener(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type, context: Any, peer: PeerServer):
        self.context = context
        self.peer = peer
        super().__init__(address, handler)

    def get_request(self) -> tuple[Any, Any]:
        connection, address = self.socket.accept()
        try:
            connection.settimeout(HANDSHAKE_TIMEOUT)
            wrapped = self.context.wrap_socket(connection, server_side=True)
        except OSError:
            # A handshake that does not chain to the authority never becomes a request.
            connection.close()
            raise
        wrapped.settimeout(REQUEST_TIMEOUT)
        return wrapped, address

    def handle_error(self, request: Any, client_address: Any) -> None:
        log.debug("the peer listener dropped a request from %s", client_address, exc_info=True)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DeltaMusic"
    sys_version = ""

    def do_GET(self) -> None:
        if self._caller() is None:
            return
        route = self._route()
        try:
            if route == "hello":
                self._json(self._peer.service.peer_hello())
            elif route == "songs":
                self._packed({"songs": [song.to_dict() for song in self._peer.service.peer_songs()]})
            elif route == "playlists":
                self._packed({"playlists": [playlist.to_dict() for playlist in self._peer.service.peer_playlists()]})
            elif route is not None and route.startswith("track/"):
                self._track(unquote(route[len("track/") :]))
            else:
                self._fail(ErrorCode.NOT_FOUND, "no such route")
        except ProtocolError as failure:
            self._refuse(failure.error)
        except ConnectionError:
            log.debug("a peer went away part way through %s", route)
            self.close_connection = True

    def do_POST(self) -> None:
        """The pairing routes take an untrusted certificate while the window is open."""
        certificate = self._certificate()
        if certificate is None:
            return
        route = self._route()
        pairing = self._peer.pairing
        try:
            if route == "pair/begin":
                self._json(pairing.begin(certificate, self.client_address[0]))
            elif route == "pair/prove":
                body = self._body()
                self._json(
                    pairing.prove(certificate, _string(body, "session_id"), _string(body, "proof"), self.client_address[0])
                )
            else:
                self._fail(ErrorCode.NOT_FOUND, "no such route")
        except ProtocolError as failure:
            self._refuse(failure.error)
        except ConnectionError:
            log.debug("a peer went away part way through %s", route)
            self.close_connection = True

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("peer listener: " + format, *args)

    # Internals

    @property
    def _peer(self) -> PeerServer:
        return self.server.peer

    def _route(self) -> str | None:
        path = urlsplit(self.path).path
        prefix = f"{ROOT}/"
        return path[len(prefix) :] if path.startswith(prefix) else None

    def _caller(self) -> PeerRecord | None:
        """The record for whoever is calling. Answers the caller and gives back None when no record pins it."""
        certificate = self._certificate()
        if certificate is None:
            return None
        record = self._peer.registry.met(certificate, self.client_address[0])
        if record is None:
            self._fail(ErrorCode.UNTRUSTED_PEER, "no record pins that certificate")
            return None
        return record

    def _certificate(self) -> bytes | None:
        """What the caller handed over. Every route needs one, whether or not it needs trust."""
        certificate = self.connection.getpeercert(binary_form=True)
        if certificate is None:
            self._fail(ErrorCode.UNTRUSTED_PEER, "this route needs a core certificate")
            return None
        return certificate

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            raise invalid_argument("a peer sent no readable body")
        try:
            carried = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise invalid_argument("a peer sent a body that is not JSON")
        if not isinstance(carried, dict):
            raise invalid_argument("a peer sent a body that is not an object")
        return carried

    def _track(self, uuid: str) -> None:
        path = self._peer.service.peer_track(uuid)
        if path is None or not path.is_file():
            self._fail(ErrorCode.NOT_FOUND, f"no file for {uuid}")
            return
        size = path.stat().st_size
        span = _requested_range(self.headers.get("Range"), size)
        if span is None:
            self._send(
                HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                b"",
                headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
            )
            return

        start, end = span
        headers = {
            "Accept-Ranges": "bytes",
            # The whole file's digest, so a transfer resumed by `Range` still verifies at the end.
            DIGEST_HEADER: _digest_of(path),
        }
        status = HTTPStatus.OK
        if (start, end) != (0, size - 1):
            status = HTTPStatus.PARTIAL_CONTENT
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._headers(status, end - start + 1, "application/octet-stream", headers)
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = handle.read(min(CHUNK, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def _json(self, payload: dict[str, Any]) -> None:
        self._send(HTTPStatus.OK, json.dumps(payload).encode("utf-8"))

    def _packed(self, payload: dict[str, Any]) -> None:
        body = gzip.compress(json.dumps(payload).encode("utf-8"))
        self._send(HTTPStatus.OK, body, headers={"Content-Encoding": "gzip"})

    def _fail(self, code: ErrorCode, message: str) -> None:
        self._refuse(Error(code=code, message=message))

    def _refuse(self, error: Error) -> None:
        """The refusal, and the connection with it, since a body this end did not read leaves nothing to reuse."""
        body = json.dumps({"error": error.to_dict()}).encode("utf-8")
        self.close_connection = True
        self._send(STATUS.get(error.code, HTTPStatus.INTERNAL_SERVER_ERROR), body, headers={"Connection": "close"})

    def _send(self, status: HTTPStatus, body: bytes, content_type: str = "application/json", headers: dict[str, str] | None = None) -> None:
        self._headers(status, len(body), content_type, headers)
        if body:
            self.wfile.write(body)

    def _headers(self, status: HTTPStatus, length: int, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()


def _string(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise invalid_argument(f"'{key}' must be a string")
    return value


def _requested_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The span to serve, the whole file when nothing was asked for. None when what was asked for is outside the file."""
    whole = (0, size - 1)
    if not header or not header.startswith("bytes=") or "," in header:
        return whole
    first, separator, last = header[len("bytes=") :].strip().partition("-")
    if not separator:
        return whole
    try:
        if not first:
            # A suffix range counts back from the end.
            start, end = max(0, size - int(last)), size - 1
        else:
            start, end = int(first), int(last) if last else size - 1
    except ValueError:
        return whole
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()
