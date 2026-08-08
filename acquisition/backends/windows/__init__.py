"""The Windows backend: virtual loopback cable + SMTC.

Windows has no first-class way to capture what one application is playing,
so the player is pointed at a virtual cable and the cable's output is opened
as an ordinary recording device.

Cable and app id setup is documented in SETUP.md.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Mapping

from ...interfaces import AudioSource, Backend, SessionSource
from .config import WindowsCaptureConfig
from .recorder import Recorder
from .session import SessionWatcher


class WindowsBackend(Backend):
    """Pairs the loopback Recorder with the SMTC watcher."""

    name = "windows"

    def __init__(self, settings: Mapping[str, Any]) -> None:
        known = set(WindowsCaptureConfig.__dataclass_fields__)
        unknown = set(settings) - known
        if unknown:
            raise ValueError(
                f"unknown windows setting(s) {sorted(unknown)}; "
                f"valid settings are {sorted(known)}"
            )
        self._config = WindowsCaptureConfig(**dict(settings))

    @classmethod
    def is_available(cls) -> bool:
        # The WinRT import is the real gate; the platform check keeps the message honest elsewhere.
        if sys.platform != "win32":
            return False
        try:
            import winrt.windows.media.control  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def config(self) -> WindowsCaptureConfig:
        return self._config

    def create_audio_source(self) -> AudioSource:
        return Recorder(self._config)

    def create_session_source(self, app_id: str) -> SessionSource:
        return SessionWatcher(app_id)

    @staticmethod
    def default_settings() -> Dict[str, Any]:
        return {
            "device": "CABLE Output (VB-Audio Virtual Cable)",
            "hostapi": "WASAPI",
            "samplerate": None,
            "channels": 2,
            "loop_seconds": 2.0,
            "max_recording_seconds": 900.0,
        }

    @staticmethod
    def describe_devices() -> List[str]:
        from .devices import list_input_devices

        return [str(device) for device in list_input_devices()]


__all__ = ["WindowsBackend", "Recorder", "SessionWatcher", "WindowsCaptureConfig"]
