import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.event_bus import EventBus
from core.library.library import Library
from core.peer.types.peer_side import PeerSide
from core.playback.controller import PlaybackController
from core.runtime import Runtime
from core.session import SessionMemory
from core.types.client import Client, EventSink
from protocol.errors import ProtocolError, invalid_argument
from protocol.types.error import Error
from protocol.types.error_code import ErrorCode
from protocol.types.origin import Origin
from protocol.types.peer_playlist import PeerPlaylist
from protocol.types.peer_song import PeerSong
from protocol.types.request import Request
from protocol.types.response import Response
from protocol.types.session_state import SessionState
from protocol.version import PEER_PROTOCOL_VERSION

if TYPE_CHECKING:
    from core.peer.server import PeerServer

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], dict[str, Any]]

# Pairing emits a code for a frontend to display.
LOCAL_ONLY_METHODS = frozenset(
    {
        "pairing_status",
        "pairing_publish",
        "pairing_conceal",
        "pairing_candidates",
        "pairing_request",
        "pairing_submit_code",
        "pairing_cancel",
        "peer_forget",
    }
)

# These reach across the network and touch no library state, so holding the runtime thread for them would stall playback.
DIRECT_METHODS = frozenset({"pairing_request", "pairing_submit_code"})


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
        peer: PeerSide | None = None,
        features: Sequence[str] = (),
    ):
        self._library = library
        self._controller = controller
        self._runtime = runtime
        self._bus = bus
        self._memory = memory
        self._peer = peer
        self._features = list(features)
        self._peer_server: "PeerServer | None" = None
        self._handlers: dict[str, Handler] = self._build_handlers()

    # Lifecycle

    def use_peer_server(self, server: "PeerServer") -> None:
        """The peer listener answers by asking this service, so it is handed over once both exist."""
        self._peer_server = server

    def start(self) -> None:
        self._runtime.start()
        self._runtime.call(lambda: self._memory.restore(self._controller, self._library))
        self._runtime.scan_later()
        if self._peer is not None:
            self._peer.jobs.start()
        if self._peer_server is not None:
            self._peer_server.start()

    def stop(self) -> None:
        if self._peer_server is not None:
            self._peer_server.stop()
        # Jobs and transfers write through the runtime, so they let go of it before it stops.
        if self._peer is not None:
            self._peer.jobs.stop()
        self._runtime.stop()
        # The runtime thread has joined, so nothing else is still touching the memory.
        self._memory.flush()
        self._controller.close()
        self._library.close()

    def attach(self, name: str, sink: EventSink, origin: Origin = Origin.LOCAL) -> Client:
        """A transport takes a client handle here. The sink is called on the thread that raised the event."""
        return self._bus.attach(name, sink, origin)

    def detach(self, client: Client) -> None:
        self._bus.detach(client)

    # Dispatch

    def dispatch(self, envelope: dict[str, Any], origin: Origin = Origin.LOCAL) -> dict[str, Any]:
        try:
            request = Request.from_dict(envelope)
        except (KeyError, TypeError) as failure:
            error = Error(code=ErrorCode.INVALID_ARGUMENT, message=f"malformed request: {failure}")
            return Response.failed(str(envelope.get("id", "")), error).to_dict()

        handler = self._handlers.get(request.method)
        if handler is None or (origin is Origin.NETWORK and request.method in LOCAL_ONLY_METHODS):
            error = Error(code=ErrorCode.INVALID_ARGUMENT, message=f"no such method '{request.method}'")
            return Response.failed(request.id, error).to_dict()

        try:
            result = handler(request.params) if request.method in DIRECT_METHODS else self._runtime.call(lambda: handler(request.params))
        except ProtocolError as failure:
            return Response.failed(request.id, failure.error).to_dict()
        except Exception as failure:
            log.exception("%s blew up", request.method)
            error = Error(code=ErrorCode.INTERNAL, message=str(failure))
            return Response.failed(request.id, error).to_dict()
        return Response.succeeded(request.id, result).to_dict()

    def _build_handlers(self) -> dict[str, Handler]:
        handlers: dict[str, Handler] = {
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
        # A core with no peer identity carries no peer surface, so those methods read as unknown.
        if self._peer is not None:
            peer = self._peer
            handlers.update(
                {
                    "peer_list": self._peer_list,
                    "peer_forget": self._peer_forget,
                    "pairing_status": lambda params: peer.pairing.window(),
                    "pairing_publish": lambda params: peer.pairing.publish(_number(params, "seconds")),
                    "pairing_conceal": lambda params: peer.pairing.conceal(),
                    "pairing_candidates": self._pairing_candidates,
                    "pairing_request": self._pairing_request,
                    "pairing_submit_code": self._pairing_submit_code,
                    "pairing_cancel": self._pairing_cancel,
                    "peer_list_songs": lambda params: {"job_id": peer.jobs.list_songs(_text(params, "peer_id"))},
                    "peer_list_playlists": lambda params: {"job_id": peer.jobs.list_playlists(_text(params, "peer_id"))},
                    "peer_fetch_songs": self._peer_fetch_songs,
                    "peer_fetch_playlists": self._peer_fetch_playlists,
                    "peer_jobs": lambda params: {"jobs": [job.to_dict() for job in peer.jobs.jobs()]},
                    "peer_job_cancel": self._peer_job_cancel,
                }
            )
        return handlers

    # Handlers

    def _get_state(self, params: dict[str, Any]) -> dict[str, Any]:
        state = SessionState(
            playback=self._controller.playback_state(),
            queue=self._controller.queue_state(),
            library_revision=self._bus.library_revision,
            features=self._features,
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

    # Peers

    def _peer_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"peers": [peer.to_dict() for peer in self._peer.registry.peers()]}

    def _peer_forget(self, params: dict[str, Any]) -> dict[str, Any]:
        self._peer.registry.forget(_text(params, "peer_id"))
        return {}

    def _pairing_candidates(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"candidates": [candidate.to_dict() for candidate in self._peer.pairing.candidates()]}

    def _pairing_request(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._peer.pairing.request(_text(params, "core_id"), _optional_text(params, "address"))

    def _pairing_submit_code(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._peer.pairing.submit_code(_text(params, "session_id"), _text(params, "code"))

    def _pairing_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        self._peer.pairing.cancel(_text(params, "session_id"))
        return {}

    def _peer_fetch_songs(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"job_id": self._peer.jobs.fetch_songs(_text(params, "peer_id"), _optional_uuids(params, "uuids"))}

    def _peer_fetch_playlists(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"job_id": self._peer.jobs.fetch_playlists(_text(params, "peer_id"), _optional_uuids(params, "uuids"))}

    def _peer_job_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        self._peer.jobs.cancel(_text(params, "job_id"))
        return {}

    # What the peer listener serves. These read, so they answer on the calling thread.

    def peer_hello(self) -> dict[str, Any]:
        songs, playlists = self._library.counts()
        return {
            "id": self._peer.identity.uuid,
            "name": self._peer.identity.name,
            "version": PEER_PROTOCOL_VERSION,
            "library_revision": self._bus.library_revision,
            "songs": songs,
            "playlists": playlists,
        }

    def peer_songs(self) -> list[PeerSong]:
        return [PeerSong.from_song(song) for song in self._library.snapshot_songs()]

    def peer_playlists(self) -> list[PeerPlaylist]:
        return self._library.peer_playlists()

    def peer_track(self, uuid: str) -> Path | None:
        """The file behind a track uuid. None when this core holds no bytes to serve for it."""
        songs = self._library.get_songs_by_uuid([uuid])
        if not songs or not songs[0].found_on_disk:
            return None
        return self._library.path_for(songs[0])

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


def _optional_text(params: dict[str, Any], key: str) -> str | None:
    if params.get(key) is None:
        return None
    return _text(params, key)


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


def _optional_uuids(params: dict[str, Any], key: str) -> list[str] | None:
    """Naming nothing takes everything the peer carries, so an absent list is not an empty one."""
    if params.get(key) is None:
        return None
    return _uuids(params, key)


def _fields(params: dict[str, Any]) -> dict[str, Any]:
    fields = params.get("fields")
    if not isinstance(fields, dict):
        raise invalid_argument("'fields' must be an object")
    return fields
