from PyQt6.QtCore import QObject, pyqtSignal

from frontends.core_client import CoreClient
from protocol.types.event import Event


class EventBridge(QObject):
    """Carries events from the runtime thread onto the GUI thread.
    """

    arrived = pyqtSignal(object)

    def __init__(self, client: CoreClient):
        super().__init__()
        self._client = client

    def start(self) -> None:
        self._client.attach(self._on_event)

    def stop(self) -> None:
        self._client.detach()

    def _on_event(self, event: Event) -> None:
        self.arrived.emit(event)
