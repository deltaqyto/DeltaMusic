from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget

from frontends.qt.style import COLUMN_HEAD_HEIGHT
from frontends.qt.widgets.no_focus_delegate import NoFocusDelegate
from protocol.types.playlist_summary import PlaylistSummary

PLAYLIST_ID = Qt.ItemDataRole.UserRole
ALL_TRACKS_ID = 0


class Sidebar(QWidget):
    """All Tracks, then the playlists, with the controls for managing them."""

    playlist_chosen = pyqtSignal(int)
    play_requested = pyqtSignal(int)
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebarPane")
        self.setFixedWidth(208)

        title = QLabel("PLAYLISTS")
        title.setObjectName("paneTitle")

        add = QPushButton("+")
        add.setObjectName("iconButton")
        add.setToolTip("New playlist")
        add.setFixedWidth(24)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self.create_requested.emit)

        # Matches the track table's column head so the two line up across the divider.
        heading = QWidget()
        heading.setObjectName("paneHeading")
        heading.setFixedHeight(COLUMN_HEAD_HEIGHT)
        heading_row = QHBoxLayout(heading)
        heading_row.setContentsMargins(0, 0, 8, 0)
        heading_row.setSpacing(0)
        heading_row.addWidget(title, 1)
        heading_row.addWidget(add)

        self._list = QListWidget()
        self._list.setObjectName("sidebar")
        self._list.setItemDelegate(NoFocusDelegate(self._list))
        self._list.currentItemChanged.connect(self._on_current)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_menu)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(heading)
        column.addWidget(self._list, 1)

    def show_playlists(self, playlists: list[PlaylistSummary]) -> None:
        wanted = self.selected_playlist_id()
        self._list.blockSignals(True)
        self._list.clear()
        for playlist in playlists:
            item = QListWidgetItem(f"{playlist.name}    {playlist.song_count}")
            item.setData(PLAYLIST_ID, playlist.id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self.select(wanted if wanted is not None else (playlists[0].id if playlists else None))

    def select(self, playlist_id: int | None) -> None:
        if playlist_id is None:
            return
        for row in range(self._list.count()):
            if self._list.item(row).data(PLAYLIST_ID) == playlist_id:
                self._list.setCurrentRow(row)
                return

    def selected_playlist_id(self) -> int | None:
        item = self._list.currentItem()
        return item.data(PLAYLIST_ID) if item is not None else None

    def _on_current(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.playlist_chosen.emit(current.data(PLAYLIST_ID))

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.play_requested.emit(item.data(PLAYLIST_ID))

    def _on_menu(self, point) -> None:
        item = self._list.itemAt(point)
        menu = QMenu(self)
        menu.addAction("New playlist", self.create_requested.emit)
        if item is not None and item.data(PLAYLIST_ID) != ALL_TRACKS_ID:
            playlist_id = item.data(PLAYLIST_ID)
            menu.addSeparator()
            menu.addAction("Rename", lambda: self.rename_requested.emit(playlist_id))
            menu.addAction("Delete", lambda: self.delete_requested.emit(playlist_id))
        menu.exec(self._list.mapToGlobal(point))
