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
