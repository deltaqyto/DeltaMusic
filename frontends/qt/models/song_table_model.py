from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from frontends.qt.formatting import clock
from frontends.qt.style import ACCENT, DIM, DIMMER, TEXT
from protocol.types.song import Song

HEADERS = ["#", "Title", "Artist", "Time", ""]
QUEUE_COLUMN = 4
"""Holds no data. The delegate paints a queue button here on the hovered row."""


class SongTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._songs: list[Song] = []
        self._playing: int | None = None

    def set_songs(self, songs: list[Song]) -> None:
        self.beginResetModel()
        self._songs = songs
        self.endResetModel()

    def set_playing(self, song_id: int | None) -> None:
        if song_id == self._playing:
            return
        self._playing = song_id
        if self._songs:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._songs) - 1, len(HEADERS) - 1))

    def song_at(self, row: int) -> Song | None:
        return self._songs[row] if 0 <= row < len(self._songs) else None

    def song_ids(self) -> list[int]:
        return [song.id for song in self._songs]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._songs)

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
        song = self.song_at(index.row())
        if song is None:
            return None
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return str(index.row() + 1)
            if column == 1:
                return f"{song.name}   missing" if not song.found_on_disk else song.name
            if column == 2:
                return song.artist
            if column == 3:
                return clock(song.duration)
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(self._colour(song, column))

        return None

    def _colour(self, song: Song, column: int) -> str:
        if not song.found_on_disk:
            return DIMMER
        if song.id == self._playing:
            return ACCENT if column in (0, 1) else DIM
        if column == 0:
            return DIMMER
        return TEXT if column == 1 else DIM
