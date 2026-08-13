import json
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path

from entry.paths import CONFIG_DIR, PROJECT_ROOT

CONFIG_FILE = CONFIG_DIR / "config.json"

# Sounddevice engine cannot play m4a, aac and wma.
AUDIO_EXTENSIONS = [".opus", ".ogg", ".flac", ".wav", ".mp3", ".aiff"]


@dataclass
class Config:
    library_folder: str = "recordings"
    database_file: str = "deltamusic.sqlite3"
    audio_extensions: list[str] = field(default_factory=lambda: list(AUDIO_EXTENSIONS))
    frontends: list[str] = field(default_factory=lambda: ["qt"])
    initial_volume: float = 0.8
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


def load_or_create(path: Path = CONFIG_FILE) -> Config:
    """Reads config.json, writing it on first run and topping it up when a field is added."""
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    known = set(Config.__dataclass_fields__)
    config = Config(**{key: value for key, value in raw.items() if key in known})
    if set(raw) != known:
        _write(path, config)
    return config


def _write(path: Path, config: Config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
