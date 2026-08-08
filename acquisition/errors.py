"""Exception hierarchy for acquisition.
"""


class CaptureError(Exception):
    pass


class DeviceNotFoundError(CaptureError):
    pass


class StreamNotRunningError(CaptureError):
    pass


class AlreadyRecordingError(CaptureError):
    pass


class NotRecordingError(CaptureError):
    pass


class RecordingLimitError(CaptureError):
    """The recording exceeded the configured in-memory duration cap."""


class WriteError(CaptureError):
    pass
