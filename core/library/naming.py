from pathlib import Path

UNKNOWN_ARTIST = "unknown"
SEPARATOR = " ~~ "


def parse_filename(path: Path) -> tuple[str, str]:
    stem = path.stem.strip()
    name, separator, artist = stem.rpartition(SEPARATOR)
    if not separator:
        return stem or path.name, UNKNOWN_ARTIST
    name, artist = name.strip(), artist.strip()
    if not name or not artist:
        return stem, UNKNOWN_ARTIST
    return name, artist
