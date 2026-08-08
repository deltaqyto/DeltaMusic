"""The Windows AudioSource.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from ...errors import CaptureError
from ...interfaces import AudioSource
from ...types import CaptureResult, SourceInfo
from .capture import CaptureEngine
from .config import WindowsCaptureConfig
from .devices import DeviceInfo

log = logging.getLogger(__name__)


class Recorder(AudioSource):
    def __init__(self, config: Optional[WindowsCaptureConfig] = None) -> None:
        self._config = config or WindowsCaptureConfig()
        self._engine = CaptureEngine(self._config)
        self._lock = threading.RLock()

    def open(self) -> SourceInfo:
        with self._lock:
            device = self._engine.start()
        return SourceInfo(
            name=device.name,
            backend="windows",
            samplerate=self._engine.samplerate,
            channels=self._engine.channels,
            detail=device.hostapi,
        )

    def close(self) -> None:
        """Stop capture and release the device. Discards any open recording."""
        with self._lock:
            if self._engine.is_recording:
                log.warning("closing while a recording is open. Discarding it")
            self._engine.close()

    def __enter__(self) -> "Recorder":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def config(self) -> WindowsCaptureConfig:
        return self._config

    @property
    def device(self) -> Optional[DeviceInfo]:
        """The backend's own richer device record. Not part of the port."""
        return self._engine.device

    @property
    def is_running(self) -> bool:
        return self._engine.is_running

    @property
    def is_recording(self) -> bool:
        return self._engine.is_recording

    @property
    def samplerate(self) -> int:
        return self._engine.samplerate

    @property
    def channels(self) -> int:
        return self._engine.channels

    @property
    def prebuffer_ms(self) -> float:
        return self._config.loop_seconds * 1000.0

    @property
    def xruns(self) -> int:
        """Stream dropouts since `open`. Non-zero means lost audio."""
        return self._engine.xruns

    @property
    def input_latency_ms(self) -> float:
        return self._engine.input_latency_seconds * 1000.0

    def start_recording(self, offset_ms: float = 0.0, *, clamp_offset: bool = True) -> float:
        """Begin recording, back-dated `offset_ms` into the loop buffer, returning the pre-roll granted.
        """
        with self._lock:
            active = self._engine.begin(offset_ms, clamp_offset=clamp_offset)
            granted = active.granted_offset * 1000.0 / max(1, self._engine.samplerate)
        if granted + 0.5 < offset_ms:
            log.warning(
                "requested %.1f ms of pre-roll, only %.1f ms was buffered",
                offset_ms,
                granted,
            )
        return granted

    def stop_capture(self, trim_ms: float = 0.0) -> CaptureResult:
        """Close the recording and return its audio without writing it.
        """
        with self._lock:
            return self._engine.end(trim_ms)

    def abort_recording(self, reason: str = "") -> bool:
        """Reject the open recording and free its memory."""
        with self._lock:
            aborted = self._engine.abort()
        if aborted:
            log.info("recording rejected%s", f": {reason}" if reason else "")
        return aborted

    def elapsed_seconds(self) -> Optional[float]:
        """Duration of the open recording so far, or None if none is open."""
        return self._engine.elapsed_seconds()


__all__ = ["Recorder", "CaptureError"]
