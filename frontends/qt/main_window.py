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
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qframelesswindow import FramelessMainWindow  # Thanks to ZhiYiYo for https://github.com/zhiyiYo/PyQt-Frameless-Window

from frontends import settings as settings_store
from frontends.core_client import ClientError, CoreClient
from frontends.qt.bridge import EventBridge
from frontends.qt.icons import app_icon
from frontends.qt.models.song_table_model import QUEUE_COLUMN, SongTableModel
from frontends.qt.style import COLUMN_HEAD_HEIGHT, STYLESHEET, TITLE_BAR_HEIGHT
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
SETTINGS_SAVE_DEBOUNCE_MS = 5000
STATUS_CLEAR_MS = 4000


class MainWindow(FramelessMainWindow):
    def __init__(self, client: CoreClient):
        super().__init__()
        self._client = client
        self._settings = settings_store.load()
        self._songs: dict[int, Song] = {}
        self._entry_ids: list[int] = []
        self._playlists: list[PlaylistSummary] = []
        self._playback: PlaybackState | None = None
        self._viewing_playlist: int | None = ALL_TRACKS_ID
        self._position = 0.0
        self._position_at = time.monotonic()
        self._rate = 0.0

        self.setWindowTitle("DeltaMusic")
        self.setWindowIcon(app_icon())
        self.resize(1280, 760)
        self.setStyleSheet(STYLESHEET)
        self.setTitleBar(ApplicationTitleBar(self))
        self._build()
        self.titleBar.raise_()

        self._bridge = EventBridge(client)
        self._bridge.arrived.connect(self._on_event)
        self._bridge.start()

        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start(TICK_MS)

        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.timeout.connect(self._settings.save)

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

        self._model = SongTableModel()
        self._table = SongTable()
        self._table.setModel(self._model)
        self._table.queue_requested.connect(self._on_queue_song)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(self._on_row_activated)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_menu)
        header = self._table.horizontalHeader()
        header.setFixedHeight(COLUMN_HEAD_HEIGHT)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(QUEUE_COLUMN, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 44)
        self._table.setColumnWidth(2, 190)
        self._table.setColumnWidth(3, 62)
        self._table.setColumnWidth(QUEUE_COLUMN, BUTTON_COLUMN_WIDTH)

        self._queue = QueueView(self._resolve)
        self._queue.remove_requested.connect(self._on_queue_remove)
        self._queue.move_requested.connect(self._on_queue_move)

        row.addWidget(self._sidebar)
        row.addWidget(self._build_divider())
        row.addWidget(self._table, 1)
        row.addWidget(self._build_divider())
        row.addWidget(self._queue)
        return body

    @staticmethod
    def _build_divider() -> QWidget:
        """The border-left would not paint, so make a plain QWidget subclass to ignore the box model."""
        divider = QFrame()
        divider.setObjectName("headerRule")
        divider.setFixedWidth(1)
        return divider

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
        self._restore_session()
        try:
            state = self._client.call("get_state")
        except ClientError as failure:
            self._set_status(str(failure))
            return
        self._apply_playback(PlaybackState.from_dict(state["playback"]))
        self._apply_queue(QueueState.from_dict(state["queue"]))

    def _restore_session(self) -> None:
        """Put the last session back. Whatever no longer resolves is quietly left out."""
        saved = self._settings
        self._quietly("set_volume", level=saved.volume)
        self._quietly("set_repeat", mode=saved.repeat)
        self._quietly("set_shuffle", enabled=saved.shuffle)
        if saved.song_id is None:
            return
        if saved.playlist_id is not None:
            result = self._quietly("get_playlist", playlist_id=saved.playlist_id)
            song_ids = [entry["song_id"] for entry in result["playlist"]["entries"]] if result else []
            if saved.song_id in song_ids:
                start = song_ids.index(saved.song_id)
                if self._quietly("play_playlist", playlist_id=saved.playlist_id, start_index=start, paused=True):
                    return
        # The playlist is gone, no longer holds the song, or would not open, so the song alone is the best that can be restored.
        self._quietly("play_songs", song_ids=[saved.song_id], paused=True)

    def _quietly(self, method: str, **params) -> dict | None:
        """Quietly attempt to run a call"""
        try:
            return self._client.call(method, **params)
        except ClientError as failure:
            log.info("could not restore %s: %s", method, failure)
            return None

    def _reload_playlists(self) -> None:
        try:
            result = self._client.call("list_playlists")
        except ClientError as failure:
            self._set_status(str(failure))
            return
        self._playlists = [PlaylistSummary.from_dict(raw) for raw in result["playlists"]]
        self._sidebar.show_playlists(self._playlists)

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

    def _run_search(self) -> None:
        query = self._search.text().strip()
        if not query:
            self._clear_status()
            if self._viewing_playlist is not None:
                self._show_playlist(self._viewing_playlist)
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
        self._model.set_songs(songs)
        self._highlight_current()
        self._set_status(f"{result['total']} matches")

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
        elif self._search.text().strip():
            self._run_search()
        elif self._viewing_playlist is not None:
            self._show_playlist(self._viewing_playlist)

    def _remember(self, **fields) -> None:
        """The write is debounced, so only a real change may restart the clock or it would never fire."""
        changed = [key for key, value in fields.items() if getattr(self._settings, key) != value]
        if not changed:
            return
        for key in changed:
            setattr(self._settings, key, fields[key])
        self._settings_timer.start(SETTINGS_SAVE_DEBOUNCE_MS)

    def _remember_playback(self, playback: PlaybackState) -> None:
        fields = {"shuffle": playback.shuffle, "repeat": playback.repeat.value}
        # Deliberately do not save mute state, and don't allow saving 0 volume so it doesn't come back silent
        if playback.volume > 0.0:
            fields["volume"] = playback.volume
        if playback.song_id is not None:
            fields["song_id"] = playback.song_id
        self._remember(**fields)

    def _apply_playback(self, playback: PlaybackState) -> None:
        self._playback = playback
        self._remember_playback(playback)
        self._position = playback.position
        self._position_at = time.monotonic()
        self._rate = playback.rate
        self._player.show_playback(playback)
        self._highlight_current()

    def _apply_queue(self, queue: QueueState) -> None:
        self._remember(playlist_id=queue.source.playlist_id if queue.source else None)
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

    # Reacting

    def _on_search_typed(self, _text: str) -> None:
        self._search_timer.start(SEARCH_DEBOUNCE_MS)

    def _on_playlist_chosen(self, playlist_id: int) -> None:
        self._viewing_playlist = playlist_id
        self._search.clear()
        self._show_playlist(playlist_id)

    def _on_playlist_play(self, playlist_id: int) -> None:
        """Shuffle should not always open on track one, so it starts somewhere in the playlist instead."""
        count = next((playlist.song_count for playlist in self._playlists if playlist.id == playlist_id), 0)
        if not count:
            return
        shuffling = self._playback is not None and self._playback.shuffle
        start = random.randrange(count) if shuffling else 0
        self._command("play_playlist", playlist_id=playlist_id, start_index=start)

    def _on_row_activated(self, index) -> None:
        row = index.row()
        song = self._model.song_at(row)
        if song is None:
            return
        if self._search.text().strip() or self._viewing_playlist is None:
            self._command("play_songs", song_ids=self._model.song_ids()[row:])
        else:
            self._command("play_playlist", playlist_id=self._viewing_playlist, start_index=row)

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
        confirmed = QMessageBox.question(self, "Delete playlist", f"Delete '{name}'? The songs are untouched.")
        if confirmed is not QMessageBox.StandardButton.Yes:
            return
        self._command("delete_playlist", playlist_id=playlist_id)
        if self._viewing_playlist == playlist_id:
            self._viewing_playlist = ALL_TRACKS_ID
            self._sidebar.select(ALL_TRACKS_ID)
        self._reload_playlists()

    # Songs

    def _on_table_menu(self, point) -> None:
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
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

        if self._entry_ids and self._viewing_playlist not in (None, ALL_TRACKS_ID):
            entry_ids = [self._entry_ids[row] for row in rows if row < len(self._entry_ids)]
            menu.addAction("Remove from this playlist", lambda: self._remove_entries(entry_ids))

        menu.addSeparator()
        menu.addAction("Forget", lambda: self._forget_songs(songs))
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
        confirmed = QMessageBox.question(
            self, "Forget songs", f"Drop {len(songs)} song(s) from the library? The files are untouched."
        )
        if confirmed is not QMessageBox.StandardButton.Yes:
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
        if self._settings_timer.isActive():
            self._settings_timer.stop()
            self._settings.save()
        self._bridge.stop()
        super().closeEvent(event)
