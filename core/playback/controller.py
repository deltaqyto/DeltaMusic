import itertools
import logging
import random
from collections.abc import Sequence
from dataclasses import replace

from core.event_bus import EventBus
from core.library.library import Library
from core.playback.engine import PlaybackEngine
from protocol.errors import ProtocolError, invalid_argument, not_found, playback_failed, track_absent
from protocol.types.event_type import EventType
from protocol.types.playback_state import PlaybackState
from protocol.types.playback_status import PlaybackStatus
from protocol.types.queue_entry import QueueEntry
from protocol.types.queue_origin import QueueOrigin
from protocol.types.queue_state import QueueState
from protocol.types.repeat_mode import RepeatMode
from protocol.types.source import Source
from protocol.types.source_kind import SourceKind

log = logging.getLogger(__name__)

HISTORY_LIMIT = 50
AHEAD_LIMIT = 20
MAX_CONSECUTIVE_FAILURES = 10


class PlaybackController:
    """The queue, the cursor, repeat, and shuffle."""

    def __init__(self, library: Library, engine: PlaybackEngine, bus: EventBus, initial_volume: float = 0.8):
        self._library = library
        self._engine = engine
        self._bus = bus

        self._queue: list[QueueEntry] = []
        self._current: int | None = None

        self._entry_ids = itertools.count(1)
        self._source: Source | None = None
        self._source_ids: list[int] = []
        self._source_next = 0

        self._status = PlaybackStatus.IDLE
        self._repeat = RepeatMode.PLAYLIST
        self._shuffle = False
        self._volume = min(1.0, max(0.0, initial_volume))
        self._duration = 0.0
        self._failures = 0
        self._counted = False
        self._swallowed = 0

        self._engine.set_volume(self._volume)

    # State

    def playback_state(self) -> PlaybackState:
        return PlaybackState(
            status=self._status,
            song_id=self.current_song_id(),
            position=self._engine.position() if self._status is not PlaybackStatus.IDLE else 0.0,
            rate=1.0 if self._status is PlaybackStatus.PLAYING else 0.0,
            duration=self._duration,
            volume=self._volume,
            repeat=self._repeat,
            shuffle=self._shuffle,
            queue_revision=self._bus.queue_revision,
        )

    def queue_state(self) -> QueueState:
        return QueueState(
            entries=list(self._queue),
            cursor=self._cursor(),
            source=self._source,
            queue_revision=self._bus.queue_revision,
        )

    def current_song_id(self) -> int | None:
        entry = self._current_entry()
        return entry.song_id if entry else None

    def source_playlist_id(self) -> int | None:
        return self._source.playlist_id if self._source else None

    def close(self) -> None:
        self._engine.close()

    # Transport

    def play(self) -> PlaybackState:
        if self._status is PlaybackStatus.PAUSED:
            self._engine.play()
            self._status = PlaybackStatus.PLAYING
            self._count_current()
        elif self._status is PlaybackStatus.IDLE and self.current_song_id() is not None:
            self._start_current()
        return self._announce()

    def pause(self) -> PlaybackState:
        if self._status is PlaybackStatus.PLAYING:
            self._engine.pause()
            self._status = PlaybackStatus.PAUSED
        return self._announce()

    def stop(self) -> PlaybackState:
        self._stop_playback()
        return self._announce()

    def seek_to(self, seconds: float) -> PlaybackState:
        if self._status is not PlaybackStatus.IDLE:
            self._engine.seek_to(min(max(0.0, seconds), self._duration))
        return self._announce()

    def seek_by(self, delta_seconds: float) -> PlaybackState:
        return self.seek_to(self._engine.position() + delta_seconds)

    def next_track(self) -> PlaybackState:
        self._advance(1)
        return self.playback_state()

    def previous_track(self) -> PlaybackState:
        self._advance(-1)
        return self.playback_state()

    def set_repeat(self, mode: str) -> PlaybackState:
        try:
            self._repeat = RepeatMode(mode)
        except ValueError:
            raise invalid_argument(f"'{mode}' is not a repeat mode")
        if self._repeat is RepeatMode.NONE:
            self._shuffle = False
        self._maintain_and_publish()
        return self._announce()

    def set_shuffle(self, enabled: bool) -> PlaybackState:
        was = self._shuffle
        self._shuffle = bool(enabled)
        if self._shuffle and self._repeat is RepeatMode.NONE:
            self._repeat = RepeatMode.PLAYLIST
        if self._shuffle != was:
            # What is already queued was drawn the old way, so it is thrown out and drawn again.
            self._flush_ahead()
            self._maintain()
            self._bus.queue_changed()
        else:
            self._maintain_and_publish()
        return self._announce()

    def set_volume(self, level: float) -> PlaybackState:
        self._volume = min(1.0, max(0.0, float(level)))
        self._engine.set_volume(self._volume)
        return self._announce()

    def play_playlist(self, playlist_id: int, start_index: int | None, paused: bool = False) -> PlaybackState:
        song_ids = self._library.song_ids_in(playlist_id)
        if not song_ids:
            raise invalid_argument("that playlist has no songs", playlist_id=playlist_id)
        start = start_index or 0
        if not 0 <= start < len(song_ids):
            raise invalid_argument(f"start_index {start} is outside the playlist")
        # Checked before anything is mutated, so a dead song leaves whatever was playing alone.
        self._require_on_disk(song_ids[start])
        self._source = Source(kind=SourceKind.PLAYLIST, playlist_id=playlist_id)
        self._source_ids = song_ids
        self._source_next = start
        # Only the chosen song goes in. The refill takes it from there, so a huge playlist is not copied.
        self._load_queue([song_ids[start]], paused, strict=True)
        return self._announce()

    def play_songs(self, song_ids: Sequence[int], paused: bool = False) -> PlaybackState:
        known = [song.id for song in self._library.get_songs(list(song_ids))]
        if not known:
            raise not_found("none of those songs exist", song_ids=list(song_ids))
        self._require_on_disk(known[0])
        self._source = Source(kind=SourceKind.SONGS, playlist_id=None)
        self._source_ids = known
        self._source_next = 0
        self._load_queue([known[0]], paused, strict=True)
        return self._announce()

    # Queue

    def queue_insert(self, song_ids: Sequence[int], after_entry_id: int | None) -> QueueState:
        known = [song.id for song in self._library.get_songs(list(song_ids))]
        missing = set(song_ids) - set(known)
        if missing:
            raise not_found(f"no songs {sorted(missing)}", song_ids=sorted(missing))
        at = self._landing_index(after_entry_id, self._user_boundary())
        self._promote_through(at)
        self._queue[at:at] = [self._new_entry(song_id, QueueOrigin.USER) for song_id in song_ids]
        return self._queue_edited()

    def queue_remove(self, entry_ids: Sequence[int]) -> QueueState:
        doomed = {int(entry_id) for entry_id in entry_ids}
        cursor_went = self._current in doomed
        # Where playback resumes: however many survivors sat ahead of the entry that was playing.
        resume = sum(1 for entry in self._queue[: max(0, self._cursor())] if entry.entry_id not in doomed)
        self._queue = [entry for entry in self._queue if entry.entry_id not in doomed]
        if cursor_went:
            self._refill(resume - 1)
            if resume < len(self._queue):
                self._current = self._queue[resume].entry_id
                self._start_current()
            else:
                self._current = None
                self._stop_playback()
            self._announce()
        return self._queue_edited()

    def queue_move(self, entry_id: int, after_entry_id: int | None) -> QueueState:
        from_index = self._index_of(entry_id)
        if from_index < 0:
            raise not_found(f"no queue entry {entry_id}", entry_id=entry_id)
        at = self._landing_index(after_entry_id, self._cursor() + 1)
        entry = self._queue.pop(from_index)
        if from_index < at:
            at -= 1
        self._queue.insert(at, replace(entry, origin=QueueOrigin.USER))
        self._promote_through(at)
        return self._queue_edited()

    def queue_clear(self) -> QueueState:
        entry = self._current_entry()
        self._queue = [entry] if entry is not None else []
        self._current = entry.entry_id if entry is not None else None
        # Clearing drops the source, so nothing refills behind it.
        self._source = None
        self._source_ids = []
        self._source_next = 0
        return self._queue_edited()

    # Engine reports, posted in from the engine thread

    def on_track_ended(self) -> None:
        self._failures = 0
        if self._repeat is RepeatMode.SONG and self.current_song_id() is not None:
            self._restart_current()
            self._announce()
            return
        self._advance(1)

    def on_track_failed(self, message: str) -> None:
        if self._swallowed:
            # The command that hit this already answered with an error, and the engine's report is only now catching up.
            self._swallowed -= 1
            return
        song_id = self.current_song_id()
        self._bus.publish(EventType.TRACK_FAILED, {"song_id": song_id, "message": message})
        self._failures += 1
        if self._failures >= MAX_CONSECUTIVE_FAILURES:
            log.error("stopping playback after %d consecutive failures", self._failures)
            self._stop_playback()
            return
        self._advance(1, count_failure=False)

    # Internals

    def _new_entry(self, song_id: int, origin: QueueOrigin) -> QueueEntry:
        return QueueEntry(entry_id=next(self._entry_ids), song_id=song_id, origin=origin)

    def _index_of(self, entry_id: int | None) -> int:
        if entry_id is None:
            return -1
        return next((index for index, entry in enumerate(self._queue) if entry.entry_id == entry_id), -1)

    def _cursor(self) -> int:
        return self._index_of(self._current)

    def _current_entry(self) -> QueueEntry | None:
        index = self._cursor()
        return self._queue[index] if index >= 0 else None

    def _user_boundary(self) -> int:
        """Where the autofill tail starts: one past the last user entry ahead of the cursor."""
        cursor = self._cursor()
        boundary = cursor + 1
        for index in range(cursor + 1, len(self._queue)):
            if self._queue[index].origin is QueueOrigin.USER:
                boundary = index + 1
        return boundary

    def _landing_index(self, after_entry_id: int | None, fallback: int) -> int:
        if after_entry_id is None:
            return fallback
        index = self._index_of(after_entry_id)
        if index < 0:
            raise not_found(f"no queue entry {after_entry_id}", entry_id=after_entry_id)
        if index < self._cursor():
            raise invalid_argument("the history is not a destination", entry_id=after_entry_id)
        return index + 1

    def _absorb_history(self) -> None:
        """The history is all `user`, so rewinding onto a drawn entry cannot strand autofill ahead of the cursor."""
        for position in range(self._cursor()):
            entry = self._queue[position]
            if entry.origin is not QueueOrigin.USER:
                self._queue[position] = replace(entry, origin=QueueOrigin.USER)

    def _promote_through(self, index: int) -> None:
        """Whatever the user placed something beyond becomes theirs too, which keeps the user run contiguous."""
        for position in range(self._cursor() + 1, index):
            entry = self._queue[position]
            if entry.origin is not QueueOrigin.USER:
                self._queue[position] = replace(entry, origin=QueueOrigin.USER)

    def _announce(self) -> PlaybackState:
        state = self.playback_state()
        self._bus.publish(EventType.PLAYBACK_CHANGED, {"playback": state.to_dict()})
        return state

    def _stop_playback(self) -> None:
        self._engine.stop()
        self._status = PlaybackStatus.IDLE
        self._duration = 0.0

    def _queue_edited(self) -> QueueState:
        self._maintain()
        self._bus.queue_changed()
        return self.queue_state()

    def _load_queue(self, song_ids: Sequence[int], paused: bool = False, strict: bool = False) -> None:
        self._queue = [self._new_entry(song_id, QueueOrigin.USER) for song_id in song_ids]
        self._current = self._queue[0].entry_id if self._queue else None
        self._source_next = min(self._source_next + len(song_ids), len(self._source_ids))
        self._maintain()
        self._bus.queue_changed()
        self._failures = 0
        if not self._queue:
            return
        try:
            self._start_current(paused, strict)
        except ProtocolError:
            self._discard_queue()
            raise

    def _discard_queue(self) -> None:
        """A named song that would not open leaves nothing playing and nothing to refill from, which beats a queue built around a song that never started."""
        self._queue = []
        self._current = None
        self._source = None
        self._source_ids = []
        self._source_next = 0
        self._stop_playback()
        self._bus.queue_changed()

    def _require_on_disk(self, song_id: int) -> None:
        song = self._library.get_songs([song_id])
        if not song or not song[0].found_on_disk:
            raise track_absent(song_id)

    def _advance(self, step: int, count_failure: bool = True) -> None:
        if count_failure:
            self._failures = 0
        # A queue that has run out leaves nothing current, and stepping back from there means the last entry.
        position = self._cursor() if self._current is not None else len(self._queue)
        target = max(0, position + step)
        # Refilling around a target that has just run off the end is what keeps playlist repeat going.
        if self._refill(target):
            self._bus.queue_changed()
        if target >= len(self._queue):
            self._current = None
            self._stop_playback()
            self._announce()
            return
        self._current = self._queue[target].entry_id
        self._absorb_history()
        if self._trim():
            self._bus.queue_changed()
        self._start_current()
        self._announce()

    def _start_current(self, paused: bool = False, strict: bool = False) -> None:
        if self._open_current(paused, strict):
            self._counted = False
            if not paused:
                self._count_current()
            self._bus.publish(EventType.TRACK_CHANGED, {"song_id": self.current_song_id(), "cursor": self._cursor()})

    def _count_current(self) -> None:
        """A song opened paused is counted when it first plays, and only then."""
        song_id = self.current_song_id()
        if self._counted or song_id is None:
            return
        self._counted = True
        self._library.mark_played(song_id)

    def _restart_current(self) -> None:
        """This reloads rather than rewinding a finished stream,
        because an engine that has run to the end has already torn its output down.
        """
        self._open_current()

    def _open_current(self, paused: bool = False, strict: bool = False) -> bool:
        """Strict means a command named this song, so it hears about the failure instead of the queue moving on."""
        song_id = self.current_song_id()
        if song_id is None:
            self.stop()
            return False
        song = self._library.get_songs([song_id])
        path = self._library.path_for(song[0]) if song else None
        if path is None or not song[0].found_on_disk:
            if strict:
                raise track_absent(song_id)
            self.on_track_failed(f"song {song_id} is not on disk")
            return False
        self._duration = song[0].duration
        if not self._engine.load(str(path)):
            # The engine has already reported the failure, and playing an engine with no stream would report it again.
            self._stop_playback()
            if strict:
                # That report is queued behind this command as a deferred job, and answering twice is what the count prevents.
                self._swallowed += 1
                raise playback_failed("the file could not be opened for playback", song_id=song_id)
            return False
        # Loading does not start an engine, so a paused open is silent and ready for `play`.
        if paused:
            self._status = PlaybackStatus.PAUSED
            return True
        self._engine.play()
        self._status = PlaybackStatus.PLAYING
        return True

    def _flush_ahead(self) -> None:
        """Throws away the autofill tail."""
        del self._queue[self._user_boundary() :]

    def _maintain(self) -> bool:
        """Trim the history and refill. Report whether the queue moved."""
        cursor = self._cursor()
        if cursor < 0:
            # Nothing is playing, so there is no position to stock ahead of. The next play command reseeds.
            return False
        refilled = self._refill(cursor)
        trimmed = self._trim()
        return refilled or trimmed

    def _refill(self, ahead_of: int) -> bool:
        """Tops the queue up past the given position. User entries count toward that total."""
        if self._repeat is RepeatMode.NONE or not self._source_ids:
            return False
        added = False
        while len(self._queue) - ahead_of - 1 < AHEAD_LIMIT:
            self._queue.append(self._new_entry(self._draw(), QueueOrigin.AUTOFILL))
            added = True
        return added

    def _trim(self) -> bool:
        trimmed = False
        while self._cursor() > HISTORY_LIMIT:
            self._queue.pop(0)
            trimmed = True
        return trimmed

    def _maintain_and_publish(self) -> None:
        if self._maintain():
            self._bus.queue_changed()

    def _draw(self) -> int:
        if self._shuffle:
            return random.choice(self._source_ids)
        if self._source_next >= len(self._source_ids):
            self._source_next = 0
        song_id = self._source_ids[self._source_next]
        self._source_next += 1
        return song_id
