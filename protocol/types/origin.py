from enum import Enum


class Origin(str, Enum):
    """Where an attachment came from, set by the transport that accepted it."""

    LOCAL = "local"
    NETWORK = "network"
