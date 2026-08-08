from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QStyleOptionViewItem, QTableView

from frontends.qt.icons import glyph
from frontends.qt.models.song_table_model import QUEUE_COLUMN
from frontends.qt.style import ACCENT, DIM, PANEL_2
from frontends.qt.widgets.no_focus_delegate import NoFocusDelegate

BUTTON_COLUMN_WIDTH = 34
ICON_SIZE = 15
NO_CELL = (-1, -1)


class _RowDelegate(NoFocusDelegate):
    """A row-wide hover and a per-row button for use in the table: `::item:hover` is one cell."""

    def __init__(self, table: "SongTable"):
        super().__init__(table)
        self._table = table
        self._idle = glyph("queue_add", DIM, ICON_SIZE)
        self._lit = glyph("queue_add", ACCENT, ICON_SIZE)

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        hovered_row, hovered_column = self._table.hovered_cell()
        if index.row() == hovered_row:
            painter.fillRect(option.rect, QColor(PANEL_2))
        super().paint(painter, option, index)
        if index.column() != QUEUE_COLUMN or index.row() != hovered_row:
            return
        art = self._lit if hovered_column == QUEUE_COLUMN else self._idle
        centre = option.rect.center()
        painter.drawPixmap(centre.x() - art.width() // 2 + 1, centre.y() - art.height() // 2 + 1, art)


class SongTable(QTableView):
    """The library table"""

    queue_requested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self._hovered = NO_CELL
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(_RowDelegate(self))

    def hovered_cell(self) -> tuple[int, int]:
        return self._hovered

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        index = self.indexAt(event.position().toPoint())
        self._set_hovered((index.row(), index.column()) if index.isValid() else NO_CELL)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._set_hovered(NO_CELL)

    def mousePressEvent(self, event) -> None:
        # The button needs to own its cell. if it handed the press forward, it would also move the selection and arm a double click.
        if self._on_button(event) and event.button() is Qt.MouseButton.LeftButton:
            self.queue_requested.emit(self.indexAt(event.position().toPoint()).row())
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_button(event):
            return
        super().mouseDoubleClickEvent(event)

    def _on_button(self, event) -> bool:
        index = self.indexAt(event.position().toPoint())
        return index.isValid() and index.column() == QUEUE_COLUMN

    def _set_hovered(self, cell: tuple[int, int]) -> None:
        if cell == self._hovered:
            return
        previous, self._hovered = self._hovered, cell
        pointing = cell[1] == QUEUE_COLUMN
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if pointing else Qt.CursorShape.ArrowCursor)
        for row in {previous[0], cell[0]}:
            self._repaint_row(row)

    def _repaint_row(self, row: int) -> None:
        model = self.model()
        if row < 0 or model is None:
            return
        span = self.visualRect(model.index(row, 0)).united(self.visualRect(model.index(row, model.columnCount() - 1)))
        self.viewport().update(span)
