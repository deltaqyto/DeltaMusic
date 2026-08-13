from typing import Any

from protocol.types.error import Error
from protocol.types.error_code import ErrorCode


class ProtocolError(Exception):
    """Raised anywhere under CoreService"""

    def __init__(self, code: ErrorCode, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.error = Error(code=code, message=message, detail=detail or {})


def not_found(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.NOT_FOUND, message, detail)


def invalid_argument(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.INVALID_ARGUMENT, message, detail)


def conflict(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.CONFLICT, message, detail)


def track_absent(song_id: int) -> ProtocolError:
    return ProtocolError(ErrorCode.TRACK_ABSENT, "the song's file is not on disk", {"song_id": song_id})


def playback_failed(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.PLAYBACK_FAILED, message, detail)


def peer_unknown(peer_id: str) -> ProtocolError:
    return ProtocolError(ErrorCode.PEER_UNKNOWN, f"no peer {peer_id}", {"peer_id": peer_id})


def peer_unreachable(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.PEER_UNREACHABLE, message, detail)


def pairing_closed(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.PAIRING_CLOSED, message, detail)


def pairing_refused(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.PAIRING_REFUSED, message, detail)


def untrusted_peer(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.UNTRUSTED_PEER, message, detail)


def transfer_failed(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.TRANSFER_FAILED, message, detail)


def insufficient_space(message: str, **detail: Any) -> ProtocolError:
    return ProtocolError(ErrorCode.INSUFFICIENT_SPACE, message, detail)
