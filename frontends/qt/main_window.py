import logging
import random
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from qframelesswindow import FramelessMainWindow  # Thanks to ZhiYiYo for https://github.com/zhiyiYo/PyQt-Frameless-Window

from frontends.core_client import ClientError, CoreClient
from frontends.qt.bridge import EventBridge
from frontends.qt.icons import app_icon
from frontends.qt.models.peer_song_table_model import PeerSongTableModel
from frontends.qt.models.song_table_model import ACTION_COLUMN, SongTableModel
from frontends.qt.peer_book import PeerBook
from frontends.qt.style import COLUMN_HEAD_HEIGHT, STYLESHEET, TITLE_BAR_HEIGHT
from frontends.qt.types.view_target import ViewTarget
from frontends.qt.widgets.confirmation import Confirmation
from frontends.qt.widgets.devices_dialog import DevicesDialog
from frontends.qt.widgets.job_bar import JobBar
from frontends.qt.widgets.name_editor import NameEditor
from frontends.qt.widgets.player_bar import PlayerBar
from frontends.qt.widgets.queue_view import QueueView
from frontends.qt.widgets.sidebar import Sidebar
from frontends.qt.widgets.song_table import BUTTON_COLUMN_WIDTH, SongTable
from frontends.qt.widgets.song_editor import SongEditor
from frontends.qt.widgets.title_bar import ApplicationTitleBar
from protocol.types.event import Event
from protocol.types.event_type import EventType
from protocol.types.library_scope import LibraryScope
from protocol.types.playback_state import PlaybackState
from protocol.types.playlist_summary import PlaylistSummary
from protocol.types.queue_state import QueueState
from protocol.types.song import Song

log = logging.getLogger(__name__)

ALL_TRACKS_ID = 0
SEARCH_DEBOUNCE_MS = 200
TICK_MS = 200
STATUS_CLEAR_MS = 4000


