import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from uuid import uuid4

from core.library.naming import parse_filename
from core.library.probe import measure_duration
from core.library.tags import read_uuid, write_uuid
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
        row_uuids = {song.uuid for song in songs}

        # Every song, plus every file, is one unit of work. A file matched to a song is counted with it.
        total = len(files) + len(songs)
        done = 0

        for song in songs:
            done += 1
            found = unclaimed.pop(song.location, None) if song.location else None
            if found is None:
                missing.append(song)
                continue
            done += 1
            patch = self._settle(song, found)
            if patch is not None:
                plan.patches.append(patch)
            self._on_progress(done, total, ScanPhase.WALKING)

        lost = {song.uuid: song for song in missing}
        for location in list(unclaimed):
            found = unclaimed[location]
            song = lost.pop(found.uuid, None) if found.uuid else None
            if song is None:
                continue
            del unclaimed[location]
            done += 1
            # A stamped file that moved may also have been re-encoded, so its size and duration are taken as they are.
            plan.patches.append(
                SongPatch(
                    song_id=song.id,
                    found_on_disk=True,
                    location=location,
                    file_size=found.file_size,
                    duration=measure_duration(found.path),
                )
            )
            self._on_progress(done, total, ScanPhase.RECONCILING)

        durations: dict[str, float] = {}
        for song in missing:
            if song.uuid not in lost:
                continue
            rebound = self._recover(song, unclaimed, durations, row_uuids)
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
                        file_size=self._stamp(rebound, song.uuid) or rebound.file_size,
                        duration=durations.get(rebound.location, song.duration),
                    )
                )
            self._on_progress(done, total, ScanPhase.RECONCILING)

        for found in unclaimed.values():
            name, artist = parse_filename(found.path)
            uuid, file_size = found.uuid, found.file_size
            if uuid is None or uuid in row_uuids:
                # No uuid, or one that already names another song, so this file is a copy and gets its own.
                uuid = str(uuid4())
                file_size = self._stamp(found, uuid) or file_size
            row_uuids.add(uuid)
            plan.insertions.append(
                NewSong(
                    name=name,
                    artist=artist,
                    duration=durations.get(found.location) or measure_duration(found.path),
                    file_size=file_size,
                    location=found.location,
                    uuid=uuid,
                )
            )
            done += 1
            self._on_progress(done, total, ScanPhase.INSERTING)

        self._on_progress(total, total, ScanPhase.DONE)
        return plan

    def _settle(self, song: Song, found: ScannedFile) -> SongPatch | None:
        """A song whose file is where the database says it is."""
        file_size, duration = found.file_size, None
        if file_size != song.file_size:
            duration = measure_duration(found.path)
        if found.uuid != song.uuid:
            # The database is authoritative, so the file is stamped with what the row says, and it grows by the write.
            file_size = self._stamp(found, song.uuid) or file_size
        if file_size == song.file_size and duration is None and song.found_on_disk:
            return None
        return SongPatch(song_id=song.id, found_on_disk=True, file_size=file_size, duration=duration)

    def _stamp(self, found: ScannedFile, uuid: str) -> int | None:
        """Writes the uuid into the file and answers the size it left behind. None when the container takes no tag."""
        if not write_uuid(found.path, uuid):
            return None
        try:
            return found.path.stat().st_size
        except OSError as failure:
            log.warning("could not measure %s after stamping it: %s", found.path, failure)
            return None

    def _recover(
        self, song: Song, unclaimed: dict[str, ScannedFile], durations: dict[str, float], row_uuids: set[str]
    ) -> ScannedFile | None:
        """Same name and size, else same size and duration. ANY ambiguity means no match."""
        if song.location is None:
            # No file was ever placed for this song, so there is nothing to recover it from.
            return None
        # A file naming a song of its own is not a candidate for this one, whatever its name and size say.
        candidates = [f for f in unclaimed.values() if f.uuid not in row_uuids]
        wanted_name = Path(song.location).name
        by_name = [f for f in candidates if f.path.name == wanted_name and f.file_size == song.file_size]
        if len(by_name) == 1:
            return by_name[0]

        by_size = [f for f in candidates if f.file_size == song.file_size]
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
            found[location] = ScannedFile(
                location=location, path=path, file_size=path.stat().st_size, uuid=read_uuid(path)
            )
        return found
