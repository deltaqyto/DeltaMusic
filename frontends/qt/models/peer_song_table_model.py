from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from frontends.qt.formatting import clock
from frontends.qt.models.song_table_model import HEADERS
from frontends.qt.style import DIM, DIMMER, FAINT, TEXT
from frontends.qt.types.snapshot import ListedSong


class PeerSongTableModel(QAbstractTableModel):
    """The active peer's snapshot. Weight is what this core can play: held, not held, or not servable."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ListedSong] = []

    def set_songs(self, rows: list[ListedSong]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def song_at(self, row: int) -> ListedSong | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def uuids(self) -> list[str]:
        return [listed.song.uuid for listed in self._rows]

    def action_glyph(self) -> str | None:
        """Activating a row already fetches, so the action column is empty."""
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation is not Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section].upper()
        if role == Qt.ItemDataRole.TextAlignmentRole:
            side = Qt.AlignmentFlag.AlignRight if section == 3 else Qt.AlignmentFlag.AlignLeft
            return int(side | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        listed = self.song_at(index.row())
        if listed is None:
            return None
        song = listed.song
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return str(index.row() + 1)
            if column == 1:
                return f"{song.name}   unavailable" if not song.available else song.name
            if column == 2:
                return song.artist
            if column == 3:
                return clock(song.duration)
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(self._colour(listed, column))

        return None

    @staticmethod
    def _colour(listed: ListedSong, column: int) -> str:
        if not listed.song.available:
            return FAINT
        if not listed.held:
            return DIMMER
        if column == 0:
            return DIMMER
        return TEXT if column == 1 else DIM
