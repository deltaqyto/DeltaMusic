"""Capture tracks off an audio source, driven by a media session.

A portable core plus one backend per platform.
"""

from .config import DEFAULT_CONFIG_PATH, AcquisitionConfig
from .controller import RecordingController, Stats
from .errors import (
    AlreadyRecordingError,
    CaptureError,
    DeviceNotFoundError,
    NotRecordingError,
    RecordingLimitError,
    StreamNotRunningError,
    WriteError,
)
from .interfaces import AudioSource, Backend, SessionSource
from .registry import available_backends, backend_names, select
from .runner import run
from .saver import SaveJob, SaveWorker
from .types import CaptureResult, SourceInfo, TrackInfo, TrackMetadata

__all__ = [
    "run",
    "AcquisitionConfig",
    "DEFAULT_CONFIG_PATH",
    "AudioSource",
    "SessionSource",
    "Backend",
    "select",
    "available_backends",
    "backend_names",
    "RecordingController",
    "Stats",
    "SaveWorker",
    "SaveJob",
    "TrackInfo",
    "TrackMetadata",
    "CaptureResult",
    "SourceInfo",
    "CaptureError",
    "DeviceNotFoundError",
    "StreamNotRunningError",
    "AlreadyRecordingError",
    "NotRecordingError",
    "RecordingLimitError",
    "WriteError",
]

__version__ = "2.0.0"
