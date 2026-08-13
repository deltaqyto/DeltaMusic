from enum import Enum


class PairingState(str, Enum):
    """Where one pairing session stands."""

    AWAITING_CODE = "awaiting_code"
    PAIRED = "paired"
    REFUSED = "refused"
    CANCELLED = "cancelled"
