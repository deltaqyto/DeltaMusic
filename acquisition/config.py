"""User-facing configuration, loaded from and written to config/acquisition_config.json."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from entry.paths import CONFIG_DIR, PROJECT_ROOT

from .encoding.formats import resolve
from .encoding.naming import DEFAULT_TEMPLATE

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = CONFIG_DIR / "acquisition_config.json"


@dataclass
class AcquisitionConfig:

    # None selects by platform.
    backend: Optional[str] = None

    app_id: str = "your_app.exe"  # Monitored for track information
    poll_interval: float = 0.1

    save_directory: str = "recordings"
    filename_template: str = DEFAULT_TEMPLATE
    # 'opus', 'ogg', 'mp3' (lossy) or 'flac', 'wav' with a PCM subtype.
    container: str = "opus"
    subtype: str = "PCM_16"   # lossless containers only
    overwrite: bool = False
    dither: bool = True

    # timing
    start_lead_ms: float = 50.0
    completion_tolerance_seconds: float = 1.0
    end_tolerance_seconds: float = 2.0

    # Peak amplitude below which a block of audio counts as silent, and the
    # share of a capture that may be silent before it is considered likely broken.
    silence_threshold: float = 0.0001
    max_silence_fraction: float = 0.7

    log_level: str = "INFO"

    backends: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    _path: Optional[Path] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not str(self.app_id).strip():
            raise ValueError("config: app_id must not be empty")
        if not 0.02 <= self.poll_interval <= 5.0:
            raise ValueError("config: poll_interval must be between 0.02 and 5 seconds")
        if self.start_lead_ms < 0:
            raise ValueError("config: start_lead_ms must be >= 0")
        if self.completion_tolerance_seconds < 0:
            raise ValueError("config: completion_tolerance_seconds must be >= 0")
        if self.end_tolerance_seconds < 0:
            raise ValueError("config: end_tolerance_seconds must be >= 0")
        if not 0.0 <= self.silence_threshold < 1.0:
            raise ValueError("config: silence_threshold must be in 0..1")
        if not 0.0 < self.max_silence_fraction <= 1.0:
            raise ValueError("config: max_silence_fraction must be in 0..1")
        try:
            resolve(self.container, self.subtype)
        except ValueError as exc:
            raise ValueError(f"config: {exc}") from exc
        if str(self.log_level).upper() not in (
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        ):
            raise ValueError(f"config: unknown log_level {self.log_level!r}")

    def settings_for(self, backend_name: str) -> Dict[str, Any]:
        return dict(self.backends.get(backend_name, {}))

    @property
    def save_path(self) -> Path:
        """``save_directory`` resolved against the project root if relative."""
        path = Path(self.save_directory).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @classmethod
    def load(cls, path: Optional[Path | str] = None, *, create: bool = True) -> "AcquisitionConfig":
        """Load config from ``path``, writing a default file if absent."""
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH

        if not config_path.exists():
            if not create:
                raise FileNotFoundError(f"no config file at {config_path}")
            config = cls(backends=cls._default_backend_sections())
            config._path = config_path
            config.save(config_path)
            log.info("wrote default config to %s", config_path)
            return config

        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{config_path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{config_path} must contain a JSON object")

        # Backend sections are top-level keys named after the backend
        from .registry import backend_names

        sections: Dict[str, Dict[str, Any]] = {}
        for name in backend_names():
            if name in raw:
                section = raw.pop(name)
                if not isinstance(section, dict):
                    raise ValueError(f"{config_path}: {name!r} must be a JSON object")
                sections[name] = section

        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        known.discard("backends")
        unknown = set(raw) - known
        if unknown:
            raise ValueError(
                f"{config_path}: unknown setting(s) {sorted(unknown)}; "
                f"valid settings are {sorted(known)} plus a section per backend "
                f"({sorted(backend_names())})"
            )

        config = cls(**raw, backends=sections)
        config._path = config_path
        return config

    def save(self, path: Optional[Path | str] = None) -> Path:
        """Write the config back out as JSON, backend sections inlined as top-level keys."""
        target = Path(path) if path else (self._path or DEFAULT_CONFIG_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)

        payload: Dict[str, Any] = {
            key: value
            for key, value in asdict(self).items()
            if not key.startswith("_") and key != "backends"
        }
        payload.update(self.backends)

        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        tmp.replace(target)
        return target

    @staticmethod
    def _default_backend_sections() -> Dict[str, Dict[str, Any]]:
        from .registry import available_backends

        return {backend.name: backend.default_settings() for backend in available_backends()}
