import json
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from entry.paths import CONFIG_DIR, PROJECT_ROOT
from protocol.types.shuffle_method import ShuffleMethod

CONFIG_FILE = CONFIG_DIR / "config.json"

# Sounddevice engine cannot play m4a, aac and wma.
AUDIO_EXTENSIONS = [".opus", ".ogg", ".flac", ".wav", ".mp3", ".aiff"]

# Settings that are loaded only on startup
LIVE_SETTINGS = frozenset({"shuffle_method"})

# Inclusive bounds, with None for open.
_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "initial_volume": (0.0, 1.0),
    "peer_port": (1, 65535),
    "remote_control_port": (1, 65535),
    "visibility_seconds": (1, None),
    "max_concurrent_transfers": (1, None),
    "transfer_space_reserve_bytes": (0, None),
}


@dataclass
class Config:
    library_folder: str = "recordings"
    database_file: str = "deltamusic.sqlite3"
    audio_extensions: list[str] = field(default_factory=lambda: list(AUDIO_EXTENSIONS))
    frontends: list[str] = field(default_factory=lambda: ["qt"])
    initial_volume: float = 0.8
    shuffle_method: str = ShuffleMethod.TRUE_RANDOM.value
    private_library: bool = False
    peer_enabled: bool = True
    peer_port: int = 47822
    core_name: str = field(default_factory=socket.gethostname)
    visibility_seconds: int = 300
    max_concurrent_transfers: int = 2
    transfer_space_reserve_bytes: int = 1 << 30  # 1 GB
    remote_control_enabled: bool = False
    remote_control_port: int = 47821

    @property
    def library_path(self) -> Path:
        return (PROJECT_ROOT / self.library_folder).resolve()

    @property
    def database_path(self) -> Path:
        return self.library_path / self.database_file


_TEMPLATE = Config()


def check_setting(key: str, value: Any) -> Any:
    """Return the value in the form used by `Config`. Raises ValueError if a setting is invalid."""
    if key not in Config.__dataclass_fields__:
        raise ValueError(f"no setting '{key}'")
    kind = type(getattr(_TEMPLATE, key))
    if kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"'{key}' must be true or false")
    elif kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{key}' must be a whole number")
    elif kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{key}' must be a number")
        value = float(value)
    elif kind is str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{key}' must be text")
        value = value.strip()
    else:
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"'{key}' must be a list of text")
        value = [item.strip() for item in value]

    low, high = _BOUNDS.get(key, (None, None))
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f"'{key}' must be {_range_text(low, high)}")
    if key == "shuffle_method" and value not in {method.value for method in ShuffleMethod}:
        raise ValueError(f"'{value}' is not a shuffle method")
    if key == "audio_extensions" and not all(item.startswith(".") for item in value):
        raise ValueError("'audio_extensions' entries must start with a dot")
    return value


def _range_text(low: float | None, high: float | None) -> str:
    if low is not None and high is not None:
        return f"between {low:g} and {high:g}"
    return f"at least {low:g}" if low is not None else f"at most {high:g}"


def load_or_create(path: Path = CONFIG_FILE) -> Config:
    """Reads config.json, writing it on first run and topping it up when a field is added."""
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    known = set(Config.__dataclass_fields__)
    config = Config(**{key: value for key, value in raw.items() if key in known})
    if set(raw) != known:
        save(config, path)
    return config


def save(config: Config, path: Path = CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
