"""Settings for the Windows backend: the `"windows"` section of config/acquisition_config.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class WindowsCaptureConfig:
    """Settings for the Windows Recorder.

    Attributes:
        device: Name substring (case-insensitive) or index. `None` uses the system default input.
        hostapi: Host API substring, to disambiguate a device that appears under several APIs - which, on Windows, is all of them.
        samplerate: `None` adopts the device default.
        channels: `None` adopts the device default, capped at 2.
        loop_seconds: Size of the rolling pre-roll buffer, and so the ceiling on how far back a recording can be back-dated. The controller reads it as `prebuffer_ms`.
        blocksize: Frames per callback. 0 lets PortAudio choose, which is lowest latency but variable.
        latency: PortAudio latency hint ('low', 'high', or seconds).
        max_recording_seconds: Cap on a single in-memory recording. Tripping it discards the audio, since the metadata needed to save it has not arrived yet. Default 15 minutes (~165 MB at 48 kHz stereo).
    """

    device: Optional[Union[str, int]] = None
    hostapi: Optional[str] = None
    samplerate: Optional[int] = None
    channels: Optional[int] = None
    loop_seconds: float = 2.0
    blocksize: int = 0
    latency: Union[str, float] = "low"
    max_recording_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.loop_seconds <= 0:
            raise ValueError("windows.loop_seconds must be > 0")
        if self.loop_seconds > 120:
            raise ValueError("windows.loop_seconds > 120 is almost certainly a mistake")
        if self.samplerate is not None and not 4000 <= self.samplerate <= 768000:
            raise ValueError(f"windows.samplerate: implausible value {self.samplerate}")
        if self.channels is not None and not 1 <= self.channels <= 64:
            raise ValueError(f"windows.channels: implausible value {self.channels}")
        if self.blocksize < 0:
            raise ValueError("windows.blocksize must be >= 0")
        if self.max_recording_seconds <= 0:
            raise ValueError("windows.max_recording_seconds must be > 0")
