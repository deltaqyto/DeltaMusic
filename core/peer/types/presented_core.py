from dataclasses import dataclass


@dataclass(frozen=True)
class PresentedCore:
    """What a presented certificate says about the core behind it. Nothing here is trusted."""

    id: str
    name: str
    fingerprint: str
