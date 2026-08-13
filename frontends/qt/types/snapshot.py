from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from protocol.types.peer_playlist import PeerPlaylist
from protocol.types.peer_song import PeerSong


@dataclass(frozen=True)
class ListedSong:
    """A peer song as a listing job measured it against this core."""

    song: PeerSong
    held: bool
    """Whether this core has that track's file on disk."""

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ListedSong":
        return ListedSong(song=PeerSong.from_dict(raw), held=bool(raw.get("held")))


@dataclass(frozen=True)
class ListedPlaylist:
    """A peer playlist with its entries counted by that same measure, duplicates included."""

    playlist: PeerPlaylist
    songs_held: int
    songs_missing: int
    bytes_missing: int

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ListedPlaylist":
        return ListedPlaylist(
            playlist=PeerPlaylist.from_dict(raw),
            songs_held=int(raw.get("songs_held") or 0),
            songs_missing=int(raw.get("songs_missing") or 0),
            bytes_missing=int(raw.get("bytes_missing") or 0),
        )


@dataclass
class Snapshot:
    """One peer's songs and playlists, as its listing jobs answered them."""

    peer_id: str
    songs: list[ListedSong] = field(default_factory=list)
    playlists: list[ListedPlaylist] = field(default_factory=list)

    @cached_property
    def by_uuid(self) -> dict[str, ListedSong]:
        return {listed.song.uuid: listed for listed in self.songs}

    def playlist(self, uuid: str) -> ListedPlaylist | None:
        return next((listed for listed in self.playlists if listed.playlist.uuid == uuid), None)

    def tracks_of(self, uuid: str) -> list[ListedSong]:
        """The playlist's entries in the peer's order, as far as its songs were listed."""
        listed = self.playlist(uuid)
        if listed is None:
            return []
        return [self.by_uuid[track] for track in listed.playlist.songs if track in self.by_uuid]
