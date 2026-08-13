import itertools
import logging
import shutil
import threading
from functools import partial
from typing import Any

from core.event_bus import EventBus
from core.library.library import Library
from core.peer.discovery import Discovery
from core.peer.identity import CoreIdentity
from core.peer.link import PeerLink
from core.peer.registry import PeerRegistry
from core.peer.transfers import Transfers
from core.runtime import Runtime
from protocol.errors import ProtocolError, insufficient_space, invalid_argument
from protocol.types.error import Error
from protocol.types.error_code import ErrorCode
from protocol.types.event_type import EventType
from protocol.types.peer_job import PeerJob
from protocol.types.peer_job_kind import PeerJobKind
from protocol.types.peer_job_state import SETTLED, PeerJobState
from protocol.types.peer_playlist import PeerPlaylist
from protocol.types.peer_record import PeerRecord
from protocol.types.peer_song import PeerSong
from protocol.types.song import Song

log = logging.getLogger(__name__)

PROGRESS_SECONDS = 1.0
ROWS_AT_ONCE = 400


class PeerJobs:
    """The job table and the threads under it. It settles a plan, writes rows and merges playlists, and hands the files to `Transfers`."""

    def __init__(
        self,
        library: Library,
        runtime: Runtime,
        identity: CoreIdentity,
        registry: PeerRegistry,
        discovery: Discovery,
        transfers: Transfers,
        bus: EventBus,
        space_reserve: int = 0,
    ):
        self._library = library
        self._runtime = runtime
        self._identity = identity
        self._registry = registry
        self._discovery = discovery
        self._transfers = transfers
        self._bus = bus
        self._space_reserve = space_reserve

        self._lock = threading.Condition()
        self._jobs: dict[str, _Job] = {}
        self._ids = itertools.count(1)
        transfers.report_to(self.transfer_finished)

    # Lifecycle

    def start(self) -> None:
        self._transfers.start()

    def stop(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                if job.state not in SETTLED:
                    job.cancelled = True
            self._lock.notify_all()
        self._transfers.stop()

    # Commands

    def list_songs(self, peer_id: str) -> str:
        return self._begin(PeerJobKind.LIST_SONGS, peer_id, None)

    def list_playlists(self, peer_id: str) -> str:
        return self._begin(PeerJobKind.LIST_PLAYLISTS, peer_id, None)

    def fetch_songs(self, peer_id: str, uuids: list[str] | None) -> str:
        return self._begin(PeerJobKind.FETCH_SONGS, peer_id, uuids)

    def fetch_playlists(self, peer_id: str, uuids: list[str] | None) -> str:
        return self._begin(PeerJobKind.FETCH_PLAYLISTS, peer_id, uuids)

    def jobs(self) -> list[PeerJob]:
        with self._lock:
            return [job.described() for job in self._jobs.values()]

    def cancel(self, job_id: str) -> None:
        """Unknown or settled, nothing happens. Rows already written stay."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state in SETTLED:
                return
            job.cancelled = True
            job.state = PeerJobState.CANCELLED
            self._lock.notify_all()
        self._transfers.drop(job_id)

    # Reports

    def transfer_finished(self, job_id: str, uuid: str, received: int, error: str | None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.waiting.discard(uuid)
            job.items_done += 1
            job.bytes_settled += received
            if error is None:
                job.files_received += 1
            else:
                job.given_up.append({"uuid": uuid, "error": error})
            self._lock.notify_all()

    # Internals

    def _begin(self, kind: PeerJobKind, peer_id: str, uuids: list[str] | None) -> str:
        peer = self._registry.require(peer_id)
        if uuids is not None and not uuids:
            raise invalid_argument("naming no uuids asks for nothing", peer_id=peer_id)
        with self._lock:
            job = _Job(f"j-{next(self._ids)}", kind, peer_id)
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, peer, uuids), name=f"peer-{job.id}", daemon=True).start()
        return job.id

    def _run(self, job: "_Job", peer: PeerRecord, uuids: list[str] | None) -> None:
        link = PeerLink(self._identity, self._registry, peer, self._discovery)
        try:
            if job.kind is PeerJobKind.LIST_SONGS:
                result = self._listed_songs(link)
            elif job.kind is PeerJobKind.LIST_PLAYLISTS:
                result = self._listed_playlists(link)
            else:
                result = self._fetched(job, link, uuids)
        except ProtocolError as failure:
            self._failed(job, failure.error)
            return
        except Exception as failure:
            log.exception("%s blew up", job.id)
            self._failed(job, Error(code=ErrorCode.INTERNAL, message=str(failure)))
            return
        self._finished(job, result)

    # Listing

    def _listed_songs(self, link: PeerLink) -> dict[str, Any]:
        held = self._held()
        return {"songs": [song.to_dict() | {"held": song.uuid in held} for song in link.songs()]}

    def _listed_playlists(self, link: PeerLink) -> dict[str, Any]:
        """The peer's playlists measured against this core, which takes its songs as well, for the sizes."""
        songs = {song.uuid: song for song in link.songs()}
        held = self._held()
        listed = []
        for playlist in link.playlists():
            # Duplicates count, since an entry is an entry.
            carried = sum(1 for uuid in playlist.songs if uuid in held)
            missing = [songs[uuid] for uuid in playlist.songs if uuid not in held and uuid in songs]
            listed.append(
                playlist.to_dict()
                | {
                    "songs_held": carried,
                    "songs_missing": len(playlist.songs) - carried,
                    "bytes_missing": sum(song.file_size for song in missing if song.available),
                }
            )
        return {"playlists": listed}

    def _held(self) -> set[str]:
        """The track uuids this core holds a file for."""
        return {song.uuid for song in self._library.snapshot_songs() if song.found_on_disk}

    # Fetching

    def _fetched(self, job: "_Job", link: PeerLink, uuids: list[str] | None) -> dict[str, Any]:
        songs = {song.uuid: song for song in link.songs()}
        playlists: list[PeerPlaylist] = []
        if job.kind is PeerJobKind.FETCH_PLAYLISTS:
            playlists, tracks = self._planned_playlists(job, link, songs, uuids)
        else:
            named = list(songs) if uuids is None else uuids
            job.unknown = [uuid for uuid in named if uuid not in songs]
            tracks = [uuid for uuid in dict.fromkeys(named) if uuid in songs]

        local = {song.uuid: song for song in self._library.snapshot_songs()}
        files = [songs[uuid] for uuid in tracks if songs[uuid].available and not _is_held(local.get(uuid))]
        self._require_space(files)

        with self._lock:
            job.items_total = len(files)
            job.bytes_total = sum(song.file_size for song in files)
            job.waiting = {song.uuid for song in files}
            if not job.cancelled:
                job.state = PeerJobState.RUNNING
        self._publish(job)

        self._write_rows(job, [songs[uuid] for uuid in tracks], playlists)
        if job.cancelled:
            return job.result()
        for song in files:
            self._transfers.submit(job.id, link, song)
        self._wait_out(job)
        return job.result()

    def _require_space(self, files: list[PeerSong]) -> None:
        """A plan is settled only when its files fit beside what the queue has still to move."""
        wanted = sum(song.file_size for song in files) + self._transfers.outstanding()
        usable = max(shutil.disk_usage(self._library.root).free - self._space_reserve, 0)
        if wanted > usable:
            raise insufficient_space(f"the plan needs {wanted} bytes and {usable} are free", wanted=wanted, usable=usable)

    def _planned_playlists(
        self, job: "_Job", link: PeerLink, songs: dict[str, PeerSong], uuids: list[str] | None
    ) -> tuple[list[PeerPlaylist], list[str]]:
        carried = {playlist.uuid: playlist for playlist in link.playlists()}
        named = list(carried) if uuids is None else list(dict.fromkeys(uuids))
        job.unknown = [uuid for uuid in named if uuid not in carried]
        wanted = [carried[uuid] for uuid in named if uuid in carried]
        tracks = dict.fromkeys(uuid for playlist in wanted for uuid in playlist.songs)
        return wanted, [uuid for uuid in tracks if uuid in songs]

    def _write_rows(self, job: "_Job", songs: list[PeerSong], playlists: list[PeerPlaylist]) -> None:
        """Rows before any file moves, so a playlist is whole and playable as far as its tracks allow."""
        for start in range(0, len(songs), ROWS_AT_ONCE):
            if job.cancelled:
                return
            batch = songs[start : start + ROWS_AT_ONCE]
            inserted, updated = self._runtime.call(partial(self._library.merge_peer_songs, batch))
            job.songs_inserted += inserted
            job.songs_updated += updated
        for playlist in playlists:
            if job.cancelled:
                return
            created, dropped = self._runtime.call(partial(self._library.merge_peer_playlist, playlist))
            job.playlists_created += 1 if created else 0
            job.playlists_updated += 0 if created else 1
            job.entries_dropped += dropped

    def _wait_out(self, job: "_Job") -> None:
        """Parks until every file in the plan is done, reporting no more than once a second."""
        while True:
            with self._lock:
                if not job.waiting or job.cancelled:
                    return
                self._lock.wait(PROGRESS_SECONDS)
            self._publish(job)

    # Reporting

    def _publish(self, job: "_Job") -> None:
        active = self._transfers.active_for(job.id)
        self._bus.publish(
            EventType.PEER_JOB_PROGRESS,
            {
                "job_id": job.id,
                "kind": job.kind.value,
                "state": job.state.value,
                "items_done": job.items_done,
                "items_total": job.items_total,
                "bytes_done": job.bytes_settled + sum(entry["bytes_done"] for entry in active),
                "bytes_total": job.bytes_total,
                "active": active,
            },
        )

    def _finished(self, job: "_Job", result: dict[str, Any]) -> None:
        with self._lock:
            if job.state is not PeerJobState.CANCELLED:
                job.state = PeerJobState.FINISHED
            state = job.state
        self._bus.publish(
            EventType.PEER_JOB_FINISHED,
            {"job_id": job.id, "kind": job.kind.value, "state": state.value, "result": result},
        )

    def _failed(self, job: "_Job", error: Error) -> None:
        """A job that got no further than planning, so nothing was written."""
        if job.cancelled:
            self._finished(job, job.result())
            return
        with self._lock:
            job.state = PeerJobState.FAILED
        self._bus.publish(
            EventType.PEER_JOB_FAILED, {"job_id": job.id, "kind": job.kind.value, "error": error.to_dict()}
        )


class _Job:
    """One job, as the table holds it."""

    def __init__(self, job_id: str, kind: PeerJobKind, peer_id: str):
        self.id = job_id
        self.kind = kind
        self.peer_id = peer_id
        self.state = PeerJobState.PLANNING
        self.cancelled = False

        self.items_total = 0
        self.items_done = 0
        self.bytes_total = 0
        self.bytes_settled = 0
        self.waiting: set[str] = set()

        self.songs_inserted = 0
        self.songs_updated = 0
        self.playlists_created = 0
        self.playlists_updated = 0
        self.entries_dropped = 0
        self.files_received = 0
        self.unknown: list[str] = []
        self.given_up: list[dict[str, str]] = []

    def described(self) -> PeerJob:
        return PeerJob(
            job_id=self.id,
            kind=self.kind,
            peer_id=self.peer_id,
            state=self.state,
            items_done=self.items_done,
            items_total=self.items_total,
            bytes_done=self.bytes_settled,
            bytes_total=self.bytes_total,
        )

    def result(self) -> dict[str, Any]:
        return {
            "playlists_created": self.playlists_created,
            "playlists_updated": self.playlists_updated,
            "entries_dropped": self.entries_dropped,
            "songs_inserted": self.songs_inserted,
            "songs_updated": self.songs_updated,
            "files_received": self.files_received,
            "bytes_received": self.bytes_settled,
            "unknown": self.unknown,
            "given_up": self.given_up,
        }


def _is_held(song: Song | None) -> bool:
    return song is not None and song.found_on_disk
