from __future__ import annotations

import threading
from typing import Tuple

import numpy as np


class RingBuffer:
    """Locked rolling buffer holding the most recent `capacity` frames.

    One writer (the audio callback), any number of readers. The lock is held only for pointer arithmetic and memcpy.
    """

    __slots__ = ("_buf", "_capacity", "_channels", "_write_pos", "_total", "_lock")

    def __init__(self, capacity: int, channels: int, dtype=np.float32) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1 frame")
        if channels < 1:
            raise ValueError("channels must be >= 1")
        self._capacity = int(capacity)
        self._channels = int(channels)
        self._buf = np.zeros((self._capacity, self._channels), dtype=dtype)
        self._write_pos = 0
        self._total = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def total_frames(self) -> int:
        """Frames ever written. Monotonic."""
        with self._lock:
            return self._total

    def clear(self) -> None:
        with self._lock:
            self._buf[:] = 0
            self._write_pos = 0
            self._total = 0

    def write(self, block: np.ndarray) -> None:
        """Append `block` (frames, channels), overwriting oldest frames."""
        if block.ndim != 2 or block.shape[1] != self._channels:
            raise ValueError(
                f"expected block shaped (frames, {self._channels}), got {block.shape}"
            )
        n = block.shape[0]
        if n == 0:
            return

        # A block larger than the whole buffer can only contribute its tail.
        if n >= self._capacity:
            block = block[-self._capacity :]
            n = self._capacity

        with self._lock:
            end = self._write_pos + n
            if end <= self._capacity:
                self._buf[self._write_pos : end] = block
            else:
                split = self._capacity - self._write_pos
                self._buf[self._write_pos :] = block[:split]
                self._buf[: n - split] = block[split:]
            self._write_pos = end % self._capacity
            self._total += n

    def read_last(self, frames: int) -> Tuple[np.ndarray, int]:
        """Copy out the most recent `frames` frames, clamped to what is available.
        """
        if frames < 0:
            raise ValueError("frames must be >= 0")
        with self._lock:
            available = min(self._total, self._capacity)
            n = min(frames, available)
            total = self._total
            if n == 0:
                return np.zeros((0, self._channels), dtype=self._buf.dtype), total
            start = (self._write_pos - n) % self._capacity
            end = start + n
            if end <= self._capacity:
                out = self._buf[start:end].copy()
            else:
                split = self._capacity - start
                out = np.empty((n, self._channels), dtype=self._buf.dtype)
                out[:split] = self._buf[start:]
                out[split:] = self._buf[: n - split]
            return out, total
