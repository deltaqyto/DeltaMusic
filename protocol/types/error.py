from dataclasses import dataclass, field
from typing import Any

from protocol.types.error_code import ErrorCode


@dataclass(frozen=True)
class Error:
    code: ErrorCode
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "detail": self.detail}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Error":
        return Error(
            code=ErrorCode(raw["code"]),
            message=raw.get("message", ""),
            detail=raw.get("detail") or {},
        )
