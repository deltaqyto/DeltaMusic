from enum import Enum


class LibraryScope(str, Enum):
    SONG = "song"
    PLAYLIST = "playlist"
    STATISTICS = "statistics"
