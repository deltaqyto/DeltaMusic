from dataclasses import dataclass
from typing import Any

from protocol.types.error import Error
from protocol.version import PROTOCOL_VERSION


@dataclass(frozen=True)
class Response:
    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: Error | None = None
    v: int = PROTOCOL_VERSION

    @staticmethod
    def succeeded(request_id: str, result: dict[str, Any] | None = None) -> "Response":
        return Response(id=request_id, ok=True, result=result or {})

    @staticmethod
    def failed(request_id: str, error: Error) -> "Response":
        return Response(id=request_id, ok=False, error=error)

    def to_dict(self) -> dict[str, Any]:
        envelope: dict[str, Any] = {"v": self.v, "id": self.id, "ok": self.ok}
        if self.ok:
            envelope["result"] = self.result or {}
        else:
            envelope["error"] = self.error.to_dict()
        return envelope

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Response":
        return Response(
            v=raw.get("v", PROTOCOL_VERSION),
            id=raw["id"],
            ok=raw["ok"],
            result=raw.get("result"),
            error=Error.from_dict(raw["error"]) if not raw["ok"] else None,
        )
