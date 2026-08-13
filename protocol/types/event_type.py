from enum import Enum


class EventType(str, Enum):
    HEARTBEAT = "Heartbeat"
    TRACK_CHANGED = "TrackChanged"
    PLAYBACK_CHANGED = "PlaybackChanged"
    QUEUE_CHANGED = "QueueChanged"
    LIBRARY_CHANGED = "LibraryChanged"
    SCAN_PROGRESS = "ScanProgress"
    TRACK_FAILED = "TrackFailed"

    PAIRING_WINDOW_CHANGED = "PairingWindowChanged"
    PAIRING_CANDIDATES_CHANGED = "PairingCandidatesChanged"
    PAIRING_CODE_READY = "PairingCodeReady"
    PAIRING_STATE_CHANGED = "PairingStateChanged"
    PEER_CHANGED = "PeerChanged"
    PEER_JOB_PROGRESS = "PeerJobProgress"
    PEER_JOB_FINISHED = "PeerJobFinished"
    PEER_JOB_FAILED = "PeerJobFailed"


# Pairing emits a code for a frontend to display, so the family reaches local attachments alone.
LOCAL_ONLY_EVENTS = frozenset(
    {
        EventType.PAIRING_WINDOW_CHANGED,
        EventType.PAIRING_CANDIDATES_CHANGED,
        EventType.PAIRING_CODE_READY,
        EventType.PAIRING_STATE_CHANGED,
    }
)
