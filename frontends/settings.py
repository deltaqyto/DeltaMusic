import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from entry.paths import CONFIG_DIR
from protocol.types.repeat_mode import RepeatMode

SETTINGS_FILE = CONFIG_DIR / "settings.json"

log = logging.getLogger(__name__)


@dataclass
class Settings:
    """What a frontend remembers between runs"""

    volume: float = 0.8
    shuffle: bool = False
    repeat: str = RepeatMode.PLAYLIST.value
    song_id: int | None = None
    playlist_id: int | None = None

    def save(self, path: Path = SETTINGS_FILE) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        except OSError as failure:
            log.warning("could not write %s: %s", path, failure)


def load(path: Path = SETTINGS_FILE) -> Settings:
    """This must never fail to load. Invalid files are ignored with defaults"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        if path.exists():
            log.warning("ignoring %s: %s", path, failure)
        return Settings()
    if not isinstance(raw, dict):
        log.warning("ignoring %s: not an object", path)
        return Settings()

    settings = Settings()
    settings.volume = _volume(raw.get("volume"), settings.volume)
    settings.repeat, settings.shuffle = _modes(raw.get("repeat"), raw.get("shuffle"), settings)
    settings.song_id = _identifier(raw.get("song_id"))
    settings.playlist_id = _identifier(raw.get("playlist_id"))
    return settings


def _volume(value: Any, fallback: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return fallback
    return min(1.0, max(0.0, float(value)))


def _modes(repeat: Any, shuffle: Any, defaults: Settings) -> tuple[str, bool]:
    """Shuffle needs something to draw from, so the pair is dropped together when it does not hold."""
    if not isinstance(shuffle, bool):
        return defaults.repeat, defaults.shuffle
    try:
        mode = RepeatMode(repeat)
    except ValueError:
        return defaults.repeat, defaults.shuffle
    if shuffle and mode is RepeatMode.NONE:
        return defaults.repeat, defaults.shuffle
    return mode.value, shuffle


def _identifier(value: Any) -> int | None:
    # `All Tracks` is playlist 0, so only a negative id is nonsense.
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value
