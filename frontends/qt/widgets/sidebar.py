from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget

from frontends.qt.style import COLUMN_HEAD_HEIGHT
from frontends.qt.types.snapshot import ListedPlaylist
from frontends.qt.widgets.no_focus_delegate import NoFocusDelegate
from protocol.types.peer_record import PeerRecord
from protocol.types.playlist_summary import PlaylistSummary

PLAYLIST_ID = Qt.ItemDataRole.UserRole
PEER_ID = Qt.ItemDataRole.UserRole + 1
ALL_TRACKS_ID = 0
PEER_ROWS_SHOWN = 5


class Sidebar(QWidget):
    """Peers above playlists. The playlist list follows the active peer."""

    playlist_chosen = pyqtSignal(object)
    play_requested = pyqtSignal(object)
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    peer_chosen = pyqtSignal(object)
    peer_refresh_requested = pyqtSignal(str)
    peer_fetch_requested = pyqtSignal(str)
    peer_forget_requested = pyqtSignal(str)
    playlist_fetch_requested = pyqtSignal(str)
    playlists_fetch_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebarPane")
        self.setFixedWidth(208)
        self._peer: str | None = None

        self._peers = self._build_list()
        self._peers.currentItemChanged.connect(self._on_peer_current)
        self._peers.customContextMenuRequested.connect(self._on_peer_menu)

        self._list = self._build_list()
        self._list.currentItemChanged.connect(self._on_current)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.customContextMenuRequested.connect(self._on_menu)

        self._add = QPushButton("+")
        self._add.setObjectName("iconButton")
        self._add.setToolTip("New playlist")
        self._add.setFixedWidth(24)
        self._add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add.clicked.connect(self.create_requested.emit)

        self._playlists_title = QLabel("PLAYLISTS")
        self._playlists_title.setObjectName("paneTitle")

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_heading(QLabel("DEVICES"), None))
        column.addWidget(self._peers)
        column.addWidget(self._build_heading(self._playlists_title, self._add))
        column.addWidget(self._list, 1)

        self.show_peers([], None)

    @staticmethod
    def _build_list() -> QListWidget:
        listing = QListWidget()
        listing.setObjectName("sidebar")
        listing.setItemDelegate(NoFocusDelegate(listing))
        listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        listing.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return listing

    @staticmethod
    def _build_heading(title: QLabel, button: QPushButton | None) -> QWidget:
        """Matches the track table's column head so the two line up across the divider."""
        title.setObjectName("paneTitle")
        heading = QWidget()
        heading.setObjectName("paneHeading")
        heading.setFixedHeight(COLUMN_HEAD_HEIGHT)
        row = QHBoxLayout(heading)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(0)
        row.addWidget(title, 1)
        if button is not None:
            row.addWidget(button)
        return heading

    # Peers

    def show_peers(self, peers: list[PeerRecord], active: str | None) -> None:
        self._peer = active
        self._peers.blockSignals(True)
        self._peers.clear()
        here = QListWidgetItem("This device")
        here.setData(PEER_ID, None)
        self._peers.addItem(here)
        for peer in peers:
            item = QListWidgetItem(peer.name)
            item.setData(PEER_ID, peer.id)
            self._peers.addItem(item)
        self._peers.setCurrentRow(self._peer_row(active))
        self._peers.blockSignals(False)
        rows = min(self._peers.count(), PEER_ROWS_SHOWN)
        self._peers.setFixedHeight(rows * self._peers.sizeHintForRow(0) + 2)
        self._add.setVisible(active is None)

    def _peer_row(self, peer_id: str | None) -> int:
        for row in range(self._peers.count()):
            if self._peers.item(row).data(PEER_ID) == peer_id:
                return row
        return 0

    def _on_peer_current(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.peer_chosen.emit(current.data(PEER_ID))

    def _on_peer_menu(self, point) -> None:
        item = self._peers.itemAt(point)
        if item is None or item.data(PEER_ID) is None:
            return
        peer_id = item.data(PEER_ID)
        menu = QMenu(self)
        menu.addAction("Refresh", lambda: self.peer_refresh_requested.emit(peer_id))
        menu.addAction("Download everything", lambda: self.peer_fetch_requested.emit(peer_id))
        menu.addSeparator()
        menu.addAction("Forget", lambda: self.peer_forget_requested.emit(peer_id))
        menu.exec(self._peers.mapToGlobal(point))

    # Playlists

    def show_playlists(self, playlists: list[PlaylistSummary]) -> None:
        wanted = self.selected_playlist_id()
        self._playlists_title.setText("PLAYLISTS")
        self._list.blockSignals(True)
        self._list.clear()
        for playlist in playlists:
            item = QListWidgetItem(f"{playlist.name}    {playlist.song_count}")
            item.setData(PLAYLIST_ID, playlist.id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self.select(wanted if wanted is not None else (playlists[0].id if playlists else None))

    def show_peer_playlists(self, peer_name: str, playlists: list[ListedPlaylist]) -> None:
        """A whole library row, then what the peer holds over what is here."""
        self._playlists_title.setText(peer_name.upper())
        self._list.blockSignals(True)
        self._list.clear()
        whole = QListWidgetItem(peer_name)
        whole.setData(PLAYLIST_ID, None)
        self._list.addItem(whole)
        for listed in playlists:
            entries = len(listed.playlist.songs)
            item = QListWidgetItem(f"{listed.playlist.name}    {listed.songs_held}/{entries}")
            item.setData(PLAYLIST_ID, listed.playlist.uuid)
            self._list.addItem(item)
        self._list.setCurrentRow(0)
        self._list.blockSignals(False)

    def show_listing(self, peer_name: str) -> None:
        self._playlists_title.setText(peer_name.upper())
        self._list.blockSignals(True)
        self._list.clear()
        item = QListWidgetItem("reading...")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._list.addItem(item)
        self._list.blockSignals(False)

    def select(self, playlist_id: int | None) -> None:
        if playlist_id is None:
            return
        for row in range(self._list.count()):
            if self._list.item(row).data(PLAYLIST_ID) == playlist_id:
                self._list.setCurrentRow(row)
                return

    def selected_playlist_id(self) -> int | None:
        item = self._list.currentItem()
        chosen = item.data(PLAYLIST_ID) if item is not None else None
        return chosen if isinstance(chosen, int) else None

    def _on_current(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.playlist_chosen.emit(current.data(PLAYLIST_ID))

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.play_requested.emit(item.data(PLAYLIST_ID))

    def _on_menu(self, point) -> None:
        item = self._list.itemAt(point)
        menu = QMenu(self)
        if self._peer is not None:
            peer_id, uuid = self._peer, item.data(PLAYLIST_ID) if item is not None else None
            if uuid is not None:
                menu.addAction("Download this playlist", lambda: self.playlist_fetch_requested.emit(uuid))
            elif item is not None:
                # The whole library row names no playlist, so it downloads the tracks themselves.
                menu.addAction("Download all tracks", lambda: self.peer_fetch_requested.emit(peer_id))
            menu.addAction("Download every playlist", self.playlists_fetch_requested.emit)
        else:
            menu.addAction("New playlist", self.create_requested.emit)
            if item is not None and item.data(PLAYLIST_ID) != ALL_TRACKS_ID:
                playlist_id = item.data(PLAYLIST_ID)
                menu.addSeparator()
                menu.addAction("Rename", lambda: self.rename_requested.emit(playlist_id))
                menu.addAction("Delete", lambda: self.delete_requested.emit(playlist_id))
        menu.exec(self._list.mapToGlobal(point))
