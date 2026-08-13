import logging
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal

from frontends.core_client import ClientError, CoreClient
from frontends.qt.types.job_row import JobRow
from frontends.qt.types.snapshot import ListedPlaylist, ListedSong, Snapshot
from protocol.timestamps import from_iso
from protocol.types.event import Event
from protocol.types.event_type import EventType
from protocol.types.library_scope import LibraryScope
from protocol.types.pairing_candidate import PairingCandidate
from protocol.types.pairing_state import PairingState
from protocol.types.peer_job import PeerJob
from protocol.types.peer_job_kind import PeerJobKind
from protocol.types.peer_job_state import PeerJobState
from protocol.types.peer_record import PeerRecord
from protocol.types.song import Song

log = logging.getLogger(__name__)

FETCH_KINDS = (PeerJobKind.FETCH_SONGS, PeerJobKind.FETCH_PLAYLISTS)


class PeerBook(QObject):
    """The peers, the active peer and its snapshot, the jobs, and the pairing window and session.

    It issues every peer and pairing command and turns the peer events into signals the widgets draw from.
    Nothing it holds outlives the run.
    """

    peers_changed = pyqtSignal()
    active_changed = pyqtSignal()
    snapshot_changed = pyqtSignal()
    snapshot_failed = pyqtSignal(str)
    job_changed = pyqtSignal(str)
    job_removed = pyqtSignal(str)
    window_changed = pyqtSignal()
    candidates_changed = pyqtSignal()
    session_changed = pyqtSignal()
    code_ready = pyqtSignal()
    failed = pyqtSignal(str)
    """A command that belongs to no dialog and no job row."""

    def __init__(self, client: CoreClient):
        super().__init__()
        self._client = client
        self._peers: list[PeerRecord] = []
        self._candidates: list[PairingCandidate] = []
        self._jobs: dict[str, JobRow] = {}
        self._listings: dict[str, str] = {}
        self._parts: dict[str, list | None] = {}
        self._active: str | None = None
        self._snapshot: Snapshot | None = None
        self._held: dict[str, Song] = {}
        self._window_open = False
        self._expires_at: datetime | None = None
        self._session: str | None = None
        self._state: PairingState | None = None
        self._attempts_left: int | None = None
        self._code: str | None = None
        self._code_peer: str | None = None

    # Seeding

    def start(self) -> None:
        """A frontend opening part way through a fetch shows it."""
        try:
            self._peers = [PeerRecord.from_dict(raw) for raw in self._client.call("peer_list")["peers"]]
            jobs = [PeerJob.from_dict(raw) for raw in self._client.call("peer_jobs")["jobs"]]
            window = self._client.call("pairing_status")
        except ClientError as failure:
            self.failed.emit(str(failure))
            return
        for job in jobs:
            if job.kind in FETCH_KINDS:
                self._jobs[job.job_id] = JobRow.from_job(job)
        self._take_window(window)
        self.peers_changed.emit()
        for job_id in self._jobs:
            self.job_changed.emit(job_id)

    # Reading

    def peers(self) -> list[PeerRecord]:
        return list(self._peers)

    def peer(self, peer_id: str) -> PeerRecord | None:
        return next((peer for peer in self._peers if peer.id == peer_id), None)

    def peer_name(self, peer_id: str) -> str:
        peer = self.peer(peer_id)
        return peer.name if peer is not None else peer_id

    def candidates(self) -> list[PairingCandidate]:
        return list(self._candidates)

    def jobs(self) -> list[JobRow]:
        return list(self._jobs.values())

    def job(self, job_id: str) -> JobRow | None:
        return self._jobs.get(job_id)

    def active_peer(self) -> str | None:
        return self._active

    def snapshot(self) -> Snapshot | None:
        return self._snapshot

    @property
    def listing(self) -> bool:
        return self._active is not None and self._snapshot is None

    @property
    def window_open(self) -> bool:
        return self._window_open

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def session(self) -> str | None:
        return self._session

    @property
    def session_state(self) -> PairingState | None:
        return self._state

    @property
    def attempts_left(self) -> int | None:
        return self._attempts_left

    @property
    def code(self) -> str | None:
        return self._code

    @property
    def code_peer(self) -> str | None:
        return self._code_peer

    # Browsing

    def activate(self, peer_id: str | None) -> None:
        if peer_id == self._active:
            return
        self._active = peer_id
        self._snapshot = None
        self._listings.clear()
        self._parts.clear()
        self.active_changed.emit()
        if peer_id is not None:
            self._list(peer_id)

    def refresh(self) -> None:
        """The view holds what it has until the new snapshot lands."""
        if self._active is not None:
            self._snapshot = None
            self._list(self._active)

    def _list(self, peer_id: str) -> None:
        try:
            songs = self._client.call("peer_list_songs", peer_id=peer_id)["job_id"]
            playlists = self._client.call("peer_list_playlists", peer_id=peer_id)["job_id"]
        except ClientError as failure:
            self.snapshot_failed.emit(str(failure))
            return
        self._listings = {songs: peer_id, playlists: peer_id}
        self._parts = {"songs": None, "playlists": None}

    def resolve(self, uuids: list[str]) -> dict[str, Song]:
        """Uuids to the local rows, fetching only what is not indexed."""
        wanted = [uuid for uuid in dict.fromkeys(uuids) if uuid not in self._held]
        if wanted:
            try:
                result = self._client.call("get_songs_by_uuid", uuids=wanted)
            except ClientError as failure:
                log.warning("could not resolve uuids: %s", failure)
                result = {"songs": []}
            for raw in result["songs"]:
                song = Song.from_dict(raw)
                self._held[song.uuid] = song
        return {uuid: self._held[uuid] for uuid in uuids if uuid in self._held}

    # Fetching

    def fetch_songs(self, peer_id: str, uuids: list[str] | None = None) -> None:
        self._fetch("peer_fetch_songs", PeerJobKind.FETCH_SONGS, peer_id, uuids)

    def fetch_playlists(self, peer_id: str, uuids: list[str] | None = None) -> None:
        self._fetch("peer_fetch_playlists", PeerJobKind.FETCH_PLAYLISTS, peer_id, uuids)

    def _fetch(self, method: str, kind: PeerJobKind, peer_id: str, uuids: list[str] | None) -> None:
        params = {"peer_id": peer_id}
        if uuids is not None:
            params["uuids"] = uuids
        try:
            job_id = self._client.call(method, **params)["job_id"]
        except ClientError as failure:
            self.failed.emit(str(failure))
            return
        # The row is drawn from the command, so the bar carries the fetch before the plan settles.
        self._jobs[job_id] = JobRow(job_id=job_id, kind=kind, peer_id=peer_id, state=PeerJobState.PLANNING)
        self.job_changed.emit(job_id)

    def cancel(self, job_id: str) -> None:
        try:
            self._client.call("peer_job_cancel", job_id=job_id)
        except ClientError as failure:
            self.failed.emit(str(failure))

    def dismiss(self, job_id: str) -> None:
        if self._jobs.pop(job_id, None) is not None:
            self.job_removed.emit(job_id)

    def forget(self, peer_id: str) -> None:
        try:
            self._client.call("peer_forget", peer_id=peer_id)
        except ClientError as failure:
            self.failed.emit(str(failure))
            return
        if self._active == peer_id:
            self.activate(None)

    # Pairing, whose failures belong to the dialog that asked

    def publish(self, seconds: int) -> None:
        self._take_window(self._client.call("pairing_publish", seconds=seconds))
        self.window_changed.emit()

    def conceal(self) -> None:
        self._take_window(self._client.call("pairing_conceal"))
        self.window_changed.emit()

    def reload_candidates(self) -> None:
        raw = self._client.call("pairing_candidates")["candidates"]
        self._candidates = [PairingCandidate.from_dict(entry) for entry in raw]
        self.candidates_changed.emit()

    def request(self, candidate: PairingCandidate) -> None:
        answer = self._client.call("pairing_request", core_id=candidate.id, address=candidate.address)
        self._session = answer["session_id"]
        self._state = PairingState(answer["state"])
        self._attempts_left = None
        self._code = None
        self._code_peer = candidate.name
        self.session_changed.emit()

    def submit_code(self, code: str) -> None:
        answer = self._client.call("pairing_submit_code", session_id=self._session, code=code)
        self._state = PairingState(answer["state"])
        self._attempts_left = answer.get("attempts_left")
        self.session_changed.emit()

    def cancel_pairing(self) -> None:
        if self._session is not None:
            self._client.call("pairing_cancel", session_id=self._session)
        self.clear_session()

    def clear_session(self) -> None:
        self._session = None
        self._state = None
        self._attempts_left = None
        self._code = None
        self._code_peer = None
        self.session_changed.emit()

    # Events

    def handle(self, event: Event) -> None:
        if event.type is EventType.PEER_CHANGED:
            self._on_peers(event.payload)
        elif event.type is EventType.PAIRING_WINDOW_CHANGED:
            self._take_window(event.payload)
            self.window_changed.emit()
        elif event.type is EventType.PAIRING_CANDIDATES_CHANGED:
            self._candidates = [PairingCandidate.from_dict(raw) for raw in event.payload["candidates"]]
            self.candidates_changed.emit()
        elif event.type is EventType.PAIRING_CODE_READY:
            self._on_code(event.payload)
        elif event.type is EventType.PAIRING_STATE_CHANGED:
            self._on_pairing_state(event.payload)
        elif event.type is EventType.PEER_JOB_PROGRESS:
            self._on_progress(event.payload)
        elif event.type is EventType.PEER_JOB_FINISHED:
            self._on_finished(event.payload)
        elif event.type is EventType.PEER_JOB_FAILED:
            self._on_job_failed(event.payload)
        elif event.type is EventType.LIBRARY_CHANGED:
            self._on_library_changed(event.payload)

    def _on_peers(self, payload: dict) -> None:
        self._peers = [PeerRecord.from_dict(raw) for raw in payload["peers"]]
        self.peers_changed.emit()
        if self._active is not None and self.peer(self._active) is None:
            self.activate(None)

    def _on_code(self, payload: dict) -> None:
        self._session = payload["session_id"]
        self._state = PairingState.AWAITING_CODE
        self._code = payload["code"]
        self._code_peer = payload.get("peer_name")
        self.session_changed.emit()
        self.code_ready.emit()

    def _on_pairing_state(self, payload: dict) -> None:
        if payload["session_id"] != self._session:
            return
        self._state = PairingState(payload["state"])
        self._attempts_left = payload.get("attempts_left")
        if self._state is not PairingState.AWAITING_CODE:
            self._code = None
        self.session_changed.emit()

    def _on_progress(self, payload: dict) -> None:
        row = self._row(payload["job_id"], PeerJobKind(payload["kind"]))
        if row is None:
            return
        row.apply_progress(payload)
        self.job_changed.emit(row.job_id)

    def _on_finished(self, payload: dict) -> None:
        job_id = payload["job_id"]
        if job_id in self._listings:
            self._take_listing(job_id, PeerJobKind(payload["kind"]), payload.get("result") or {})
            return
        row = self._row(job_id, PeerJobKind(payload["kind"]))
        if row is None:
            return
        row.state = PeerJobState(payload["state"])
        row.result = payload.get("result") or {}
        row.active = []
        self.job_changed.emit(job_id)
        # A fetch is what makes the snapshot stale.
        if row.state is PeerJobState.FINISHED and row.peer_id == self._active:
            self.refresh()

    def _on_job_failed(self, payload: dict) -> None:
        job_id = payload["job_id"]
        if job_id in self._listings:
            self._listings.pop(job_id)
            self._parts.clear()
            self.snapshot_failed.emit(self._message(payload.get("error")))
            return
        row = self._row(job_id, PeerJobKind(payload["kind"]))
        if row is None:
            return
        row.state = PeerJobState.FAILED
        row.error = self._message(payload.get("error"))
        row.active = []
        self.job_changed.emit(job_id)

    def _on_library_changed(self, payload: dict) -> None:
        # The uuid index answers what is held, which a write to any song can move.
        if payload.get("scope") != LibraryScope.STATISTICS.value:
            self._held.clear()

    def _take_listing(self, job_id: str, kind: PeerJobKind, result: dict) -> None:
        peer_id = self._listings.pop(job_id)
        if peer_id != self._active:
            return
        if kind is PeerJobKind.LIST_SONGS:
            self._parts["songs"] = [ListedSong.from_dict(raw) for raw in result.get("songs") or []]
        else:
            self._parts["playlists"] = [ListedPlaylist.from_dict(raw) for raw in result.get("playlists") or []]
        if self._parts.get("songs") is None or self._parts.get("playlists") is None:
            return
        self._snapshot = Snapshot(peer_id=peer_id, songs=self._parts["songs"], playlists=self._parts["playlists"])
        self._parts.clear()
        self.snapshot_changed.emit()

    def _row(self, job_id: str, kind: PeerJobKind) -> JobRow | None:
        """A job another client started is picked up off `peer_jobs`, which is what carries its peer."""
        row = self._jobs.get(job_id)
        if row is not None or kind not in FETCH_KINDS:
            return row
        try:
            jobs = [PeerJob.from_dict(raw) for raw in self._client.call("peer_jobs")["jobs"]]
        except ClientError as failure:
            log.warning("could not read jobs: %s", failure)
            return None
        job = next((entry for entry in jobs if entry.job_id == job_id), None)
        if job is None:
            return None
        self._jobs[job_id] = JobRow.from_job(job)
        return self._jobs[job_id]

    def _take_window(self, payload: dict) -> None:
        self._window_open = bool(payload.get("open"))
        self._expires_at = from_iso(payload.get("expires_at"))

    @staticmethod
    def _message(error: dict | None) -> str:
        if not error:
            return "the job failed"
        return f"{error.get('code', 'INTERNAL')}: {error.get('message', '')}".strip()
