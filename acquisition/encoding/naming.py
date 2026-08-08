"""Turning metadata into a safe, non-colliding output path."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from ..types import TrackMetadata
from .formats import resolve

# Illegal on Windows, plus path separators and control characters everywhere.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Reserved DOS device names; also reserved with any extension (CON.wav).
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_COMPONENT = 120  # leaves room for the separator and the extension

# Rare enough in real metadata that the library scanner can split on it without guessing.
SEPARATOR = " ~~ "
DEFAULT_TEMPLATE = f"{{title}}{SEPARATOR}{{artist}}"


def sanitize_component(value: str, *, fallback: str = "untitled") -> str:
    """Make `value` safe to use as one path component. Never returns an empty string, and never anything containing a path separator."""
    cleaned = _ILLEGAL.sub("_", str(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    if len(cleaned) > _MAX_COMPONENT:
        cleaned = cleaned[:_MAX_COMPONENT].rstrip(". ")
    if not cleaned or set(cleaned) <= {"."}:
        cleaned = fallback
    if cleaned.upper().split(".")[0] in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def render_filename(
    metadata: TrackMetadata,
    template: str = DEFAULT_TEMPLATE,
) -> str:
    """Render `template` from metadata, sanitising each field before substitution so no value can inject a separator or a traversal."""
    values = {
        "artist": sanitize_component(metadata.artist, fallback="unknown artist"),
        "title": sanitize_component(metadata.title, fallback="untitled"),
        "album": sanitize_component(metadata.album or "", fallback="unknown album"),
        "album_artist": sanitize_component(
            metadata.album_artist or metadata.artist, fallback="unknown artist"
        ),
        "track_number": f"{metadata.track_number:02d}" if metadata.track_number else "",
        "year": str(metadata.year) if metadata.year else "",
        "genre": sanitize_component(metadata.genre or "", fallback="unknown genre"),
    }
    try:
        rendered = template.format(**values)
    except KeyError as exc:
        raise ValueError(
            f"unknown placeholder {exc.args[0]!r} in filename template; "
            f"available: {', '.join(sorted(values))}"
        ) from exc
    except (IndexError, ValueError) as exc:
        raise ValueError(f"malformed filename template {template!r}: {exc}") from exc
    return sanitize_component(rendered)


def resolve_destination(
    destination: os.PathLike | str,
    metadata: TrackMetadata,
    extension: str,
    *,
    template: str = DEFAULT_TEMPLATE,
    overwrite: bool = False,
    create_dirs: bool = True,
) -> Path:
    """Work out the final file path. `destination` may be a directory, in which case the name comes from `template`, or a full file path."""
    extension = "." + extension.lstrip(".").lower()
    dest = Path(destination).expanduser()

    looks_like_dir = dest.is_dir() or str(destination).endswith(("/", "\\")) or not dest.suffix
    if looks_like_dir:
        directory = dest
        stem = render_filename(metadata, template)
    else:
        directory = dest.parent
        # The format, not the caller's suffix, decides the extension, so the bytes on disk and the name can never disagree.
        stem = sanitize_component(dest.stem)

    if create_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    elif not directory.is_dir():
        raise NotADirectoryError(f"destination directory does not exist: {directory}")

    candidate = directory / f"{stem}{extension}"
    if not overwrite and candidate.exists():
        # One file per track: a second copy under another name is a duplicate to clean up later, not a better outcome than no copy.
        raise FileExistsError(f"{candidate.name} already exists")
    return candidate


def extension_for(container: str, subtype: Optional[str] = None) -> str:
    """The file extension for a container."""
    return resolve(container, subtype).extension
