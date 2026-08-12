import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

from core.library.library import Library
from core.playback.controller import PlaybackController
from entry.paths import CONFIG_DIR
from protocol.errors import ProtocolError
from protocol.types.playback_state import PlaybackState
from protocol.types.repeat_mode import RepeatMode

T = TypeVar("T")

SESSION_FILE = CONFIG_DIR / "session.json"
SAVE_DEBOUNCE_SECONDS = 5.0

log = logging.getLogger(__name__)


@dataclass
class Remembered:
    """The session core puts back on start."""

    volume: float | None = None
    shuffle: bool | None = None
    repeat: str | None = None
    song_id: int | None = None
    playlist_id: int | None = None


class SessionMemory:
    """Carries the session across runs"""

    def __init__(self, path: Path = SESSION_FILE):
        self._path = path
        self._remembered = _load(path)
        self._due: float | None = None

    def restore(self, controller: PlaybackController, library: Library) -> None:
        """Playback always comes back paused at position 0."""
        saved = self._remembered
        if saved.volume is not None:
            _quietly(lambda: controller.set_volume(saved.volume))
        if saved.repeat is not None:
            _quietly(lambda: controller.set_repeat(saved.repeat))
        if saved.shuffle is not None:
            _quietly(lambda: controller.set_shuffle(saved.shuffle))
        if saved.song_id is None:
            return
        if saved.playlist_id is not None and self._restore_from_playlist(controller, library, saved):
            return
        # The playlist is gone, no longer holds the song, or would not open, so the song alone is the best that can be restored.
        _quietly(lambda: controller.play_songs([saved.song_id], paused=True))

    @staticmethod
    def _restore_from_playlist(controller: PlaybackController, library: Library, saved: Remembered) -> bool:
        song_ids = _quietly(lambda: library.song_ids_in(saved.playlist_id)) or []
        if saved.song_id not in song_ids:
            return False
        start = song_ids.index(saved.song_id)
        opened = _quietly(lambda: controller.play_playlist(saved.playlist_id, start, paused=True))
        return opened is not None

    def observe(self, playback: PlaybackState, playlist_id: int | None) -> None:
        """Called on every heartbeat. The write is debounced, so only a real change may restart the clock or it would never fire."""
        fields: dict[str, Any] = {
            "shuffle": playback.shuffle,
            "repeat": playback.repeat.value,
            "playlist_id": playlist_id,
        }
        # Deliberately do not save mute state, and don't allow saving 0 volume so it doesn't come back silent
        if playback.volume > 0.0:
            fields["volume"] = playback.volume
        if playback.song_id is not None:
            fields["song_id"] = playback.song_id

        changed = [key for key, value in fields.items() if getattr(self._remembered, key) != value]
        if changed:
            for key in changed:
                setattr(self._remembered, key, fields[key])
            self._due = time.monotonic() + SAVE_DEBOUNCE_SECONDS
        elif self._due is not None and time.monotonic() >= self._due:
            self.flush()

    def flush(self) -> None:
        if self._due is None:
            return
        self._due = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(asdict(self._remembered), indent=2) + "\n", encoding="utf-8")
        except OSError as failure:
            log.warning("could not write %s: %s", self._path, failure)


def _quietly(work: Callable[[], T]) -> T | None:
    try:
        return work()
    except ProtocolError as failure:
        log.info("could not restore the session: %s", failure.error.message)
        return None


def _load(path: Path) -> Remembered:
    """Invalid files are ignored with defaults to ensure some kind of load"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        if path.exists():
            log.warning("ignoring %s: %s", path, failure)
        return Remembered()
    if not isinstance(raw, dict):
        log.warning("ignoring %s: not an object", path)
        return Remembered()

    remembered = Remembered()
    remembered.volume = _volume(raw.get("volume"))
    remembered.repeat, remembered.shuffle = _modes(raw.get("repeat"), raw.get("shuffle"))
    remembered.song_id = _identifier(raw.get("song_id"))
    remembered.playlist_id = _identifier(raw.get("playlist_id"))
    return remembered


def _volume(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return min(1.0, max(0.0, float(value)))


def _modes(repeat: Any, shuffle: Any) -> tuple[str | None, bool | None]:
    """Shuffle needs something to draw from, so the pair is dropped together when it does not hold."""
    if not isinstance(shuffle, bool):
        return None, None
    try:
        mode = RepeatMode(repeat)
    except ValueError:
        return None, None
    if shuffle and mode is RepeatMode.NONE:
        return None, None
    return mode.value, shuffle


def _identifier(value: Any) -> int | None:
    # `All Tracks` is playlist 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value
