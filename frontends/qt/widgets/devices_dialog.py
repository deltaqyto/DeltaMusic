from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from frontends.core_client import ClientError
from frontends.qt.formatting import clock
from frontends.qt.peer_book import PeerBook
from frontends.qt.widgets.app_dialog import AppDialog
from frontends.qt.widgets.no_focus_delegate import NoFocusDelegate
from protocol.types.pairing_state import PairingState

PUBLISH_SECONDS = 300
CANDIDATE = Qt.ItemDataRole.UserRole
STATE_LINES = {
    PairingState.AWAITING_CODE: "waiting on the code",
    PairingState.PAIRED: "paired",
    PairingState.REFUSED: "the code did not match",
    PairingState.CANCELLED: "cancelled",
}


class DevicesDialog(AppDialog):
    """The window, the candidates and the exchange. What it drives is `local` only, and what it holds lives in `PeerBook`."""

    def __init__(self, book: PeerBook, parent=None):
        super().__init__("Devices", parent)
        self._book = book
        # The candidate list grows, so this one keeps its handles and takes a floor instead of a fit.
        self.setMinimumSize(460, 460)
        self.resize(520, 520)

        column = QVBoxLayout(self.body)
        column.setContentsMargins(18, 14, 18, 16)
        column.setSpacing(8)

        self._window_line = QLabel("")
        self._publish = QPushButton("Make visible")
        self._publish.clicked.connect(self._on_publish)
        window_row = QHBoxLayout()
        window_row.addWidget(self._window_line, 1)
        window_row.addWidget(self._publish)

        self._code = QLabel("")
        self._code.setObjectName("code")
        self._code_note = QLabel("")
        self._code_note.setObjectName("dialogNote")

        self._candidates = QListWidget()
        self._candidates.setObjectName("sidebar")
        self._candidates.setItemDelegate(NoFocusDelegate(self._candidates))
        self._candidates.currentItemChanged.connect(lambda *_: self._show_buttons())

        self._pair = QPushButton("Pair")
        self._pair.clicked.connect(self._on_pair)
        candidate_row = QHBoxLayout()
        candidate_row.addStretch(1)
        candidate_row.addWidget(self._pair)

        self._session_line = QLabel("")
        self._session_line.setObjectName("dialogNote")
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("code")
        self._entry.setMaxLength(4)
        self._entry.setFixedWidth(90)
        self._entry.returnPressed.connect(self._on_submit)
        self._submit = QPushButton("Submit")
        self._submit.clicked.connect(self._on_submit)
        self._drop = QPushButton("Cancel")
        self._drop.clicked.connect(self._on_cancel)
        session_row = QHBoxLayout()
        session_row.addWidget(self._entry)
        session_row.addWidget(self._submit)
        session_row.addStretch(1)
        session_row.addWidget(self._drop)

        self._error = QLabel("")
        self._error.setObjectName("dialogError")
        self._error.setWordWrap(True)

        column.addWidget(self._title("VISIBILITY"))
        column.addLayout(window_row)
        column.addWidget(self._code)
        column.addWidget(self._code_note)
        column.addWidget(self._title("NEARBY"))
        column.addWidget(self._candidates, 1)
        column.addLayout(candidate_row)
        column.addWidget(self._title("PAIRING"))
        column.addWidget(self._session_line)
        column.addLayout(session_row)
        column.addWidget(self._error)

        book.window_changed.connect(self._show_window)
        book.candidates_changed.connect(self._show_candidates)
        book.session_changed.connect(self._show_session)

        self._countdown = QTimer(self)
        self._countdown.timeout.connect(self._show_window)
        self._countdown.start(1000)

    @staticmethod
    def _title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("paneTitle")
        return label

    # Drawing

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._error.setText("")
        self._guarded(self._book.reload_candidates)
        self._show_window()
        self._show_session()

    def _show_window(self) -> None:
        if not self._book.window_open:
            self._window_line.setText("This device is not visible for pairing.")
            self._publish.setText("Make visible")
        else:
            self._window_line.setText(f"Visible for {clock(self._remaining())}.")
            self._publish.setText("Hide")

    def _remaining(self) -> float:
        expires_at = self._book.expires_at
        if expires_at is None:
            return 0.0
        return max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())

    def _show_candidates(self) -> None:
        chosen = self._chosen()
        self._candidates.clear()
        for candidate in self._book.candidates():
            state = "open" if candidate.pairing else "closed"
            item = QListWidgetItem(f"{candidate.name}    {candidate.address}    {state}")
            item.setData(CANDIDATE, candidate.id)
            self._candidates.addItem(item)
            if chosen is not None and candidate.id == chosen.id:
                self._candidates.setCurrentItem(item)
        self._show_buttons()

    def _show_buttons(self) -> None:
        candidate = self._chosen()
        self._pair.setEnabled(candidate is not None and candidate.pairing)

    def _show_session(self) -> None:
        live = self._book.session is not None
        state = self._book.session_state
        line = STATE_LINES.get(state, "") if state is not None else ""
        attempts = self._book.attempts_left
        if attempts is not None and state is PairingState.REFUSED:
            line = f"{line}, {attempts} attempts left"
        peer = self._book.code_peer
        self._session_line.setText(f"{peer}: {line}" if peer and line else line or "No pairing in progress.")
        for widget in (self._entry, self._submit, self._drop):
            widget.setEnabled(live)
        code = self._book.code
        self._code.setText(code or "")
        self._code.setVisible(bool(code))
        self._code_note.setText(f"Read this code to {peer}." if code else "")
        self._code_note.setVisible(bool(code))
        if state is PairingState.PAIRED:
            self._entry.clear()
        self._show_buttons()

    def _chosen(self):
        item = self._candidates.currentItem()
        if item is None:
            return None
        return next((entry for entry in self._book.candidates() if entry.id == item.data(CANDIDATE)), None)

    # Acting

    def _on_publish(self) -> None:
        if self._book.window_open:
            self._guarded(self._book.conceal)
        else:
            self._guarded(lambda: self._book.publish(PUBLISH_SECONDS))

    def _on_pair(self) -> None:
        candidate = self._chosen()
        if candidate is not None:
            self._guarded(lambda: self._book.request(candidate))

    def _on_submit(self) -> None:
        code = self._entry.text().strip()
        if code:
            self._guarded(lambda: self._book.submit_code(code))

    def _on_cancel(self) -> None:
        self._guarded(self._book.cancel_pairing)

    def _guarded(self, action) -> bool:
        """A command that fails inside this dialog is shown here."""
        try:
            action()
        except ClientError as failure:
            self._error.setText(str(failure))
            return False
        self._error.setText("")
        return True
