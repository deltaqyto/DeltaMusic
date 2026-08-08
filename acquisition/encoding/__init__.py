"""Portable encoding: container choice, filenames, and the actual write.

The filename policy in naming applies the strictest platform's rules
everywhere, so a file written on one machine always loads on another.
"""

from .formats import Encoding, containers, is_lossy, resolve, validate
from .naming import DEFAULT_TEMPLATE, SEPARATOR, extension_for, render_filename, resolve_destination, sanitize_component
from .save import RecordingResult, save_capture
from .writer import WriteReport, write_audio

__all__ = [
    "Encoding",
    "containers",
    "is_lossy",
    "resolve",
    "validate",
    "extension_for",
    "render_filename",
    "resolve_destination",
    "sanitize_component",
    "DEFAULT_TEMPLATE",
    "SEPARATOR",
    "RecordingResult",
    "save_capture",
    "WriteReport",
    "write_audio",
]
