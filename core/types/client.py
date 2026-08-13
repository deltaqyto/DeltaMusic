import itertools
import logging
from collections.abc import Callable
from typing import Any

from protocol.timestamps import now, to_iso
from protocol.types.event import Event
from protocol.types.event_type import EventType, LOCAL_ONLY_EVENTS
from protocol.types.origin import Origin

log = logging.getLogger(__name__)

EventSink = Callable[[dict[str, Any]], None]


class Client:
    """One attached client. Owns its own `seq` and the sink events go to.
    The sink is called on whichever thread raised the event, which is the runtime for a session or library event and a listener or a peer worker for the rest.
    """

    def __init__(self, name: str, sink: EventSink, origin: Origin = Origin.LOCAL):
        self.name = name
        self.origin = origin
        self._sink = sink
        self._seq = itertools.count(1)

    def deliver(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self.origin is Origin.NETWORK and event_type in LOCAL_ONLY_EVENTS:
            return
        event = Event(seq=next(self._seq), ts=to_iso(now()), type=event_type, payload=payload)
        try:
            self._sink(event.to_dict())
        except Exception:
            log.exception("client %s failed to take a %s", self.name, event_type.value)
