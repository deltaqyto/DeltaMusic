"""The capture engine: PortAudio stream -> loop buffer -> active recording."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from ...errors import (
    AlreadyRecordingError,
    CaptureError,
    NotRecordingError,
    RecordingLimitError,
    StreamNotRunningError,
)
from ...ringbuffer import RingBuffer
from ...types import CaptureResult
from .config import WindowsCaptureConfig
from .devices import DeviceInfo, find_device

log = logging.getLogger(__name__)

DTYPE = np.float32


@dataclass
class _Active:
    start_total: int          # ring.total_frames value the recording begins at
    requested_offset: int     # frames of pre-roll asked for
    granted_offset: int       # frames of pre-roll actually available
    started_at: float         # wall clock, for logging only
    blocks: List[np.ndarray] = field(default_factory=list)
    frames: int = 0
    truncated: bool = False   # hit max_recording_seconds


class CaptureEngine:
    """Owns the input stream, the loop buffer, and the active recording.

    One lock serialises the audio callback against `begin`/`end`.
    All work under it is bounded, so the callback stays real-time safe apart from the amortised allocation of appending to a list.
    """

    def __init__(self, config: WindowsCaptureConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._stream = None
        self._device: Optional[DeviceInfo] = None
        self._ring: Optional[RingBuffer] = None
        self._active: Optional[_Active] = None
        self._samplerate: int = 0
        self._channels: int = 0
        self._xruns = 0
        self._closed = False

    @property
    def is_running(self) -> bool:
        return self._stream is not None and self._stream.active

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._active is not None

    @property
    def samplerate(self) -> int:
        return self._samplerate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def device(self) -> Optional[DeviceInfo]:
        return self._device

    @property
    def xruns(self) -> int:
        """Count of callbacks that reported input overflow/underflow."""
        return self._xruns

    @property
    def input_latency_seconds(self) -> float:
        """How far captured audio trails real time."""
        stream = self._stream
        if stream is None:
            return 0.0
        try:
            return float(stream.latency)
        except (TypeError, ValueError):  # pragma: no cover
            return 0.0

    def start(self) -> DeviceInfo:
        """Open the device and begin filling the loop buffer."""
        if self._closed:
            raise CaptureError("engine has been closed; construct a new one")
        if self.is_running:
            return self._device  # type: ignore[return-value]

        import sounddevice as sd  # deferred: see devices._sd

        device = find_device(self._config.device, self._config.hostapi)
        samplerate = int(self._config.samplerate or round(device.default_samplerate))
        channels = self._config.channels
        if channels is None:
            channels = min(2, device.max_input_channels)
        if channels > device.max_input_channels:
            raise CaptureError(
                f"{device.name!r} offers {device.max_input_channels} input channel(s), "
                f"{channels} requested"
            )

        capacity = max(1, int(round(self._config.loop_seconds * samplerate)))
        ring = RingBuffer(capacity, channels, dtype=DTYPE)

        try:
            stream = sd.InputStream(
                device=device.index,
                samplerate=samplerate,
                channels=channels,
                dtype="float32",
                blocksize=self._config.blocksize,
                latency=self._config.latency,
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            raise CaptureError(f"could not open {device.name!r}: {exc}") from exc

        self._device = device
        self._samplerate = samplerate
        self._channels = channels
        self._ring = ring
        self._stream = stream
        self._xruns = 0
        log.info(
            "capture started on %s @ %d Hz, %d ch, %.0f ms loop buffer",
            device.name,
            samplerate,
            channels,
            self._config.loop_seconds * 1000,
        )
        return device

    def stop(self) -> None:
        """Stop the stream. Any in-flight recording is discarded."""
        stream, self._stream = self._stream, None
        with self._lock:
            self._active = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        if self._ring is not None:
            self._ring.clear()

    def close(self) -> None:
        self.stop()
        self._closed = True

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            # Input overflow means the loop buffer has a hole in it.
            self._xruns += 1
            log.warning("stream status: %s", status)
        try:
            block = np.asarray(indata, dtype=DTYPE)
            if block.ndim == 1:
                block = block.reshape(-1, 1)
            with self._lock:
                if self._ring is not None:
                    self._ring.write(block)
                active = self._active
                if active is not None and not active.truncated:
                    limit = int(
                        self._config.max_recording_seconds * self._samplerate
                    )
                    if active.frames + block.shape[0] > limit:
                        active.truncated = True
                    else:
                        active.blocks.append(block.copy())
                        active.frames += block.shape[0]
        except Exception:  # never let an exception cross into PortAudio
            log.exception("audio callback failed; block dropped")

    def begin(self, offset_ms: float = 0.0, *, clamp_offset: bool = True) -> _Active:
        """Open a recording, back-dated by `offset_ms`.

        `clamp_offset` takes what the buffer holds when it holds less than asked for. An offset beyond the buffer's whole capacity is always an error, since no amount of waiting would make it satisfiable.
        """
        if not self.is_running or self._ring is None:
            raise StreamNotRunningError("capture stream is not running")
        if offset_ms < 0:
            raise ValueError("offset_ms must be >= 0")

        offset_frames = int(round(offset_ms * self._samplerate / 1000.0))
        if offset_frames > self._ring.capacity:
            raise ValueError(
                f"offset of {offset_ms:.1f} ms exceeds the "
                f"{self._config.loop_seconds * 1000:.0f} ms loop buffer"
            )

        with self._lock:
            if self._active is not None:
                raise AlreadyRecordingError("a recording is already in progress")
            preroll, total = self._ring.read_last(offset_frames)
            if preroll.shape[0] < offset_frames and not clamp_offset:
                raise ValueError(
                    f"only {preroll.shape[0] / self._samplerate * 1000:.1f} ms of "
                    f"pre-roll is buffered, {offset_ms:.1f} ms requested"
                )
            active = _Active(
                start_total=total - preroll.shape[0],
                requested_offset=offset_frames,
                granted_offset=preroll.shape[0],
                started_at=time.time(),
            )
            if preroll.shape[0]:
                active.blocks.append(preroll)
                active.frames = preroll.shape[0]
            self._active = active
            return active

    def end(self, offset_ms: float = 0.0) -> CaptureResult:
        """Close the recording and return its audio.

        `offset_ms` discards that much of the tail, measured against audio actually delivered by the device, which lags real time by roughly one block plus the input latency.
        Hitting `max_recording_seconds` discards the audio as a probably runaway (and to keep memory under check).
        """
        if offset_ms < 0:
            raise ValueError("offset_ms must be >= 0")

        with self._lock:
            active, self._active = self._active, None
        if active is None:
            raise NotRecordingError("no recording is in progress")

        if active.truncated:
            active.blocks.clear()
            raise RecordingLimitError(
                f"recording exceeded max_recording_seconds "
                f"({self._config.max_recording_seconds:.0f}s) and was discarded"
            )

        if active.blocks:
            audio = np.concatenate(active.blocks, axis=0)
        else:
            audio = np.zeros((0, self._channels), dtype=DTYPE)
        active.blocks.clear()

        sr = self._samplerate or 1
        trim_frames = int(round(offset_ms * sr / 1000.0))
        if trim_frames:
            if trim_frames >= audio.shape[0]:
                raise ValueError(
                    f"stop offset of {offset_ms:.1f} ms would consume the whole "
                    f"{audio.shape[0] / sr * 1000:.1f} ms recording; "
                    "the recording has been discarded"
                )
            audio = audio[:-trim_frames]

        return CaptureResult(
            audio=audio,
            samplerate=self._samplerate,
            channels=self._channels,
            duration_seconds=audio.shape[0] / sr,
            requested_offset_ms=active.requested_offset * 1000.0 / sr,
            granted_offset_ms=active.granted_offset * 1000.0 / sr,
            trimmed_ms=trim_frames * 1000.0 / sr,
            started_at=active.started_at,
            stopped_at=time.time(),
            xruns=self._xruns,
            truncated=active.truncated,
        )

    def elapsed_seconds(self) -> Optional[float]:
        """Duration of the open recording so far, or None if none is open."""
        with self._lock:
            if self._active is None or not self._samplerate:
                return None
            return self._active.frames / self._samplerate

    def abort(self) -> bool:
        """Discard an in-flight recording. Returns True if one was open."""
        with self._lock:
            had = self._active is not None
            self._active = None
        return had
