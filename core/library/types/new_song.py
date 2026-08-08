from dataclasses import dataclass


@dataclass(frozen=True)
class NewSong:
    name: str
    artist: str
    duration: float
    file_size: int
    location: str
