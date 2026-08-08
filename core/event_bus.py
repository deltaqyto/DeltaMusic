import threading
from collections.abc import Iterable
from typing import Any

from core.types.client import Client, EventSink
from protocol.types.event_type import EventType
from protocol.types.library_scope import LibraryScope


class EventBus:
    """Holds the two revisions and fans events to every attached client."""

    def __init__(self) -> None:
        self._clients: list[Client] = []
        self._lock = threading.Lock()
        self.queue_revision = 0
        self.library_revision = 0

    def attach(self, name: str, sink: EventSink) -> Client:
        client = Client(name, sink)
        with self._lock:
            self._clients.append(client)
        return client

    def detach(self, client: Client) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def publish(self, event_type: EventType, payload: dict[str, Any]) -> None:
        for client in self._attached():
            client.deliver(event_type, payload)

    def bump_queue(self) -> int:
        self.queue_revision += 1
        return self.queue_revision

    def queue_changed(self) -> int:
        revision = self.bump_queue()
        self.publish(EventType.QUEUE_CHANGED, {"queue_revision": revision})
        return revision

    def library_changed(self, scope: LibraryScope, ids: Iterable[int]) -> int:
        self.library_revision += 1
        self.publish(
            EventType.LIBRARY_CHANGED,
            {"library_revision": self.library_revision, "scope": scope.value, "ids": list(ids)},
        )
        return self.library_revision

    def _attached(self) -> list[Client]:
        with self._lock:
            return list(self._clients)
