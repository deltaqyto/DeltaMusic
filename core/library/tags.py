import logging
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import TXXX

log = logging.getLogger(__name__)

TAG = "DELTAMUSIC_UUID"

VORBIS_SUFFIXES = {".opus", ".ogg", ".flac"}
ID3_SUFFIXES = {".mp3"}

# The ID3 text encoding for UTF-8.
UTF8 = 3


def read_uuid(path: Path) -> str | None:
    """The uuid stamped into the file, or None when it carries none and when the container holds none."""
    suffix = path.suffix.lower()
    if suffix not in VORBIS_SUFFIXES and suffix not in ID3_SUFFIXES:
        return None
    try:
        probed = MutagenFile(str(path))
        if probed is None or probed.tags is None:
            return None
        if suffix in ID3_SUFFIXES:
            frames = probed.tags.getall(f"TXXX:{TAG}")
            return str(frames[0].text[0]) if frames and frames[0].text else None
        values = probed.tags.get(TAG)
        return str(values[0]) if values else None
    except Exception as failure:
        log.warning("could not read the uuid in %s: %s", path, failure)
        return None


def write_uuid(path: Path, uuid: str) -> bool:
    """Stamps the uuid into the file. False when the container does not take one, or when the write failed."""
    suffix = path.suffix.lower()
    if suffix not in VORBIS_SUFFIXES and suffix not in ID3_SUFFIXES:
        return False
    try:
        audio = MutagenFile(str(path))
        if audio is None:
            return False
        if audio.tags is None:
            audio.add_tags()
        if suffix in ID3_SUFFIXES:
            audio.tags.delall(f"TXXX:{TAG}")
            audio.tags.add(TXXX(encoding=UTF8, desc=TAG, text=[uuid]))
        else:
            audio[TAG] = [uuid]
        audio.save()
        return True
    except Exception as failure:
        log.warning("could not stamp %s: %s", path, failure)
        return False
