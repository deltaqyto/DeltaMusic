from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .encoding import save_capture
from .types import CaptureResult, TrackMetadata

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SaveJob:
    capture: CaptureResult
    metadata: TrackMetadata
    destination: Path
    filename_template: str
    container: str
    subtype: str
    overwrite: bool
    dither: bool = True


class SaveWorker:
    """A single background thread that encodes captures to disk.
    Done off-thread to seamlessly handle back-back recording
    """

    def __init__(self, max_pending: int = 8) -> None:
        self._queue: "queue.Queue[Optional[SaveJob]]" = queue.Queue(maxsize=max_pending)
        self._thread: Optional[threading.Thread] = None
        self._saved = 0
        self._failed = 0

    @property
    def saved(self) -> int:
        return self._saved

    @property
    def failed(self) -> int:
        return self._failed

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="acquisition-saver", daemon=True
        )
        self._thread.start()

    def submit(self, job: SaveJob) -> bool:
        """Queue a capture for writing, returning False if the queue is full (should never happen on any modern device, though)"""
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            self._failed += 1
            log.error(
                "save queue full, dropping %r - the encoder is not keeping up",
                job.metadata.title,
            )
            return False

    def close(self, timeout: float = 60.0) -> None:
        """Drain the queue and stop the thread."""
        if self._thread is None:
            return
        pending = self.pending
        if pending:
            log.info("finishing %d queued save(s)...", pending)
        self._queue.put(None)
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.warning("saver did not finish within %.0fs; some audio was lost", timeout)
        self._thread = None

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self._write(job)
            finally:
                self._queue.task_done()

    def _write(self, job: SaveJob) -> None:
        try:
            result = save_capture(
                job.capture,
                job.metadata,
                job.destination,
                filename_template=job.filename_template,
                overwrite=job.overwrite,
                container=job.container,
                subtype=job.subtype,
                dither=job.dither,
            )
        except FileExistsError as exc:
            self._failed += 1
            log.warning("not saving %r: %s", job.metadata.title, exc)
            return
        except Exception:
            self._failed += 1
            log.exception("failed to save %r", job.metadata.title)
            return

        self._saved += 1
        log.info(
            "saved %s (%.1fs, peak %.2f%s)",
            result.path.name,
            result.duration_seconds,
            result.peak,
            f", {result.xruns} dropout(s)" if result.xruns else "",
        )
