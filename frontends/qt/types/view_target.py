from dataclasses import dataclass


@dataclass(frozen=True)
class ViewTarget:
    """What the table is showing: a local playlist, a peer's library, or one of a peer's playlists."""

    peer_id: str | None = None
    playlist_id: int | None = None
    """A local playlist. None while a peer is browsed."""

    playlist_uuid: str | None = None
    """A peer playlist. None on a peer's whole library."""

    @staticmethod
    def local(playlist_id: int) -> "ViewTarget":
        return ViewTarget(playlist_id=playlist_id)

    @staticmethod
    def peer_library(peer_id: str) -> "ViewTarget":
        return ViewTarget(peer_id=peer_id)

    @staticmethod
    def peer_playlist(peer_id: str, uuid: str) -> "ViewTarget":
        return ViewTarget(peer_id=peer_id, playlist_uuid=uuid)

    @property
    def is_local(self) -> bool:
        return self.peer_id is None
