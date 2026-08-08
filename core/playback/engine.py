from abc import ABC, abstractmethod
from collections.abc import Callable


class PlaybackEngine(ABC):
    """Decode and audio output. `on_ended` and `on_failed` fire on the engine's own thread."""

    @abstractmethod
    def load(self, path: str) -> bool:
        """False means nothing playable was opened, and the failure has already been reported."""

    @abstractmethod
    def play(self) -> None: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def seek_to(self, seconds: float) -> None: ...

    @abstractmethod
    def set_volume(self, level: float) -> None: ...

    @abstractmethod
    def position(self) -> float: ...

    @abstractmethod
    def duration(self) -> float: ...

    @abstractmethod
    def is_playing(self) -> bool: ...

    @abstractmethod
    def on_ended(self, callback: Callable[[], None]) -> None: ...

    @abstractmethod
    def on_failed(self, callback: Callable[[str], None]) -> None: ...

    @abstractmethod
    def close(self) -> None: ...
