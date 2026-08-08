import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from core.library.naming import parse_filename
from core.library.probe import measure_duration
from core.library.types.new_song import NewSong
from core.library.types.scan_plan import ScanPlan
from core.library.types.scanned_file import ScannedFile
from core.library.types.song_patch import SongPatch
from protocol.types.scan_phase import ScanPhase
from protocol.types.song import Song

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, ScanPhase], None]


class Scanner:
    """Walks the library folder and decides what the songs table should say.
    Emits a plan for the main thread to implement
    The asynch approach keeps startup times low.
    """

    def __init__(self, library_root: Path, extensions: Iterable[str], on_progress: ProgressCallback | None = None):
        self._root = library_root
        self._extensions = {extension.lower() for extension in extensions}
        self._on_progress = on_progress or (lambda scanned, total, phase: None)

    def plan(self, songs: list[Song]) -> ScanPlan:
        files = self._walk()
        plan = ScanPlan()

        unclaimed = dict(files)
        missing: list[Song] = []

        # Every song, plus every file, is one unit of work. A file matched to a song is counted with it.
        total = len(files) + len(songs)
        done = 0

        for song in songs:
            done += 1
            found = unclaimed.pop(song.location, None)
            if found is None:
                missing.append(song)
                continue
            done += 1
            if found.file_size == song.file_size:
                if not song.found_on_disk:
                    plan.patches.append(SongPatch(song_id=song.id, found_on_disk=True))
            else:
                plan.patches.append(
                    SongPatch(
                        song_id=song.id,
                        found_on_disk=True,
                        file_size=found.file_size,
                        duration=measure_duration(found.path),
                    )
                )
            self._on_progress(done, total, ScanPhase.WALKING)

        durations: dict[str, float] = {}
        for song in missing:
            rebound = self._recover(song, unclaimed, durations)
            if rebound is None:
                if song.found_on_disk:
                    plan.patches.append(SongPatch(song_id=song.id, found_on_disk=False))
            else:
                done += 1
                unclaimed.pop(rebound.location, None)
                plan.patches.append(
                    SongPatch(
                        song_id=song.id,
                        found_on_disk=True,
                        location=rebound.location,
                        file_size=rebound.file_size,
                        duration=durations.get(rebound.location, song.duration),
                    )
                )
            self._on_progress(done, total, ScanPhase.RECONCILING)

        for found in unclaimed.values():
            name, artist = parse_filename(found.path)
            plan.insertions.append(
                NewSong(
                    name=name,
                    artist=artist,
                    duration=durations.get(found.location) or measure_duration(found.path),
                    file_size=found.file_size,
                    location=found.location,
                )
            )
            done += 1
            self._on_progress(done, total, ScanPhase.INSERTING)

        self._on_progress(total, total, ScanPhase.DONE)
        return plan

    def _recover(self, song: Song, unclaimed: dict[str, ScannedFile], durations: dict[str, float]) -> ScannedFile | None:
        """Same name and size, else same size and duration. ANY ambiguity means no match."""
        wanted_name = Path(song.location).name
        by_name = [f for f in unclaimed.values() if f.path.name == wanted_name and f.file_size == song.file_size]
        if len(by_name) == 1:
            return by_name[0]

        by_size = [f for f in unclaimed.values() if f.file_size == song.file_size]
        matches = []
        for candidate in by_size:
            if candidate.location not in durations:
                durations[candidate.location] = measure_duration(candidate.path)
            if durations[candidate.location] == song.duration:
                matches.append(candidate)
        if len(matches) == 1:
            return matches[0]
        return None

    def _walk(self) -> dict[str, ScannedFile]:
        found: dict[str, ScannedFile] = {}
        if not self._root.exists():
            log.warning("library folder %s does not exist", self._root)
            return found
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self._extensions:
                continue
            location = path.relative_to(self._root).as_posix()
            found[location] = ScannedFile(location=location, path=path, file_size=path.stat().st_size)
        return found
