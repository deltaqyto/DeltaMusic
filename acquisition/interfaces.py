"""The seam between the portable core and a platform implementation.

AudioSource supplies the audio and the reach-back into the recent past.
SessionSource supplies the trigger and the track names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Mapping, Optional, Sequence

from .types import CaptureResult, SourceInfo, TrackInfo


class AudioSource(ABC):
    """A running audio input holding a rolling buffer of its last `prebuffer_ms`.

    While open, the buffer is kept full and `start_recording` may begin anywhere inside it. At most one recording is open at a time.
    """

    @abstractmethod
    def open(self) -> SourceInfo:
        """Acquire the device and start filling the buffer, returning what was opened.
        Idempotent. Raises CaptureError if the device is unusable.
        """

    @abstractmethod
    def close(self) -> None:
        """Release the device, discarding any recording in flight. Safe to call twice."""

    @abstractmethod
    def start_recording(self, offset_ms: float = 0.0) -> float:
        """Begin recording `offset_ms` back into the buffer, returning the pre-roll granted.

        Granting less than asked for is not an error.
        Asking for more than `prebuffer_ms` is a ValueError.
        Starting a second recording is an AlreadyRecordingError.
        """

    @abstractmethod
    def stop_capture(self, trim_ms: float = 0.0) -> CaptureResult:
        """End the recording and return its audio, minus `trim_ms` from the end.

        The trim is in the captured stream's time base. A caller working from wall-clock timings corrects for `input_latency_ms` first.
        Raises NotRecordingError if nothing is open, and ValueError if the trim would consume the whole recording.
        """

    @abstractmethod
    def abort_recording(self, reason: str = "") -> bool:
        """Discard the in-flight recording, returning whether there was one.
        Safe to call unconditionally."""

    @property
    @abstractmethod
    def is_recording(self) -> bool: ...

    @property
    @abstractmethod
    def samplerate(self) -> int:
        """The rate negotiated with the device, which may not be the one requested."""

    @property
    @abstractmethod
    def channels(self) -> int: ...

    @property
    @abstractmethod
    def prebuffer_ms(self) -> float:
        """The buffer's real size, which may be less than the config asked for."""

    @property
    @abstractmethod
    def input_latency_ms(self) -> float:
        """How far captured audio trails real time."""

    @property
    @abstractmethod
    def xruns(self) -> int:
        """Dropouts since open. Diagnostic only."""


class SessionSource(ABC):
    """A pollable view of what a media player is doing."""

    @abstractmethod
    async def read(self) -> Optional[TrackInfo]:
        """Return the current track, or None if the player has no session.

        Does not raise: the caller polls in a loop, and a closed player or a session torn down mid-read must not end the run.
        `TrackInfo.last_updated` is the instant the platform last refreshed the position.
        """

    @abstractmethod
    def describe(self) -> str:
        """One line naming what is being watched, for the startup log."""

    async def close(self) -> None:
        return None


class Backend(ABC):
    """A platform implementation: one AudioSource, one SessionSource."""

    #: Registry key and config section name.
    name: str = ""

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Whether this backend can run on the device"""

    @abstractmethod
    def __init__(self, settings: Mapping[str, Any]) -> None:
        """Build from this backend's config section, raising ValueError for a bad or unknown setting."""

    @abstractmethod
    def create_audio_source(self) -> AudioSource: ...

    @abstractmethod
    def create_session_source(self, app_id: str) -> SessionSource: ...

    @staticmethod
    @abstractmethod
    def default_settings() -> Dict[str, Any]:
        """The config section written out when no config file exists."""

    @staticmethod
    def describe_devices() -> Sequence[str]:
        """Input devices to show for --list-devices.
        Empty for a backend that captures a fixed sink."""
        return ()
