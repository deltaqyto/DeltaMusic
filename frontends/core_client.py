import itertools
from typing import Any

from core.service import CoreService
from protocol.types.error import Error
from protocol.types.event import Event
from protocol.types.request import Request
from protocol.types.response import Response
from protocol.version import PROTOCOL_VERSION


class ClientError(Exception):
    """A command came back `ok: false`."""

    def __init__(self, error: Error):
        super().__init__(f"{error.code.value}: {error.message}")
        self.error = error


class CoreClient:
    """What a frontend is handed. Handles protocol details

    In-process this calls `dispatch` straight across the thread boundary.
    A websocket transport would put the same envelopes on a socket.
    """

    def __init__(self, service: CoreService, name: str):
        self._service = service
        self._name = name
        self._ids = itertools.count(1)
        self._attached = None

    @property
    def name(self) -> str:
        return self._name

    def attach(self, on_event: Any) -> None:
        """`on_event` takes an Event and is called on the runtime thread."""
        self._attached = self._service.attach(self._name, lambda raw: on_event(Event.from_dict(raw)))

    def detach(self) -> None:
        if self._attached is not None:
            self._service.detach(self._attached)
            self._attached = None

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        request = Request(id=f"{self._name}-{next(self._ids)}", method=method, params=params, v=PROTOCOL_VERSION)
        response = Response.from_dict(self._service.dispatch(request.to_dict()))
        if not response.ok:
            raise ClientError(response.error)
        return response.result or {}
