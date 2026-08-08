from enum import Enum


class EventType(str, Enum):
    HEARTBEAT = "Heartbeat"
    TRACK_CHANGED = "TrackChanged"
    PLAYBACK_CHANGED = "PlaybackChanged"
    QUEUE_CHANGED = "QueueChanged"
    LIBRARY_CHANGED = "LibraryChanged"
    SCAN_PROGRESS = "ScanProgress"
    TRACK_FAILED = "TrackFailed"
