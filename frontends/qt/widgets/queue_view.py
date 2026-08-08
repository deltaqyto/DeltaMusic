from collections.abc import Callable

from PyQt6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from frontends.qt.icons import glyph
from frontends.qt.style import ACCENT, COLUMN_HEAD_HEIGHT, DIM, DIMMER, MUTED, PANEL_2, TEXT
from protocol.types.queue_entry import QueueEntry
from protocol.types.queue_origin import QueueOrigin
from protocol.types.song import Song

ENTRY_ID = Qt.ItemDataRole.UserRole
LABEL = Qt.ItemDataRole.UserRole + 1
NAME = Qt.ItemDataRole.UserRole + 2
ARTIST = Qt.ItemDataRole.UserRole + 3
HEAD_COLOUR = Qt.ItemDataRole.UserRole + 4
TAIL_COLOUR = Qt.ItemDataRole.UserRole + 5

QUEUE_WIDTH = 330
ROW_HEIGHT = 46
GRIP_WIDTH = 26
CLOSE_WIDTH = 26
LINE_GAP = 2
GRIP_SIZE = 15
CLOSE_SIZE = 13

GRIP = "grip"
CLOSE = "close"
BODY = "body"

Resolver = Callable[[list[int]], dict[int, Song]]


class _QueueDelegate(QStyledItemDelegate):
    """The queue needs to show two lines of text between a drag handle and a remove button.
    None of that is expressible as item text, so its a delegate instead. :( """

    def __init__(self, view: "_QueueList"):
        super().__init__(view)
        self._view = view
        self._grip = glyph("grip", DIMMER, GRIP_SIZE)
        self._grip_lit = glyph("grip", MUTED, GRIP_SIZE)
        self._close = glyph("close", DIMMER, CLOSE_SIZE)
        self._close_lit = glyph("close", ACCENT, CLOSE_SIZE)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row = index.row()
        hovered = row == self._view.hovered_row()
        if hovered or option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(PANEL_2))

        rect = option.rect
        metrics = QFontMetrics(option.font)
        width = max(20, rect.width() - GRIP_WIDTH - CLOSE_WIDTH)
        block = metrics.height() * 2 + LINE_GAP
        top = rect.top() + (rect.height() - block) // 2
        left = rect.left() + GRIP_WIDTH

        head = f"{index.data(LABEL)}   {index.data(NAME)}"
        painter.setPen(QColor(index.data(HEAD_COLOUR)))
        self._draw(painter, metrics, QRect(left, top, width, metrics.height()), head)
        painter.setPen(QColor(index.data(TAIL_COLOUR)))
        bottom = QRect(left, top + metrics.height() + LINE_GAP, width, metrics.height())
        self._draw(painter, metrics, bottom, index.data(ARTIST))

        if not hovered:
            return
        zone = self._view.hovered_zone()
        if self._view.movable(row):
            self._stamp(painter, rect.left() + (GRIP_WIDTH - GRIP_SIZE) // 2, rect, self._grip_lit if zone == GRIP else self._grip)
        self._stamp(painter, rect.right() - CLOSE_WIDTH + (CLOSE_WIDTH - CLOSE_SIZE) // 2, rect, self._close_lit if zone == CLOSE else self._close)

    @staticmethod
    def _draw(painter, metrics: QFontMetrics, box: QRect, text: str) -> None:
        elided = metrics.elidedText(text or "", Qt.TextElideMode.ElideRight, box.width())
        painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

    @staticmethod
    def _stamp(painter, x: int, rect: QRect, art) -> None:
        painter.drawPixmap(x, rect.center().y() - art.height() // 2 + 1, art)


class _QueueList(QListWidget):
    remove_requested = pyqtSignal(list)
    move_requested = pyqtSignal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._cursor = -1
        self._hovered = -1
        self._zone = BODY
        self._dragging = -1
        self._insert = -1

        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setItemDelegate(_QueueDelegate(self))

    def set_cursor(self, cursor: int) -> None:
        """A rebuild invalidates the row indices a held drag is built on, so the gesture gets wiped with it.
        """
        self._cursor = cursor
        self._dragging, self._insert = -1, -1

    def hovered_row(self) -> int:
        return self._hovered

    def hovered_zone(self) -> str:
        return self._zone

    def movable(self, row: int) -> bool:
        """Refuse drops into the history since its poorly defined"""
        return 0 <= self._cursor < row

    def mouseMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        if self._dragging >= 0:
            self._aim(point)
            return
        super().mouseMoveEvent(event)
        self._track(point)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hovered, self._zone = -1, BODY
        self.viewport().unsetCursor()
        self.viewport().update()

    def mousePressEvent(self, event) -> None:
        point = event.position().toPoint()
        self._track(point)
        row = self.row(self.itemAt(point))
        if row >= 0 and self._zone == CLOSE and event.button() is Qt.MouseButton.LeftButton:
            self.remove_requested.emit([self.item(row).data(ENTRY_ID)])
            return
        # Using a custom gesture instead of QDrag - using QDrag causes it to hog the GIL, which starves the audio playback and causes glitchy sounds.
        if self._zone == GRIP and self.movable(row) and event.button() is Qt.MouseButton.LeftButton:
            self._dragging = row
            self._insert = -1
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging < 0:
            super().mouseReleaseEvent(event)
            return
        moved, landing = self._dragging, self._insert
        self._dragging, self._insert = -1, -1
        self.viewport().unsetCursor()
        self.viewport().update()
        if landing < 0 or moved >= self.count():
            return
        # Since reordering is handled on core, re-render when it processes the action.
        entry_id = self.item(moved).data(ENTRY_ID)
        after = self.item(landing - 1).data(ENTRY_ID)
        if after != entry_id:
            self.move_requested.emit(entry_id, after)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._dragging >= 0:
            self._dragging, self._insert = -1, -1
            self.viewport().unsetCursor()
            self.viewport().update()
            return
        if event.key() == Qt.Key.Key_Delete and self.selectedItems():
            self.remove_requested.emit([item.data(ENTRY_ID) for item in self.selectedItems()])
            return
        super().keyPressEvent(event)

    def _aim(self, point: QPoint) -> None:
        """Work out where the held entry would land and repaint"""
        landing = self._insertion_at(point)
        if landing == self._insert:
            return
        self._insert = landing
        self.viewport().update()

    def _insertion_at(self, point: QPoint) -> int:
        item = self.itemAt(point)
        if item is None:
            row = self.count() if point.y() > 0 else 0
        else:
            row = self.row(item)
            if point.y() > self.visualItemRect(item).center().y():
                row += 1
        return -1 if self._cursor < 0 or row <= self._cursor else row

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._insert < 0:
            return
        if self._insert < self.count():
            y = self.visualItemRect(self.item(self._insert)).top()
        else:
            y = self.visualItemRect(self.item(self.count() - 1)).bottom()
        painter = QPainter(self.viewport())
        painter.fillRect(QRect(GRIP_WIDTH, y - 1, self.viewport().width() - GRIP_WIDTH - CLOSE_WIDTH, 2), QColor(ACCENT))
        painter.end()

    def _track(self, point: QPoint) -> None:
        row = self.row(self.itemAt(point))
        zone = self._zone_at(point, row)
        if (row, zone) == (self._hovered, self._zone):
            return
        previous, self._hovered, self._zone = self._hovered, row, zone
        if zone == CLOSE:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        elif zone == GRIP and self.movable(row):
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().unsetCursor()
        for target in {previous, row}:
            if target >= 0:
                self.viewport().update(self.visualItemRect(self.item(target)))

    def _zone_at(self, point: QPoint, row: int) -> str:
        if row < 0:
            return BODY
        if point.x() < GRIP_WIDTH:
            return GRIP
        if point.x() > self.viewport().width() - CLOSE_WIDTH:
            return CLOSE
        return BODY


class QueueView(QWidget):
    """The queue around the cursor"""

    remove_requested = pyqtSignal(list)
    move_requested = pyqtSignal(int, int)

    def __init__(self, resolve: Resolver):
        super().__init__()
        self.setObjectName("queuePane")
        self.setFixedWidth(QUEUE_WIDTH)
        self._resolve = resolve

        title = QLabel("QUEUE")
        title.setObjectName("paneTitle")
        heading = QWidget()
        heading.setObjectName("paneHeading")
        heading.setFixedHeight(COLUMN_HEAD_HEIGHT)
        heading_column = QVBoxLayout(heading)
        heading_column.setContentsMargins(0, 0, 0, 0)
        heading_column.addWidget(title)

        self._list = _QueueList()
        self._list.setObjectName("queue")
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.remove_requested.connect(self.remove_requested.emit)
        self._list.move_requested.connect(self.move_requested.emit)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(heading)
        column.addWidget(self._list, 1)

    def show_queue(self, entries: list[QueueEntry], cursor: int) -> None:
        songs = self._resolve([entry.song_id for entry in entries])
        self._list.set_cursor(cursor)
        self._list.clear()
        for index, entry in enumerate(entries):
            song = songs.get(entry.song_id)
            item = QListWidgetItem()
            item.setData(ENTRY_ID, entry.entry_id)
            item.setData(LABEL, self._label(index, cursor))
            item.setData(NAME, song.name if song else f"song {entry.song_id}")
            item.setData(ARTIST, song.artist if song else "")
            item.setData(HEAD_COLOUR, self._colour(entry, index, cursor))
            item.setData(TAIL_COLOUR, DIMMER if index < cursor else DIM)
            # Rows are not drop targets themselves, which keeps the indicator between rows where a reorder means something.
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self._list.addItem(item)
        if 0 <= cursor < self._list.count():
            self._list.scrollToItem(self._list.item(cursor), QListWidget.ScrollHint.PositionAtCenter)

    @staticmethod
    def _label(index: int, cursor: int) -> str:
        return ">" if index == cursor else str(index - cursor)

    @staticmethod
    def _colour(entry: QueueEntry, index: int, cursor: int) -> str:
        """Dim automatically queued entries for readability"""
        if index == cursor:
            return ACCENT
        if index < cursor:
            return DIMMER
        return TEXT if entry.origin is QueueOrigin.USER else MUTED
