from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from frontends.qt.formatting import bytes_size
from frontends.qt.icons import icon
from frontends.qt.peer_book import PeerBook
from frontends.qt.types.job_row import JobRow
from frontends.qt.widgets.elided_label import ElidedLabel
from protocol.types.peer_job_kind import PeerJobKind
from protocol.types.peer_job_state import PeerJobState

DISMISS_MS = 10000
KIND_LABELS = {PeerJobKind.FETCH_SONGS: "tracks", PeerJobKind.FETCH_PLAYLISTS: "playlists"}
STATE_LABELS = {
    PeerJobState.PLANNING: "planning",
    PeerJobState.RUNNING: "downloading",
    PeerJobState.FINISHED: "done",
    PeerJobState.FAILED: "failed",
    PeerJobState.CANCELLED: "cancelled",
}


class _Row(QWidget):
    """One fetch: the peer, the kind, items and bytes, a cancel, and the transfers under it."""

    def __init__(self, book: PeerBook, job_id: str):
        super().__init__()
        self.setObjectName("jobRow")
        self._book = book
        self._job_id = job_id
        self._open = False

        self._expander = self._button("chevron_right", "Show transfers")
        self._expander.clicked.connect(self._toggle)
        self._title = ElidedLabel("")
        self._title.setObjectName("jobTitle")
        self._items = QLabel("")
        self._items.setObjectName("jobCount")
        self._bytes = QLabel("")
        self._bytes.setObjectName("jobCount")
        self._stop = self._button("close", "Cancel")
        self._stop.clicked.connect(self._on_stop)

        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(self._expander)
        row.addWidget(self._title, 1)
        row.addWidget(self._items)
        row.addWidget(self._bytes)
        row.addWidget(self._stop)

        self._detail = QLabel("")
        self._detail.setObjectName("jobDetail")
        self._detail.setWordWrap(True)
        self._detail.setVisible(False)

        column = QVBoxLayout(self)
        column.setContentsMargins(14, 5, 12, 5)
        column.setSpacing(3)
        column.addWidget(head)
        column.addWidget(self._detail)

        self._dismissal = QTimer(self)
        self._dismissal.setSingleShot(True)
        self._dismissal.timeout.connect(lambda: self._book.dismiss(self._job_id))

    @staticmethod
    def _button(name: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("iconButton")
        button.setIcon(icon(name))
        button.setToolTip(tip)
        button.setFixedWidth(22)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def show_job(self, job: JobRow) -> None:
        peer = self._book.peer_name(job.peer_id)
        kind = KIND_LABELS.get(job.kind, job.kind.value)
        self._title.setText(f"{peer}    {STATE_LABELS[job.state]} {kind}")
        self._items.setText(f"{job.items_done}/{job.items_total}" if job.items_total else "")
        self._bytes.setText(f"{bytes_size(job.bytes_done)} / {bytes_size(job.bytes_total)}" if job.bytes_total else "")
        self._stop.setToolTip("Dismiss" if job.settled else "Cancel")
        # A result naming what it could not do is where TRANSFER_FAILED is read, so it opens itself.
        if job.settled and not job.clean:
            self._set_open(True)
        if self._open:
            self._detail.setText(self._describe(job))
        if job.settled and job.clean:
            self._dismissal.start(DISMISS_MS)

    def _describe(self, job: JobRow) -> str:
        if job.error is not None:
            return job.error
        if not job.settled:
            return self._transfers(job) or "no transfers running"
        return self._summary(job)

    def _transfers(self, job: JobRow) -> str:
        held = self._book.resolve([transfer.uuid for transfer in job.active])
        lines = []
        for transfer in job.active:
            song = held.get(transfer.uuid)
            name = song.name if song is not None else transfer.uuid
            lines.append(f"{name}   {bytes_size(transfer.bytes_done)} / {bytes_size(transfer.bytes_total)}")
        return "\n".join(lines)

    @staticmethod
    def _summary(job: JobRow) -> str:
        result = job.result or {}
        parts = [
            f"{result.get('songs_inserted', 0)} songs added",
            f"{result.get('files_received', 0)} files, {bytes_size(result.get('bytes_received', 0))}",
        ]
        made, updated = result.get("playlists_created", 0), result.get("playlists_updated", 0)
        if made or updated:
            parts.append(f"{made} playlists made, {updated} updated")
        if job.unknown:
            parts.append(f"{len(job.unknown)} not carried by the peer")
        for entry in job.given_up:
            parts.append(f"{entry.get('uuid', '')} given up: {entry.get('error', 'TRANSFER_FAILED')}")
        return "\n".join(parts)

    def _toggle(self) -> None:
        self._set_open(not self._open)
        job = self._book.job(self._job_id)
        if job is not None:
            self.show_job(job)

    def _set_open(self, opened: bool) -> None:
        self._open = opened
        self._detail.setVisible(opened)
        self._expander.setIcon(icon("chevron_down" if opened else "chevron_right"))

    def _on_stop(self) -> None:
        job = self._book.job(self._job_id)
        if job is not None and job.settled:
            self._book.dismiss(self._job_id)
            return
        self._book.cancel(self._job_id)


class JobBar(QWidget):
    """The fetches of this run, seeded from `peer_jobs` and maintained by `PeerJobProgress`."""

    def __init__(self, book: PeerBook):
        super().__init__()
        self.setObjectName("jobBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._book = book
        self._rows: dict[str, _Row] = {}

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)

        book.job_changed.connect(self._on_changed)
        book.job_removed.connect(self._on_removed)
        self.setVisible(False)

    def _on_changed(self, job_id: str) -> None:
        job = self._book.job(job_id)
        if job is None:
            return
        row = self._rows.get(job_id)
        if row is None:
            row = _Row(self._book, job_id)
            self._rows[job_id] = row
            self._column.addWidget(row)
        row.show_job(job)
        self.setVisible(True)

    def _on_removed(self, job_id: str) -> None:
        row = self._rows.pop(job_id, None)
        if row is not None:
            self._column.removeWidget(row)
            row.deleteLater()
        self.setVisible(bool(self._rows))
