import logging
import threading
from collections.abc import Callable

import sounddevice as sd
import soundfile as sf

from core.playback.engine import PlaybackEngine

log = logging.getLogger(__name__)


class SoundDeviceEngine(PlaybackEngine):
    """libsndfile decoding into a PortAudio stream.
    The stream pulls frames on PortAudio's thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file: sf.SoundFile | None = None
        self._stream: sd.OutputStream | None = None
        self._volume = 1.0
        self._frames = 0
        self._samplerate = 0
        self._paused = False
        self._reached_end = False
        self._ended: Callable[[], None] = lambda: None
        self._failed: Callable[[str], None] = lambda message: None

    def load(self, path: str) -> bool:
        self._teardown()
        try:
            handle = sf.SoundFile(path)
        except Exception as failure:
            log.warning("could not open %s: %s", path, failure)
            self._failed(f"could not open the file: {failure}")
            return False
        with self._lock:
            self._file = handle
            self._frames = handle.frames
            self._samplerate = handle.samplerate
        try:
            self._stream = sd.OutputStream(
                samplerate=handle.samplerate,
                channels=handle.channels,
                dtype="float32",
                callback=self._fill,
                finished_callback=self._on_finished,
            )
        except Exception as failure:
            log.warning("could not open an output stream for %s: %s", path, failure)
            self._teardown()
            self._failed(f"could not open an audio device: {failure}")
            return False
        return True

    def play(self) -> None:
        if self._stream is None:
            self._failed("nothing is loaded")
            return
        self._paused = False
        try:
            self._stream.start()
        except Exception as failure:
            self._failed(f"could not start playback: {failure}")

    def pause(self) -> None:
        self._paused = True
        if self._stream is not None:
            self._stream.stop()

    def stop(self) -> None:
        self._paused = False
        self._teardown()

    def seek_to(self, seconds: float) -> None:
        with self._lock:
            if self._file is None:
                return
            frame = int(max(0.0, seconds) * self._samplerate)
            self._file.seek(min(frame, self._frames))

    def set_volume(self, level: float) -> None:
        self._volume = min(1.0, max(0.0, level))

    def position(self) -> float:
        with self._lock:
            if self._file is None or self._samplerate == 0:
                return 0.0
            read = self._file.tell()
        # tell() is where decoding has reached, which leads the speakers by the stream's latency.
        buffered = self._stream.latency if self._stream is not None else 0.0
        return max(0.0, read / self._samplerate - float(buffered or 0.0))

    def duration(self) -> float:
        if self._samplerate == 0:
            return 0.0
        return self._frames / self._samplerate

    def is_playing(self) -> bool:
        return self._stream is not None and self._stream.active and not self._paused

    def on_ended(self, callback: Callable[[], None]) -> None:
        self._ended = callback

    def on_failed(self, callback: Callable[[str], None]) -> None:
        self._failed = callback

    def close(self) -> None:
        self._teardown()

    def _fill(self, outdata, frames: int, _time, status) -> None:
        if status:
            log.debug("output stream reported %s", status)
        with self._lock:
            if self._file is None:
                outdata.fill(0)
                raise sd.CallbackStop
            block = self._file.read(frames, dtype="float32", always_2d=True)
        supplied = len(block)
        if supplied:
            outdata[:supplied] = block * self._volume
        if supplied < frames:
            outdata[supplied:] = 0
            self._reached_end = True
            raise sd.CallbackStop

    def _on_finished(self) -> None:
        """Fires whenever the stream stops, so only a run off the end of the file counts as an end."""
        if not self._reached_end:
            return
        self._reached_end = False
        self._ended()

    def _teardown(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            self._reached_end = False
            try:
                stream.abort()
                stream.close()
            except Exception:
                log.exception("output stream did not close cleanly")
        with self._lock:
            if self._file is not None:
                self._file.close()
            self._file = None
            self._frames = 0
            self._samplerate = 0
