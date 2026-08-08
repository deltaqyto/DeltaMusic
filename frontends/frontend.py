from typing import Protocol

from frontends.core_client import CoreClient


class Frontend(Protocol):
    """A core interface implementation
    """

    def __init__(self, client: CoreClient): ...

    # Blocking call
    def run(self) -> int: ...

    def stop(self) -> None: ...
