from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from frontends.core_client import ClientError, CoreClient
from frontends.qt.widgets.app_dialog import AppDialog
from frontends.qt.widgets.no_focus_delegate import NoFocusDelegate
from protocol.types.shuffle_method import ShuffleMethod

NAV_WIDTH = 160
EDITOR_WIDTH = 360
NUMBER_WIDTH = 110
MEGABYTE = 1 << 20


@dataclass(frozen=True)
class Field:
    """A setting field. `kind` is [flag, choice, whole, decimal, text, list]."""

    key: str
    label: str
    kind: str
    options: tuple[tuple[str, str], ...] = ()
    low: float = 0
    high: float = 0
    scale: int = 1
    note: str = ""


SHUFFLE_METHODS = (
    (ShuffleMethod.TRUE_RANDOM.value, "True random"),
    (ShuffleMethod.AVOID_REPEATS.value, "Avoid repeats"),
)

SECTIONS: dict[str, tuple[Field, ...]] = {
    "Playback": (
        Field("shuffle_method", "Shuffle method", "choice", options=SHUFFLE_METHODS),
        Field("initial_volume", "Starting volume", "decimal", low=0, high=1),
    ),
    "Library": (
        Field("library_folder", "Library folder", "text"),
        Field("database_file", "Database file", "text"),
        Field("audio_extensions", "Audio extensions", "list"),
        Field("private_library", "Private library", "flag", note="Forgetting a song deletes its file."),
    ),
    "Devices": (
        Field("peer_enabled", "Enable peering", "flag"),
        Field("core_name", "Device name", "text"),
        Field("peer_port", "Peer port", "whole", low=1, high=65535),
        Field("visibility_seconds", "Visibility window (seconds)", "whole", low=1, high=86400),
        Field("max_concurrent_transfers", "Concurrent transfers", "whole", low=1, high=64),
        Field("transfer_space_reserve_bytes", "Free space reserve (MB)", "whole", low=0, high=1 << 20, scale=MEGABYTE),
    ),
    "Remote control": (
        Field("remote_control_enabled", "Enable remote control", "flag"),
        Field("remote_control_port", "Remote control port", "whole", low=1, high=65535),
    ),
    "General": (Field("frontends", "Frontends", "list"),),
}


def _editor(spec: Field) -> QWidget:
    if spec.kind == "flag":
        return QCheckBox()
    if spec.kind == "choice":
        box = QComboBox()
        for value, label in spec.options:
            box.addItem(label, value)
        box.setMaximumWidth(EDITOR_WIDTH)
        return box
    if spec.kind == "whole":
        spin = QSpinBox()
        spin.setRange(int(spec.low), int(spec.high))
    elif spec.kind == "decimal":
        spin = QDoubleSpinBox()
        spin.setRange(spec.low, spec.high)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
    else:
        line = QLineEdit()
        line.setMaximumWidth(EDITOR_WIDTH)
        return line
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(NUMBER_WIDTH)
    return spin


def _read(spec: Field, editor: QWidget) -> Any:
    if spec.kind == "flag":
        return editor.isChecked()
    if spec.kind == "choice":
        return editor.currentData()
    if spec.kind == "whole":
        return editor.value() * spec.scale
    if spec.kind == "decimal":
        return editor.value()
    if spec.kind == "list":
        return [item.strip() for item in editor.text().split(",") if item.strip()]
    return editor.text().strip()


def _write(spec: Field, editor: QWidget, value: Any) -> None:
    if spec.kind == "flag":
        editor.setChecked(value)
    elif spec.kind == "choice":
        editor.setCurrentIndex(max(0, editor.findData(value)))
    elif spec.kind == "whole":
        editor.setValue(value // spec.scale)
    elif spec.kind == "decimal":
        editor.setValue(value)
    elif spec.kind == "list":
        editor.setText(", ".join(value))
    else:
        editor.setText(value)


class SettingsDialog(AppDialog):

    def __init__(self, client: CoreClient, parent=None):
        super().__init__("Settings", parent)
        self._client = client
        self._fields: dict[str, Field] = {}
        self._editors: dict[str, QWidget] = {}
        # Track shown values to avoid rounding being interpreted as edits
        self._shown: dict[str, Any] = {}
        self.setMinimumSize(660, 420)
        self.resize(720, 460)

        self._nav = QListWidget()
        self._nav.setObjectName("sidebar")
        self._nav.setItemDelegate(NoFocusDelegate(self._nav))
        self._nav.setFixedWidth(NAV_WIDTH)
        self._stack = QStackedWidget()
        self._stack.setObjectName("dialogBody")
        for title, fields in SECTIONS.items():
            self._nav.addItem(title)
            self._stack.addWidget(self._page(fields))
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        self._note = QLabel("")
        self._note.setObjectName("dialogNote")
        self._note.setWordWrap(True)
        self._error = QLabel("")
        self._error.setObjectName("dialogError")
        self._error.setWordWrap(True)
        self._save = QPushButton("Save")
        self._save.clicked.connect(self._on_save)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)

        messages = QVBoxLayout()
        messages.setSpacing(2)
        messages.addWidget(self._note)
        messages.addWidget(self._error)
        footer = QHBoxLayout()
        footer.setContentsMargins(22, 6, 18, 14)
        footer.setSpacing(8)
        footer.addLayout(messages, 1)
        footer.addWidget(self._save)
        footer.addWidget(close)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        side.addWidget(self._stack, 1)
        side.addLayout(footer)

        row = QHBoxLayout(self.body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._nav)
        row.addLayout(side, 1)

    def _page(self, fields: tuple[Field, ...]) -> QWidget:
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for spec in fields:
            editor = _editor(spec)
            self._fields[spec.key] = spec
            self._editors[spec.key] = editor
            label = QLabel(spec.label)
            label.setObjectName("settingLabel")
            form.addRow(label, self._with_note(editor, spec.note) if spec.note else editor)

        page = QWidget()
        page.setObjectName("dialogBody")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column = QVBoxLayout(page)
        column.setContentsMargins(22, 18, 22, 8)
        column.addLayout(form)
        column.addStretch(1)
        return page

    @staticmethod
    def _with_note(editor: QWidget, text: str) -> QWidget:
        cell = QWidget()
        cell.setObjectName("settingCell")
        column = QVBoxLayout(cell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(editor)
        note = QLabel(text)
        note.setObjectName("dialogNote")
        column.addWidget(note)
        return cell

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._note.setText("")
        self._error.setText("")
        try:
            self._show(self._client.call("get_settings")["settings"])
        except ClientError as failure:
            self._error.setText(failure.error.message)

    def _show(self, settings: dict[str, Any]) -> None:
        for key, spec in self._fields.items():
            editor = self._editors[key]
            _write(spec, editor, settings[key])
            self._shown[key] = _read(spec, editor)

    def _on_save(self) -> None:
        changes = {}
        for key, spec in self._fields.items():
            value = _read(spec, self._editors[key])
            if value != self._shown[key]:
                changes[key] = value
        if not changes:
            self._note.setText("Nothing to save.")
            return
        try:
            result = self._client.call("update_settings", values=changes)
        except ClientError as failure:
            self._note.setText("")
            self._error.setText(failure.error.message)
            return
        self._error.setText("")
        self._show(result["settings"])
        pending = ", ".join(self._fields[key].label.lower() for key in result["restart_required"])
        self._note.setText(f"Saved. Restart to apply: {pending}." if pending else "Saved.")
