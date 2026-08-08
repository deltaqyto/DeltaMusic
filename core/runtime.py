import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, TypeVar

from core.event_bus import EventBus
from core.library.library import Library
from core.library.scanner import Scanner
from core.playback.controller import PlaybackController
from protocol.types.event_type import EventType
from protocol.types.scan_phase import ScanPhase

log = logging.getLogger(__name__)

T = TypeVar("T")

HEARTBEAT_SECONDS = 1.0
QUEUE_EVERY_NTH_HEARTBEAT = 10
PROGRESS_EVERY = 25


class Runtime:
    """Commands from any transport and reports from the engine thread queue here for handling
    """

    def __init__(self, library: Library, controller: PlaybackController, bus: EventBus, extensions: list[str]):
        self._library = library
        self._controller = controller
        self._bus = bus
        self._extensions = extensions

        self._jobs: queue.Queue[tuple[Callable[[], Any], Future | None]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="core-runtime", daemon=True)
        self._scan_thread: threading.Thread | None = None
        self._stopping = threading.Event()

        self._beats = 0
        self._queue_revision_sent = -1

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._jobs.put((lambda: None, None))
        self._thread.join(timeout=5.0)

    def call(self, work: Callable[[], T]) -> T:
        """Runs `work` on the runtime thread and waits for it. Exceptions surface to the caller."""
        if threading.current_thread() is self._thread:
            return work()
        pending: Future = Future()
        self._jobs.put((work, pending))
        return pending.result()

    def post(self, work: Callable[[], Any]) -> None:
        """Hands `work` to the runtime without waiting. The engine thread reports this way."""
        self._jobs.put((work, None))

    def scan_later(self) -> None:
        """Walks and probes off the runtime thread, then applies the plan on it."""
        self._scan_thread = threading.Thread(target=self._scan, name="core-scan", daemon=True)
        self._scan_thread.start()

    def _run(self) -> None:
        next_beat = time.monotonic() + HEARTBEAT_SECONDS
        while not self._stopping.is_set():
            timeout = max(0.0, next_beat - time.monotonic())
            try:
                work, pending = self._jobs.get(timeout=timeout)
            except queue.Empty:
                self._beat()
                next_beat = time.monotonic() + HEARTBEAT_SECONDS
                continue
            self._apply(work, pending)
            if time.monotonic() >= next_beat:
                self._beat()
                next_beat = time.monotonic() + HEARTBEAT_SECONDS

    def _apply(self, work: Callable[[], Any], pending: Future | None) -> None:
        if pending is None:
            try:
                work()
            except Exception:
                log.exception("a posted job failed")
            return
        if not pending.set_running_or_notify_cancel():
            return
        try:
            pending.set_result(work())
        except BaseException as failure:
            pending.set_exception(failure)

    def _beat(self) -> None:
        self._beats += 1
        playback = self._controller.playback_state()
        payload: dict[str, Any] = {"playback": playback.to_dict()}
        moved = playback.queue_revision != self._queue_revision_sent
        if moved or self._beats % QUEUE_EVERY_NTH_HEARTBEAT == 0:
            payload["queue"] = self._controller.queue_state().to_dict()
            self._queue_revision_sent = playback.queue_revision
        self._bus.publish(EventType.HEARTBEAT, payload)

    def _scan(self) -> None:
        songs = self.call(self._library.snapshot_songs)
        last_reported = [0]

        def on_progress(scanned: int, total: int, phase: ScanPhase) -> None:
            if phase is not ScanPhase.DONE and scanned - last_reported[0] < PROGRESS_EVERY:
                return
            last_reported[0] = scanned
            self.post(
                lambda: self._bus.publish(
                    EventType.SCAN_PROGRESS, {"scanned": scanned, "total": total, "phase": phase.value}
                )
            )

        scanner = Scanner(self._library.root, self._extensions, on_progress)
        try:
            plan = scanner.plan(songs)
        except Exception:
            log.exception("the startup scan failed")
            return
        self.post(lambda: self._library.apply_scan_plan(plan))
