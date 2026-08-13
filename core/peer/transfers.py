import hashlib
import logging
import threading
from collections import deque
from functools import partial
from collections.abc import Callable
from http import HTTPStatus
from http.client import HTTPException
from pathlib import Path
from typing import Any

from core.library.library import Library
from core.library.tags import write_uuid
from core.peer.link import PeerLink
from core.runtime import Runtime
from protocol.errors import ProtocolError, transfer_failed
from protocol.types.error_code import ErrorCode
from protocol.types.peer_song import PeerSong

log = logging.getLogger(__name__)

CHUNK = 1 << 16
ATTEMPTS = 3
PART_SUFFIX = ".part"
NAME_ATTEMPTS = 1000

Report = Callable[[str, str, int, str | None], None]


class Transfers:
    """The transfer queue and the threads under it. One entry per track file, deduplicated by uuid across jobs."""

    def __init__(self, library: Library, runtime: Runtime, workers: int):
        self._library = library
        self._runtime = runtime
        self._workers = max(1, workers)
        self._lock = threading.Condition()
        self._pending: deque[_Transfer] = deque()
        self._live: dict[str, _Transfer] = {}
        self._threads: list[threading.Thread] = []
        self._stopping = False
        self._report: Report = lambda job_id, uuid, received, error: None

    def report_to(self, report: Report) -> None:
        """Whoever is waiting on a transfer hears about it here, once per waiting job."""
        self._report = report

    def start(self) -> None:
        if self._threads:
            return
        for number in range(self._workers):
            thread = threading.Thread(target=self._work, name=f"peer-transfer-{number + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._pending.clear()
            self._lock.notify_all()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()

    def submit(self, job_id: str, link: PeerLink, song: PeerSong) -> None:
        """A file to pull. A job asking for one already moving joins it rather than starting a second."""
        with self._lock:
            held = self._live.get(song.uuid)
            if held is not None:
                held.waiters.add(job_id)
                return
            transfer = _Transfer(song, link, job_id)
            self._live[song.uuid] = transfer
            self._pending.append(transfer)
            self._lock.notify()

    def drop(self, job_id: str) -> None:
        """A cancelled job stops waiting. A transfer with nothing waiting on it is dropped, running or not."""
        with self._lock:
            for transfer in list(self._live.values()):
                transfer.waiters.discard(job_id)
                if transfer.waiters:
                    continue
                transfer.dropped = True
                if transfer.running:
                    continue
                if transfer in self._pending:
                    self._pending.remove(transfer)
                self._live.pop(transfer.song.uuid, None)

    def outstanding(self) -> int:
        """What the queue has still to move, queued and running both, counted once per track."""
        with self._lock:
            return sum(max(transfer.bytes_total - transfer.bytes_done, 0) for transfer in self._live.values())

    def active_for(self, job_id: str) -> list[dict[str, Any]]:
        """The transfers running for one job, as a progress event carries them."""
        with self._lock:
            return [
                {"uuid": transfer.song.uuid, "bytes_done": transfer.bytes_done, "bytes_total": transfer.bytes_total}
                for transfer in self._live.values()
                if transfer.running and job_id in transfer.waiters
            ]

    # Internals

    def _work(self) -> None:
        while True:
            with self._lock:
                while not self._pending and not self._stopping:
                    self._lock.wait()
                if self._stopping:
                    return
                transfer = self._pending.popleft()
                transfer.running = True
            self._carry(transfer)

    def _carry(self, transfer: "_Transfer") -> None:
        error: str | None = None
        received = 0
        try:
            received = self._pull(transfer)
        except ProtocolError as failure:
            error = failure.error.code.value
            log.warning("gave up on %s: %s", transfer.song.uuid, failure)
        except Exception:
            error = ErrorCode.TRANSFER_FAILED.value
            log.exception("gave up on %s", transfer.song.uuid)
        with self._lock:
            waiters = set(transfer.waiters)
            dropped = transfer.dropped
            self._live.pop(transfer.song.uuid, None)
        if dropped:
            return
        for job_id in waiters:
            self._report(job_id, transfer.song.uuid, received, error)

    def _pull(self, transfer: "_Transfer") -> int:
        """The file, resuming by `Range` on a retry. Gives back the bytes moved, and raises when the retries run out."""
        # Two transfers can be handed the same relative location by two peers, so the part file is claimed under the lock.
        with self._lock:
            destination = _free_path(self._library.root / _under_library(transfer.song))
            part = destination.with_name(destination.name + PART_SUFFIX)
            part.parent.mkdir(parents=True, exist_ok=True)
            part.touch(exist_ok=True)
        moved = 0

        for attempt in range(ATTEMPTS):
            if transfer.dropped or self._stopping:
                return moved
            start = part.stat().st_size if part.exists() else 0
            transfer.bytes_done = start
            try:
                digest, written = self._append(transfer, part, start)
            except (HTTPException, OSError, ProtocolError) as failure:
                # A body that stops part way through is an incomplete read, which is the case the retries are for.
                log.info("attempt %d on %s did not finish: %s", attempt + 1, transfer.song.uuid, failure)
                # A resume point the sender would not serve is thrown away, so the retry starts from nothing.
                if start and _nothing_written(part, start):
                    part.unlink(missing_ok=True)
                continue
            moved += written
            if transfer.dropped or self._stopping:
                return moved
            if not self._whole(part, digest, transfer.song.file_size):
                log.info("%s did not verify, so it is pulled again", transfer.song.uuid)
                part.unlink(missing_ok=True)
                continue

            # The stamp changes the file, which is why the digest is checked first.
            write_uuid(part, transfer.song.uuid)
            # The part file beside it is this one, so only the destination itself is asked about.
            landing = destination if not destination.exists() else _free_path(destination)
            part.replace(landing)
            size = landing.stat().st_size
            location = landing.relative_to(self._library.root).as_posix()
            self._runtime.call(partial(self._library.place_file, transfer.song.uuid, location, size))
            return moved

        raise transfer_failed(f"{transfer.song.name} would not come across", uuid=transfer.song.uuid)

    def _append(self, transfer: "_Transfer", part: Path, start: int) -> tuple[str, int]:
        """One pass at the body, onto the end of the part file. Gives back the sender's digest and what this pass wrote."""
        with transfer.link.track(transfer.song.uuid, start) as (response, digest):
            resumed = start > 0 and response.status == HTTPStatus.PARTIAL_CONTENT
            transfer.bytes_total = _total_of(response, transfer.song.file_size)
            written = 0
            base = start if resumed else 0
            with part.open("ab" if resumed else "wb") as handle:
                while not transfer.dropped and not self._stopping:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    written += len(block)
                    transfer.bytes_done = base + written
            return digest, written

    @staticmethod
    def _whole(part: Path, digest: str, expected_size: int) -> bool:
        """The digest when the sender gave one, and the size it advertised when it did not."""
        if not part.exists():
            return False
        if digest:
            return _digest_of(part) == digest
        return part.stat().st_size == expected_size


class _Transfer:
    """One track file moving from a peer to this core."""

    def __init__(self, song: PeerSong, link: PeerLink, job_id: str):
        self.song = song
        self.link = link
        self.waiters: set[str] = {job_id}
        self.bytes_done = 0
        self.bytes_total = song.file_size
        self.running = False
        self.dropped = False


def _under_library(song: PeerSong) -> Path:
    """The sender's location, with anything that would climb out of the library folder taken out."""
    parts = [
        part
        for part in Path(song.location or "").parts
        if part not in ("", ".", "..", "/", "\\") and ":" not in part
    ]
    return Path(*parts) if parts else Path(f"{song.name} ~~ {song.artist}")


def _free_path(path: Path) -> Path:
    """The path itself while nothing holds it, else the first `name (2)` that is free."""
    if _vacant(path):
        return path
    for attempt in range(2, NAME_ATTEMPTS):
        candidate = path.with_name(f"{path.stem} ({attempt}){path.suffix}")
        if _vacant(candidate):
            return candidate
    raise transfer_failed(f"no free name beside {path}")


def _vacant(path: Path) -> bool:
    return not path.exists() and not path.with_name(path.name + PART_SUFFIX).exists()


def _nothing_written(part: Path, start: int) -> bool:
    return part.exists() and part.stat().st_size <= start


def _total_of(response: Any, advertised: int) -> int:
    """What the whole file measures, off `Content-Range` when the answer carries one."""
    carried = response.headers.get("Content-Range") or ""
    _, _, total = carried.partition("/")
    return int(total) if total.isdigit() else advertised


def _digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()
