import logging
from collections.abc import Callable
from typing import Any

from core.event_bus import EventBus
from core.library.library import Library
from core.playback.controller import PlaybackController
from core.runtime import Runtime
from core.session import SessionMemory
from core.types.client import Client, EventSink
from protocol.errors import ProtocolError, invalid_argument
from protocol.types.error import Error
from protocol.types.error_code import ErrorCode
from protocol.types.request import Request
from protocol.types.response import Response
from protocol.types.session_state import SessionState

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class CoreService:
    """One method per command in the protocol, and the `dispatch` door onto them.
    """

    def __init__(
        self,
        library: Library,
        controller: PlaybackController,
        runtime: Runtime,
        bus: EventBus,
        memory: SessionMemory,
    ):
        self._library = library
        self._controller = controller
        self._runtime = runtime
        self._bus = bus
        self._memory = memory
        self._handlers: dict[str, Handler] = self._build_handlers()

    # Lifecycle

    def start(self) -> None:
        self._runtime.start()
        self._runtime.call(lambda: self._memory.restore(self._controller, self._library))
        self._runtime.scan_later()

    def stop(self) -> None:
        self._runtime.stop()
        # The runtime thread has joined, so nothing else is still touching the memory.
        self._memory.flush()
        self._controller.close()
        self._library.close()

    def attach(self, name: str, sink: EventSink) -> Client:
        """A transport takes a client handle here. The sink is called on the runtime thread."""
        return self._bus.attach(name, sink)

    def detach(self, client: Client) -> None:
        self._bus.detach(client)

    # Dispatch

    def dispatch(self, envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            request = Request.from_dict(envelope)
        except (KeyError, TypeError) as failure:
            error = Error(code=ErrorCode.INVALID_ARGUMENT, message=f"malformed request: {failure}")
            return Response.failed(str(envelope.get("id", "")), error).to_dict()

        handler = self._handlers.get(request.method)
        if handler is None:
            error = Error(code=ErrorCode.INVALID_ARGUMENT, message=f"no such method '{request.method}'")
            return Response.failed(request.id, error).to_dict()

        try:
            result = self._runtime.call(lambda: handler(request.params))
        except ProtocolError as failure:
            return Response.failed(request.id, failure.error).to_dict()
        except Exception as failure:
            log.exception("%s blew up", request.method)
            error = Error(code=ErrorCode.INTERNAL, message=str(failure))
            return Response.failed(request.id, error).to_dict()
        return Response.succeeded(request.id, result).to_dict()

    def _build_handlers(self) -> dict[str, Handler]:
        return {
            "get_state": self._get_state,
            "play": lambda params: self._playback(self._controller.play()),
            "pause": lambda params: self._playback(self._controller.pause()),
            "stop": lambda params: self._playback(self._controller.stop()),
            "seek_to": lambda params: self._playback(self._controller.seek_to(_number(params, "seconds"))),
            "seek_by": lambda params: self._playback(self._controller.seek_by(_number(params, "delta_seconds"))),
            "next_track": lambda params: self._playback(self._controller.next_track()),
            "previous_track": lambda params: self._playback(self._controller.previous_track()),
            "set_repeat": lambda params: self._playback(self._controller.set_repeat(_text(params, "mode"))),
            "set_shuffle": lambda params: self._playback(self._controller.set_shuffle(_flag(params, "enabled"))),
            "set_volume": lambda params: self._playback(self._controller.set_volume(_number(params, "level"))),
            "play_playlist": self._play_playlist,
            "play_songs": self._play_songs,
            "get_queue": lambda params: self._queue(self._controller.queue_state()),
            "queue_insert": self._queue_insert,
            "queue_remove": self._queue_remove,
            "queue_move": self._queue_move,
            "queue_clear": self._queue_clear,
            "list_songs": self._list_songs,
            "get_songs": self._get_songs,
            "get_songs_by_uuid": self._get_songs_by_uuid,
            "update_song": self._update_song,
            "forget_song": self._forget_song,
            "list_playlists": self._list_playlists,
            "get_playlist": self._get_playlist,
            "create_playlist": self._create_playlist,
            "update_playlist": self._update_playlist,
            "delete_playlist": self._delete_playlist,
            "playlist_add": self._playlist_add,
            "playlist_remove": self._playlist_remove,
            "playlist_move": self._playlist_move,
        }

    # Handlers

    def _get_state(self, params: dict[str, Any]) -> dict[str, Any]:
        state = SessionState(
            playback=self._controller.playback_state(),
            queue=self._controller.queue_state(),
            library_revision=self._bus.library_revision,
        )
        return state.to_dict()

    def _play_playlist(self, params: dict[str, Any]) -> dict[str, Any]:
        playlist_id = _integer(params, "playlist_id")
        start_index = params.get("start_index")
        paused = bool(params.get("paused"))
        return self._playback(self._controller.play_playlist(playlist_id, start_index, paused))

    def _play_songs(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._playback(self._controller.play_songs(_ids(params, "song_ids"), bool(params.get("paused"))))

    def _queue_insert(self, params: dict[str, Any]) -> dict[str, Any]:
        state = self._controller.queue_insert(_ids(params, "song_ids"), _optional_integer(params, "after_entry_id"))
        return self._queue(state)

    def _queue_remove(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._queue(self._controller.queue_remove(_ids(params, "entry_ids")))

    def _queue_move(self, params: dict[str, Any]) -> dict[str, Any]:
        state = self._controller.queue_move(
            _integer(params, "entry_id"), _optional_integer(params, "after_entry_id")
        )
        return self._queue(state)

    def _queue_clear(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._queue(self._controller.queue_clear())

    def _list_songs(self, params: dict[str, Any]) -> dict[str, Any]:
        songs, total = self._library.list_songs(
            params.get("query"), int(params.get("offset") or 0), int(params.get("limit") or 100)
        )
        return {"songs": [song.to_dict() for song in songs], "total": total}

    def _get_songs(self, params: dict[str, Any]) -> dict[str, Any]:
        songs = self._library.get_songs(_ids(params, "song_ids"))
        return {"songs": [song.to_dict() for song in songs]}

    def _get_songs_by_uuid(self, params: dict[str, Any]) -> dict[str, Any]:
        songs = self._library.get_songs_by_uuid(_uuids(params, "uuids"))
        return {"songs": [song.to_dict() for song in songs]}

    def _update_song(self, params: dict[str, Any]) -> dict[str, Any]:
        song = self._library.update_song(_integer(params, "song_id"), _fields(params))
        return {"song": song.to_dict()}

    def _forget_song(self, params: dict[str, Any]) -> dict[str, Any]:
        self._library.forget_song(_integer(params, "song_id"))
        return {}

    def _list_playlists(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"playlists": [playlist.to_dict() for playlist in self._library.list_playlists()]}

    def _get_playlist(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"playlist": self._library.get_playlist(_integer(params, "playlist_id")).to_dict()}

    def _create_playlist(self, params: dict[str, Any]) -> dict[str, Any]:
        playlist = self._library.create_playlist(_text(params, "name"), _ids(params, "song_ids", required=False))
        return {"playlist": playlist.to_dict()}

    def _update_playlist(self, params: dict[str, Any]) -> dict[str, Any]:
        playlist = self._library.update_playlist(_integer(params, "playlist_id"), _fields(params))
        return {"playlist": playlist.to_dict()}

    def _delete_playlist(self, params: dict[str, Any]) -> dict[str, Any]:
        self._library.delete_playlist(_integer(params, "playlist_id"))
        return {}

    def _playlist_add(self, params: dict[str, Any]) -> dict[str, Any]:
        at_index = params.get("at_index")
        playlist = self._library.playlist_add(
            _integer(params, "playlist_id"), _ids(params, "song_ids"), None if at_index is None else int(at_index)
        )
        return {"playlist": playlist.to_dict()}

    def _playlist_remove(self, params: dict[str, Any]) -> dict[str, Any]:
        playlist = self._library.playlist_remove(_ids(params, "entry_ids"))
        return {"playlist": playlist.to_dict()}

    def _playlist_move(self, params: dict[str, Any]) -> dict[str, Any]:
        playlist = self._library.playlist_move(_integer(params, "entry_id"), _integer(params, "to_index"))
        return {"playlist": playlist.to_dict()}

    @staticmethod
    def _playback(state: Any) -> dict[str, Any]:
        return {"playback": state.to_dict()}

    @staticmethod
    def _queue(state: Any) -> dict[str, Any]:
        return {"queue": state.to_dict()}


def _integer(params: dict[str, Any], key: str) -> int:
    try:
        return int(params[key])
    except (KeyError, TypeError, ValueError):
        raise invalid_argument(f"'{key}' must be an integer")


def _optional_integer(params: dict[str, Any], key: str) -> int | None:
    if params.get(key) is None:
        return None
    return _integer(params, key)


def _number(params: dict[str, Any], key: str) -> float:
    try:
        return float(params[key])
    except (KeyError, TypeError, ValueError):
        raise invalid_argument(f"'{key}' must be a number")


def _text(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        raise invalid_argument(f"'{key}' must be a string")
    return value


def _flag(params: dict[str, Any], key: str) -> bool:
    value = params.get(key)
    if not isinstance(value, bool):
        raise invalid_argument(f"'{key}' must be true or false")
    return value


def _ids(params: dict[str, Any], key: str, required: bool = True) -> list[int]:
    value = params.get(key)
    if value is None:
        if required:
            raise invalid_argument(f"'{key}' is required")
        return []
    if not isinstance(value, list):
        raise invalid_argument(f"'{key}' must be a list of integers")
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        raise invalid_argument(f"'{key}' must be a list of integers")


def _uuids(params: dict[str, Any], key: str) -> list[str]:
    value = params.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise invalid_argument(f"'{key}' must be a list of strings")
    return value


def _fields(params: dict[str, Any]) -> dict[str, Any]:
    fields = params.get("fields")
    if not isinstance(fields, dict):
        raise invalid_argument("'fields' must be an object")
    return fields
