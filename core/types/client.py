import itertools
import logging
from collections.abc import Callable
from typing import Any

from protocol.timestamps import now, to_iso
from protocol.types.event import Event
from protocol.types.event_type import EventType

log = logging.getLogger(__name__)

EventSink = Callable[[dict[str, Any]], None]


class Client:
    """One attached client. Owns its own `seq` and the sink events go to.
    The sink is called on the runtime thread.
    """

    def __init__(self, name: str, sink: EventSink):
        self.name = name
        self._sink = sink
        self._seq = itertools.count(1)

    def deliver(self, event_type: EventType, payload: dict[str, Any]) -> None:
        event = Event(seq=next(self._seq), ts=to_iso(now()), type=event_type, payload=payload)
        try:
            self._sink(event.to_dict())
        except Exception:
            log.exception("client %s failed to take a %s", self.name, event_type.value)
