from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class NewSong:
    name: str
    artist: str
    duration: float
    file_size: int
    location: str
    uuid: str = field(default_factory=lambda: str(uuid4()))
    """Minted here unless the scanner read one off the file."""
