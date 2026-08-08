from dataclasses import dataclass, field

from core.library.types.new_song import NewSong
from core.library.types.song_patch import SongPatch


@dataclass
class ScanPlan:
    """Whatever the scan decided."""

    patches: list[SongPatch] = field(default_factory=list)
    insertions: list[NewSong] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.patches and not self.insertions
