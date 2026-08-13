from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QStyleOptionViewItem, QTableView

from frontends.qt.icons import glyph
from frontends.qt.models.song_table_model import ACTION_COLUMN
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
        self._art: dict[tuple[str, str], QPixmap] = {}

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        hovered_row, hovered_column = self._table.hovered_cell()
        if index.row() == hovered_row:
            painter.fillRect(option.rect, QColor(PANEL_2))
        super().paint(painter, option, index)
        name = self._table.action_glyph()
        if name is None or index.column() != ACTION_COLUMN or index.row() != hovered_row:
            return
        art = self._pixmap(name, ACCENT if hovered_column == ACTION_COLUMN else DIM)
        centre = option.rect.center()
        painter.drawPixmap(centre.x() - art.width() // 2 + 1, centre.y() - art.height() // 2 + 1, art)

    def _pixmap(self, name: str, colour: str) -> QPixmap:
        key = (name, colour)
        if key not in self._art:
            self._art[key] = glyph(name, colour, ICON_SIZE)
        return self._art[key]


class SongTable(QTableView):
    """The track table. Its action column takes its glyph and its meaning from whichever model is set."""

    action_requested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self._hovered = NO_CELL
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(_RowDelegate(self))

    def hovered_cell(self) -> tuple[int, int]:
        return self._hovered

    def action_glyph(self) -> str | None:
        model = self.model()
        return model.action_glyph() if model is not None else None

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
            self.action_requested.emit(self.indexAt(event.position().toPoint()).row())
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_button(event):
            return
        super().mouseDoubleClickEvent(event)

    def _on_button(self, event) -> bool:
        index = self.indexAt(event.position().toPoint())
        return index.isValid() and index.column() == ACTION_COLUMN and self.action_glyph() is not None

    def _set_hovered(self, cell: tuple[int, int]) -> None:
        if cell == self._hovered:
            return
        previous, self._hovered = self._hovered, cell
        pointing = cell[1] == ACTION_COLUMN and self.action_glyph() is not None
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if pointing else Qt.CursorShape.ArrowCursor)
        for row in {previous[0], cell[0]}:
            self._repaint_row(row)

    def _repaint_row(self, row: int) -> None:
        model = self.model()
        if row < 0 or model is None:
            return
        span = self.visualRect(model.index(row, 0)).united(self.visualRect(model.index(row, model.columnCount() - 1)))
        self.viewport().update(span)
