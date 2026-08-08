from datetime import datetime, timezone


def to_iso(moment: datetime | None) -> str | None:
    """UTC, ISO 8601, millisecond precision, Z-suffixed."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    millis = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    return millis + "Z"


def from_iso(text: str | None) -> datetime | None:
    if text is None:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def now() -> datetime:
    return datetime.now(timezone.utc)
