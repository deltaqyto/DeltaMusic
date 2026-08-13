from enum import Enum


class PeerJobKind(str, Enum):
    """What a peer job was started to do."""

    LIST_SONGS = "list_songs"
    LIST_PLAYLISTS = "list_playlists"
    FETCH_SONGS = "fetch_songs"
    FETCH_PLAYLISTS = "fetch_playlists"
