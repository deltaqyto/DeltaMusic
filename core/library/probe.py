import logging
from pathlib import Path

from mutagen import File as MutagenFile

log = logging.getLogger(__name__)


def measure_duration(path: Path) -> float:
    """Seconds from the container header. Zero when the file will not parse."""
    try:
        probed = MutagenFile(str(path))
    except Exception as failure:
        log.warning("could not probe %s: %s", path, failure)
        return 0.0
    if probed is None or probed.info is None:
        return 0.0
    return float(getattr(probed.info, "length", 0.0) or 0.0)