class MainWindow(FramelessMainWindow):
    def __init__(self, client: CoreClient):
        super().__init__()
        self._client = client
        self._songs: dict[int, Song] = {}
        self._entry_ids: list[int] = []
        self._playlists: list[PlaylistSummary] = []
        self._playback: PlaybackState | None = None
        self._viewing = ViewTarget.local(ALL_TRACKS_ID)
        self._position = 0.0
        self._position_at = time.monotonic()
        self._rate = 0.0
        self._book = PeerBook(client)
        self._devices: DevicesDialog | None = None

        self.setWindowTitle("DeltaMusic")
        self.setWindowIcon(app_icon())
        self.resize(1280, 760)
        self.setStyleSheet(STYLESHEET)
        self.setTitleBar(ApplicationTitleBar(self))
        self._build()
        self._wire_book()
        self.titleBar.raise_()

        self._bridge = EventBridge(client)
        self._bridge.arrived.connect(self._book.handle)
        self._bridge.arrived.connect(self._on_event)
        self._bridge.start()

        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start(TICK_MS)

        self._load_state()

    # Building

    def _build(self) -> None:
        shell = QWidget()
        shell.setObjectName("shell")
        column = QVBoxLayout(shell)
        column.setContentsMargins(0, TITLE_BAR_HEIGHT, 0, 0)
        column.setSpacing(0)

        self._wire_header()
        column.addWidget(self._build_rule())
        column.addWidget(self._build_body(), 1)

        self._job_bar = JobBar(self._book)
        column.addWidget(self._job_bar)

        self._player = PlayerBar()
        self._player.play_pressed.connect(lambda: self._command("play"))
        self._player.pause_pressed.connect(lambda: self._command("pause"))
        self._player.next_pressed.connect(lambda: self._command("next_track"))
        self._player.previous_pressed.connect(lambda: self._command("previous_track"))
        self._player.seeked.connect(lambda seconds: self._command("seek_to", seconds=seconds))
        self._player.volume_set.connect(lambda level: self._command("set_volume", level=level))
        self._player.shuffle_set.connect(lambda enabled: self._command("set_shuffle", enabled=enabled))
        self._player.repeat_set.connect(lambda mode: self._command("set_repeat", mode=mode))
        column.addWidget(self._player)

        self.setCentralWidget(shell)

    def _wire_header(self) -> None:
        self._search = self.titleBar.search
        self._status = self.titleBar.status
        self._search.textChanged.connect(self._on_search_typed)
        self.titleBar.devices.clicked.connect(self._open_devices)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._run_search)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status)

    @staticmethod
    def _build_rule() -> QWidget:
        rule = QFrame()
        rule.setObjectName("headerRule")
        rule.setFixedHeight(1)
        return rule

    def _build_body(self) -> QWidget:
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.playlist_chosen.connect(self._on_playlist_chosen)
        self._sidebar.create_requested.connect(self._on_create_playlist)
        self._sidebar.rename_requested.connect(self._on_rename_playlist)
        self._sidebar.delete_requested.connect(self._on_delete_playlist)
        self._sidebar.play_requested.connect(self._on_playlist_play)
        self._sidebar.peer_chosen.connect(self._book.activate)
        self._sidebar.peer_refresh_requested.connect(lambda _peer_id: self._book.refresh())
        self._sidebar.peer_fetch_requested.connect(self._book.fetch_songs)
        self._sidebar.peer_forget_requested.connect(self._on_forget_peer)
        self._sidebar.playlist_fetch_requested.connect(self._on_fetch_playlist)
        self._sidebar.playlists_fetch_requested.connect(self._on_fetch_playlists)

        self._model = SongTableModel()
        self._peer_model = PeerSongTableModel()
        self._table = SongTable()
        self._table.setModel(self._model)
        self._table.action_requested.connect(self._on_queue_song)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(self._on_row_activated)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_menu)
        self._dress_header()

        self._queue = QueueView(self._resolve)
        self._queue.remove_requested.connect(self._on_queue_remove)
        self._queue.move_requested.connect(self._on_queue_move)

        row.addWidget(self._sidebar)
        row.addWidget(self._build_divider())
        row.addWidget(self._table, 1)
        row.addWidget(self._build_divider())
        row.addWidget(self._queue)
        return body

    def _dress_header(self) -> None:
        """The models share a column layout, and a fresh model resets the sections."""
        header = self._table.horizontalHeader()
        header.setFixedHeight(COLUMN_HEAD_HEIGHT)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(ACTION_COLUMN, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 44)
        self._table.setColumnWidth(2, 190)
        self._table.setColumnWidth(3, 62)
        self._table.setColumnWidth(ACTION_COLUMN, BUTTON_COLUMN_WIDTH)

    @staticmethod
    def _build_divider() -> QWidget:
        """The border-left would not paint, so make a plain QWidget subclass to ignore the box model."""
        divider = QFrame()
        divider.setObjectName("headerRule")
        divider.setFixedWidth(1)
        return divider

    def _wire_book(self) -> None:
        self._book.peers_changed.connect(self._show_peers)
        self._book.active_changed.connect(self._on_active_changed)
        self._book.snapshot_changed.connect(self._on_snapshot)
        self._book.snapshot_failed.connect(self._on_snapshot_failed)
        self._book.failed.connect(self._set_status)
        self._book.code_ready.connect(self._open_devices)

    # Status

    def _set_status(self, text: str) -> None:
        """Statuses get wiped after a bit"""
        self._status.setText(text)
        self._status_timer.start(STATUS_CLEAR_MS)

    def _clear_status(self) -> None:
        self._status_timer.stop()
        self._status.setText("")

    # Loading

    def _load_state(self) -> None:
        self._reload_playlists()
        self._book.start()
        try:
            state = self._client.call("get_state")
        except ClientError as failure:
            self._set_status(str(failure))
            return
        self._apply_playback(PlaybackState.from_dict(state["playback"]))
        self._apply_queue(QueueState.from_dict(state["queue"]))

    def _reload_playlists(self) -> None:
        try:
            result = self._client.call("list_playlists")
        except ClientError as failure:
            self._set_status(str(failure))
            return
        self._playlists = [PlaylistSummary.from_dict(raw) for raw in result["playlists"]]
        if self._book.active_peer() is None:
            self._sidebar.show_playlists(self._playlists)

    def _show_target(self) -> None:
        if self._viewing.is_local:
            self._use_model(self._model)
            self._show_playlist(self._viewing.playlist_id)
            return
        self._use_model(self._peer_model)
        self._show_peer_songs()

    def _use_model(self, model) -> None:
        if self._table.model() is model:
            return
        self._table.setModel(model)
        self._dress_header()

    def _show_playlist(self, playlist_id: int) -> None:
        try:
            playlist = self._client.call("get_playlist", playlist_id=playlist_id)["playlist"]
        except ClientError as failure:
            self._set_status(str(failure))
            return
        entries = playlist["entries"]
        song_ids = [entry["song_id"] for entry in entries]
        resolved = self._resolve(song_ids)
        # Entry ids are what playlist_remove addresses, and duplicates mean a song id will not do.
        self._entry_ids = [entry["entry_id"] for entry in entries if entry["song_id"] in resolved]
        self._model.set_songs([resolved[song_id] for song_id in song_ids if song_id in resolved])
        self._highlight_current()

    def _show_peer_songs(self) -> None:
        snapshot = self._book.snapshot()
        if snapshot is None:
            self._peer_model.set_songs([])
            return
        self._entry_ids = []
        if self._viewing.playlist_uuid is None:
            self._peer_model.set_songs(snapshot.songs)
        else:
            self._peer_model.set_songs(snapshot.tracks_of(self._viewing.playlist_uuid))

    def _run_search(self) -> None:
        query = self._search.text().strip()
        if not query:
            self._clear_status()
            self._show_target()
            return
        if not self._viewing.is_local:
            self._search_peer(query)
            return
        try:
            result = self._client.call("list_songs", query=query, offset=0, limit=500)
        except ClientError as failure:
            self._set_status(str(failure))
            return
        songs = [Song.from_dict(raw) for raw in result["songs"]]
        for song in songs:
            self._songs[song.id] = song
        self._entry_ids = []
        self._use_model(self._model)
        self._model.set_songs(songs)
        self._highlight_current()
        self._set_status(f"{result['total']} matches")

    def _search_peer(self, query: str) -> None:
        """No command searches a peer, so the snapshot is filtered here."""
        snapshot = self._book.snapshot()
        if snapshot is None:
            return
        wanted = query.casefold()
        rows = [
            listed
            for listed in snapshot.songs
            if wanted in listed.song.name.casefold() or wanted in listed.song.artist.casefold()
        ]
        self._use_model(self._peer_model)
        self._peer_model.set_songs(rows)
        self._set_status(f"{len(rows)} matches")

    def _resolve(self, song_ids: list[int]) -> dict[int, Song]:
        """Ids to songs, fetching only what is not cached."""
        wanted = [song_id for song_id in dict.fromkeys(song_ids) if song_id not in self._songs]
        if wanted:
            try:
                result = self._client.call("get_songs", song_ids=wanted)
            except ClientError as failure:
                log.warning("could not resolve songs: %s", failure)
                result = {"songs": []}
            for raw in result["songs"]:
                song = Song.from_dict(raw)
                self._songs[song.id] = song
        return {song_id: self._songs[song_id] for song_id in song_ids if song_id in self._songs}

    # Events

    def _on_event(self, event: Event) -> None:
        if event.type is EventType.HEARTBEAT:
            self._apply_playback(PlaybackState.from_dict(event.payload["playback"]))
            if "queue" in event.payload:
                self._apply_queue(QueueState.from_dict(event.payload["queue"]))
        elif event.type is EventType.PLAYBACK_CHANGED:
            self._apply_playback(PlaybackState.from_dict(event.payload["playback"]))
        elif event.type is EventType.TRACK_CHANGED:
            self._highlight_current()
            # Every label and colour in the queue is relative to the cursor, so a move restyles rows that did not change.
            self._refresh_queue()
        elif event.type is EventType.QUEUE_CHANGED:
            self._refresh_queue()
        elif event.type is EventType.LIBRARY_CHANGED:
            self._on_library_changed(event)
        elif event.type is EventType.SCAN_PROGRESS:
            payload = event.payload
            self._set_status(f"scanning {payload['scanned']}/{payload['total']}")
        elif event.type is EventType.TRACK_FAILED:
            self._set_status(event.payload.get("message", "a track would not play"))

    def _on_library_changed(self, event: Event) -> None:
        # Play counts change on every track, and nothing on screen shows them, so refetching for them is pure churn.
        if event.payload.get("scope") == LibraryScope.STATISTICS.value:
            return
        for song_id in event.payload.get("ids", []):
            self._songs.pop(song_id, None)
        if event.payload.get("scope") == LibraryScope.PLAYLIST.value:
            self._reload_playlists()
        elif not self._viewing.is_local:
            return
        elif self._search.text().strip():
            self._run_search()
        else:
            self._show_target()

    def _apply_playback(self, playback: PlaybackState) -> None:
        self._playback = playback
        self._position = playback.position
        self._position_at = time.monotonic()
        self._rate = playback.rate
        self._player.show_playback(playback)
        self._highlight_current()

    def _apply_queue(self, queue: QueueState) -> None:
        self._queue.show_queue(queue.entries, queue.cursor)

    def _refresh_queue(self) -> None:
        try:
            queue = QueueState.from_dict(self._client.call("get_queue")["queue"])
        except ClientError as failure:
            self._set_status(str(failure))
            return
        self._apply_queue(queue)

    def _highlight_current(self) -> None:
        song_id = self._playback.song_id if self._playback else None
        self._model.set_playing(song_id)
        if song_id is None:
            self._player.show_track("Nothing playing", "")
            return
        song = self._resolve([song_id]).get(song_id)
        if song is not None:
            self._player.show_track(song.name, song.artist)

    def _tick(self) -> None:
        if self._rate <= 0.0:
            return
        elapsed = time.monotonic() - self._position_at
        self._player.show_position(self._position + elapsed * self._rate)

    # Peers

    def _show_peers(self) -> None:
        self._sidebar.show_peers(self._book.peers(), self._book.active_peer())

    def _on_active_changed(self) -> None:
        peer_id = self._book.active_peer()
        self._show_peers()
        self._search.clear()
        if peer_id is None:
            self._viewing = ViewTarget.local(ALL_TRACKS_ID)
            self._sidebar.show_playlists(self._playlists)
            self._sidebar.select(ALL_TRACKS_ID)
            self._show_target()
            return
        name = self._book.peer_name(peer_id)
        self._viewing = ViewTarget.peer_library(peer_id)
        self._sidebar.show_listing(name)
        self._use_model(self._peer_model)
        self._peer_model.set_songs([])
        self._set_status(f"reading {name}")

    def _on_snapshot(self) -> None:
        snapshot = self._book.snapshot()
        peer_id = self._book.active_peer()
        if snapshot is None or peer_id is None:
            return
        self._sidebar.show_peer_playlists(self._book.peer_name(peer_id), snapshot.playlists)
        # A refresh keeps the playlist that was open, if the peer still carries it.
        if self._viewing.playlist_uuid is not None and snapshot.playlist(self._viewing.playlist_uuid) is None:
            self._viewing = ViewTarget.peer_library(peer_id)
        self._show_target()

    def _on_snapshot_failed(self, message: str) -> None:
        self._set_status(message)
        self._sidebar.show_peer_playlists(self._book.peer_name(self._book.active_peer() or ""), [])
        self._use_model(self._peer_model)
        self._peer_model.set_songs([])

    def _open_devices(self) -> None:
        if self._devices is None:
            self._devices = DevicesDialog(self._book, self)
        self._devices.show()
        self._devices.raise_()
        self._devices.activateWindow()

    def _on_forget_peer(self, peer_id: str) -> None:
        name = self._book.peer_name(peer_id)
        if Confirmation.ask(self, "Forget device", f"Forget '{name}'? Its tracks here are untouched."):
            self._book.forget(peer_id)

    def _on_fetch_playlist(self, uuid: str) -> None:
        peer_id = self._book.active_peer()
        if peer_id is not None and self._confirm_merge(uuid):
            self._book.fetch_playlists(peer_id, [uuid])

    def _on_fetch_playlists(self) -> None:
        peer_id = self._book.active_peer()
        if peer_id is not None:
            self._book.fetch_playlists(peer_id)

    def _confirm_merge(self, uuid: str) -> bool:
        """Merging a playlist this core already holds replaces its entry list."""
        known = next((playlist for playlist in self._playlists if playlist.uuid == uuid), None)
        if known is None:
            return True
        return Confirmation.ask(
            self, "Download playlist", f"'{known.name}' is already downloaded. Update with peer copy?."
        )

    def _play_held(self, uuids: list[str]) -> None:
        """A fetch writes rows before files move, so `found_on_disk` is the test rather than the row being there."""
        held = self._book.resolve(uuids)
        song_ids = [held[uuid].id for uuid in uuids if uuid in held and held[uuid].found_on_disk]
        if song_ids:
            self._command("play_songs", song_ids=song_ids)

    # Reacting

    def _on_search_typed(self, _text: str) -> None:
        self._search_timer.start(SEARCH_DEBOUNCE_MS)

    def _on_playlist_chosen(self, chosen) -> None:
        peer_id = self._book.active_peer()
        if peer_id is None:
            if not isinstance(chosen, int):
                return
            self._viewing = ViewTarget.local(chosen)
        elif chosen is None:
            self._viewing = ViewTarget.peer_library(peer_id)
        else:
            self._viewing = ViewTarget.peer_playlist(peer_id, chosen)
        self._search.clear()
        self._show_target()

    def _on_playlist_play(self, chosen) -> None:
        peer_id = self._book.active_peer()
        if peer_id is None:
            if isinstance(chosen, int):
                self._play_local_playlist(chosen)
            return
        if chosen is None:
            return
        if not self._confirm_merge(chosen):
            return
        self._book.fetch_playlists(peer_id, [chosen])
        snapshot = self._book.snapshot()
        if snapshot is not None:
            self._play_held([listed.song.uuid for listed in snapshot.tracks_of(chosen)])

    def _play_local_playlist(self, playlist_id: int) -> None:
        """Shuffle should not always open on track one, so it starts somewhere in the playlist instead."""
        count = next((playlist.song_count for playlist in self._playlists if playlist.id == playlist_id), 0)
        if not count:
            return
        shuffling = self._playback is not None and self._playback.shuffle
        start = random.randrange(count) if shuffling else 0
        self._command("play_playlist", playlist_id=playlist_id, start_index=start)

    def _on_row_activated(self, index) -> None:
        row = index.row()
        if not self._viewing.is_local:
            self._activate_peer_row(row)
            return
        song = self._model.song_at(row)
        if song is None:
            return
        if self._search.text().strip():
            self._command("play_songs", song_ids=self._model.song_ids()[row:])
        else:
            self._command("play_playlist", playlist_id=self._viewing.playlist_id, start_index=row)

    def _activate_peer_row(self, row: int) -> None:
        listed = self._peer_model.song_at(row)
        peer_id = self._book.active_peer()
        if listed is None or peer_id is None or not listed.song.available:
            return
        if not listed.held:
            self._book.fetch_songs(peer_id, [listed.song.uuid])
            return
        self._play_held([entry.song.uuid for entry in self._peer_songs_from(row)])

    def _peer_songs_from(self, row: int) -> list:
        return [self._peer_model.song_at(index) for index in range(row, self._peer_model.rowCount())]

    # Playlists

    def _on_create_playlist(self) -> None:
        name = NameEditor.ask(self, "New playlist", "Name")
        if name is None:
            return
        self._command("create_playlist", name=name, song_ids=[])
        self._reload_playlists()

    def _on_rename_playlist(self, playlist_id: int) -> None:
        current = next((p.name for p in self._playlists if p.id == playlist_id), "")
        name = NameEditor.ask(self, "Rename playlist", "Name", current)
        if name is None:
            return
        self._command("update_playlist", playlist_id=playlist_id, fields={"name": name})
        self._reload_playlists()

    def _on_delete_playlist(self, playlist_id: int) -> None:
        name = next((p.name for p in self._playlists if p.id == playlist_id), "")
        if not Confirmation.ask(self, "Delete playlist", f"Delete '{name}'? The songs are untouched."):
            return
        self._command("delete_playlist", playlist_id=playlist_id)
        if self._viewing.playlist_id == playlist_id:
            self._viewing = ViewTarget.local(ALL_TRACKS_ID)
            self._sidebar.select(ALL_TRACKS_ID)
        self._reload_playlists()

    # Songs

    def _on_table_menu(self, point) -> None:
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        if not self._viewing.is_local:
            self._peer_menu(point, rows)
            return
        songs = [song for song in (self._model.song_at(row) for row in rows) if song is not None]
        if not songs:
            return

        menu = QMenu(self)
        menu.addAction("Play", lambda: self._on_row_activated(self._table.indexAt(point)))
        if len(songs) == 1:
            menu.addAction("Edit...", lambda: self._edit_song(songs[0]))

        targets = [p for p in self._playlists if p.id != ALL_TRACKS_ID]
        if targets:
            adding = menu.addMenu("Add to playlist")
            for playlist in targets:
                adding.addAction(playlist.name, lambda _=False, p=playlist.id: self._add_to_playlist(p, songs))

        if self._entry_ids and self._viewing.playlist_id not in (None, ALL_TRACKS_ID):
            entry_ids = [self._entry_ids[row] for row in rows if row < len(self._entry_ids)]
            menu.addAction("Remove from this playlist", lambda: self._remove_entries(entry_ids))

        menu.addSeparator()
        menu.addAction("Forget", lambda: self._forget_songs(songs))
        menu.exec(self._table.viewport().mapToGlobal(point))

    def _peer_menu(self, point, rows: list[int]) -> None:
        peer_id = self._book.active_peer()
        if peer_id is None:
            return
        listed = [entry for entry in (self._peer_model.song_at(row) for row in rows) if entry is not None]
        menu = QMenu(self)
        if listed:
            uuids = [entry.song.uuid for entry in listed]
            menu.addAction(f"Download {len(uuids)} track(s)", lambda: self._book.fetch_songs(peer_id, uuids))
        menu.addAction("Download everything", lambda: self._book.fetch_songs(peer_id))
        menu.exec(self._table.viewport().mapToGlobal(point))

    def _edit_song(self, song: Song) -> None:
        editor = SongEditor(song, self)
        if editor.exec() != SongEditor.DialogCode.Accepted:
            return
        fields = {key: value for key, value in editor.fields().items() if value}
        if fields:
            self._command("update_song", song_id=song.id, fields=fields)

    def _add_to_playlist(self, playlist_id: int, songs: list[Song]) -> None:
        self._command("playlist_add", playlist_id=playlist_id, song_ids=[song.id for song in songs], at_index=None)
        self._reload_playlists()

    def _remove_entries(self, entry_ids: list[int]) -> None:
        if entry_ids:
            self._command("playlist_remove", entry_ids=entry_ids)

    def _forget_songs(self, songs: list[Song]) -> None:
        question = f"Drop {len(songs)} song(s) from the library? The files are untouched."
        if not Confirmation.ask(self, "Forget songs", question):
            return
        for song in songs:
            self._command("forget_song", song_id=song.id)

    def _on_queue_song(self, row: int) -> None:
        """No landing spot given, so the core drops it after the last thing the user queued."""
        song = self._model.song_at(row)
        if song is not None:
            self._command("queue_insert", song_ids=[song.id], after_entry_id=None)

    def _on_queue_remove(self, entry_ids: list) -> None:
        self._command("queue_remove", entry_ids=list(entry_ids))

    def _on_queue_move(self, entry_id: int, after_entry_id: int) -> None:
        self._command("queue_move", entry_id=entry_id, after_entry_id=after_entry_id)

    def _command(self, method: str, **params) -> None:
        try:
            result = self._client.call(method, **params)
        except ClientError as failure:
            self._set_status(str(failure))
            return
        if "playback" in result:
            self._apply_playback(PlaybackState.from_dict(result["playback"]))
        if "queue" in result:
            self._apply_queue(QueueState.from_dict(result["queue"]))

    def closeEvent(self, event) -> None:
        self._ticker.stop()
        self._bridge.stop()
        super().closeEvent(event)
