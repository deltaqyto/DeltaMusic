import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config as AlembicConfig

from core.event_bus import EventBus
from core.library.models import PlaylistEntryRow, PlaylistRow, SongRow
from core.library.types.scan_plan import ScanPlan
from protocol.errors import conflict, invalid_argument, not_found
from protocol.types.library_scope import LibraryScope
from protocol.types.playlist import Playlist
from protocol.types.playlist_entry import PlaylistEntry
from protocol.types.playlist_summary import PlaylistSummary
from protocol.types.song import Song

log = logging.getLogger(__name__)

ALL_TRACKS_ID = 0
ALL_TRACKS_NAME = "All Tracks"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class Library:
    """Songs, playlists and the database."""

    def __init__(self, database_path: Path, library_root: Path, bus: EventBus):
        self.root = library_root
        self._bus = bus
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{database_path}", future=True)
        _enable_wal(self._engine)
        _migrate(database_path)
        self._sessions = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)

    def close(self) -> None:
        self._engine.dispose()

    # Songs

    def snapshot_songs(self) -> list[Song]:
        with self._sessions() as session:
            return [_to_song(row) for row in session.scalars(select(SongRow)).all()]

    def get_songs(self, song_ids: Sequence[int]) -> list[Song]:
        """Only the ids that exist, in the order asked for."""
        with self._sessions() as session:
            found = {row.id: _to_song(row) for row in session.scalars(select(SongRow).where(SongRow.id.in_(song_ids)))}
        return [found[song_id] for song_id in song_ids if song_id in found]

    def require_song(self, song_id: int) -> Song:
        with self._sessions() as session:
            row = session.get(SongRow, song_id)
            if row is None:
                raise not_found(f"no song {song_id}", song_id=song_id)
            return _to_song(row)

    def list_songs(self, query: str | None, offset: int, limit: int) -> tuple[list[Song], int]:
        statement = select(SongRow)
        if query:
            pattern = f"%{query}%"
            statement = statement.where(or_(SongRow.name.ilike(pattern), SongRow.artist.ilike(pattern)))
        with self._sessions() as session:
            total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            rows = session.scalars(statement.order_by(SongRow.name, SongRow.id).offset(offset).limit(limit)).all()
            return [_to_song(row) for row in rows], total

    def update_song(self, song_id: int, fields: dict[str, Any]) -> Song:
        allowed = {"name", "artist", "metadata"}
        unknown = set(fields) - allowed
        if unknown:
            raise invalid_argument(f"update_song cannot set {sorted(unknown)}")
        with self._sessions() as session:
            row = session.get(SongRow, song_id)
            if row is None:
                raise not_found(f"no song {song_id}", song_id=song_id)
            if "name" in fields:
                row.name = str(fields["name"])
            if "artist" in fields:
                row.artist = str(fields["artist"])
            if "metadata" in fields:
                row.song_metadata = fields["metadata"] or {}
            session.commit()
            song = _to_song(row)
        self._bus.library_changed(LibraryScope.SONG, [song_id])
        return song

    def forget_song(self, song_id: int) -> None:
        with self._sessions() as session:
            row = session.get(SongRow, song_id)
            if row is None:
                raise not_found(f"no song {song_id}", song_id=song_id)
            touched = {entry.playlist_id for entry in row.entries}
            session.delete(row)
            session.commit()
            for playlist_id in touched:
                self._renumber(session, playlist_id)
            session.commit()
        self._bus.library_changed(LibraryScope.SONG, [song_id])

    def mark_played(self, song_id: int) -> None:
        with self._sessions() as session:
            row = session.get(SongRow, song_id)
            if row is None:
                return
            row.play_count += 1
            row.last_played_at = datetime.now(timezone.utc)
            session.commit()
        self._bus.library_changed(LibraryScope.STATISTICS, [song_id])

    def path_for(self, song: Song) -> Path:
        return self.root / song.location

    # Playlists

    def list_playlists(self) -> list[PlaylistSummary]:
        with self._sessions() as session:
            rows = session.scalars(select(PlaylistRow).order_by(PlaylistRow.name)).all()
            summaries = [
                PlaylistSummary(
                    id=row.id,
                    name=row.name,
                    metadata=row.playlist_metadata or {},
                    created_at=_utc(row.created_at),
                    modified_at=_utc(row.modified_at),
                    song_count=len(row.entries),
                )
                for row in rows
            ]
            total = session.scalar(select(func.count()).select_from(SongRow)) or 0
        return [self._all_tracks_summary(total), *summaries]

    def get_playlist(self, playlist_id: int) -> Playlist:
        if playlist_id == ALL_TRACKS_ID:
            return self._all_tracks()
        with self._sessions() as session:
            row = self._require_playlist(session, playlist_id)
            return _to_playlist(row)

    def create_playlist(self, name: str, song_ids: Sequence[int]) -> Playlist:
        name = (name or "").strip()
        if not name:
            raise invalid_argument("a playlist needs a name")
        if name == ALL_TRACKS_NAME:
            raise invalid_argument(f"'{ALL_TRACKS_NAME}' is reserved")
        with self._sessions() as session:
            if session.scalar(select(PlaylistRow).where(PlaylistRow.name == name)) is not None:
                raise conflict(f"a playlist named '{name}' exists")
            row = PlaylistRow(name=name)
            session.add(row)
            session.flush()
            self._append_entries(session, row, song_ids, at_index=None)
            session.commit()
            playlist = _to_playlist(row)
        self._bus.library_changed(LibraryScope.PLAYLIST, [playlist.id])
        return playlist

    def update_playlist(self, playlist_id: int, fields: dict[str, Any]) -> Playlist:
        self._reject_pseudo(playlist_id)
        allowed = {"name", "metadata"}
        unknown = set(fields) - allowed
        if unknown:
            raise invalid_argument(f"update_playlist cannot set {sorted(unknown)}")
        with self._sessions() as session:
            row = self._require_playlist(session, playlist_id)
            if "name" in fields:
                name = str(fields["name"]).strip()
                if not name:
                    raise invalid_argument("a playlist needs a name")
                if name == ALL_TRACKS_NAME:
                    raise invalid_argument(f"'{ALL_TRACKS_NAME}' is reserved")
                clash = session.scalar(select(PlaylistRow).where(PlaylistRow.name == name, PlaylistRow.id != playlist_id))
                if clash is not None:
                    raise conflict(f"a playlist named '{name}' exists")
                row.name = name
            if "metadata" in fields:
                row.playlist_metadata = fields["metadata"] or {}
            _touch(row)
            session.commit()
            playlist = _to_playlist(row)
        self._bus.library_changed(LibraryScope.PLAYLIST, [playlist_id])
        return playlist

    def delete_playlist(self, playlist_id: int) -> None:
        self._reject_pseudo(playlist_id)
        with self._sessions() as session:
            row = self._require_playlist(session, playlist_id)
            session.delete(row)
            session.commit()
        self._bus.library_changed(LibraryScope.PLAYLIST, [playlist_id])

    def playlist_add(self, playlist_id: int, song_ids: Sequence[int], at_index: int | None) -> Playlist:
        self._reject_pseudo(playlist_id)
        with self._sessions() as session:
            row = self._require_playlist(session, playlist_id)
            self._append_entries(session, row, song_ids, at_index)
            _touch(row)
            session.commit()
            playlist = _to_playlist(row)
        self._bus.library_changed(LibraryScope.PLAYLIST, [playlist_id])
        return playlist

    def playlist_remove(self, entry_ids: Sequence[int]) -> Playlist:
        if not entry_ids:
            raise invalid_argument("no entries given")
        with self._sessions() as session:
            entries = session.scalars(select(PlaylistEntryRow).where(PlaylistEntryRow.id.in_(entry_ids))).all()
            missing = set(entry_ids) - {entry.id for entry in entries}
            if missing:
                raise not_found(f"no entries {sorted(missing)}", entry_ids=sorted(missing))
            playlist_ids = {entry.playlist_id for entry in entries}
            if len(playlist_ids) > 1:
                raise invalid_argument("entries span more than one playlist")
            playlist_id = playlist_ids.pop()
            for entry in entries:
                session.delete(entry)
            session.flush()
            row = self._require_playlist(session, playlist_id)
            self._renumber(session, playlist_id)
            _touch(row)
            session.commit()
            session.refresh(row)
            playlist = _to_playlist(row)
        self._bus.library_changed(LibraryScope.PLAYLIST, [playlist_id])
        return playlist

    def playlist_move(self, entry_id: int, to_index: int) -> Playlist:
        with self._sessions() as session:
            entry = session.get(PlaylistEntryRow, entry_id)
            if entry is None:
                raise not_found(f"no entry {entry_id}", entry_id=entry_id)
            row = self._require_playlist(session, entry.playlist_id)
            ordered = list(row.entries)
            if not 0 <= to_index < len(ordered):
                raise invalid_argument(f"index {to_index} is outside the playlist")
            ordered.remove(entry)
            ordered.insert(to_index, entry)
            for position, moved in enumerate(ordered):
                moved.position = position
            _touch(row)
            session.commit()
            session.refresh(row)
            playlist = _to_playlist(row)
        self._bus.library_changed(LibraryScope.PLAYLIST, [entry.playlist_id])
        return playlist

    def song_ids_in(self, playlist_id: int) -> list[int]:
        """The source list for playback, snapshot at the moment it is asked for."""
        if playlist_id == ALL_TRACKS_ID:
            with self._sessions() as session:
                return list(session.scalars(select(SongRow.id).order_by(SongRow.name, SongRow.id)))
        with self._sessions() as session:
            row = self._require_playlist(session, playlist_id)
            return [entry.song_id for entry in row.entries]

    # Scanning

    def apply_scan_plan(self, plan: ScanPlan) -> list[int]:
        if plan.is_empty():
            return []
        touched: list[int] = []
        with self._sessions() as session:
            for patch in plan.patches:
                row = session.get(SongRow, patch.song_id)
                if row is None:
                    continue
                row.found_on_disk = patch.found_on_disk
                if patch.location is not None:
                    row.location = patch.location
                if patch.file_size is not None:
                    row.file_size = patch.file_size
                if patch.duration is not None:
                    row.duration = patch.duration
                touched.append(row.id)
            for new in plan.insertions:
                row = SongRow(
                    name=new.name,
                    artist=new.artist,
                    duration=new.duration,
                    file_size=new.file_size,
                    location=new.location,
                    found_on_disk=True,
                )
                session.add(row)
                session.flush()
                touched.append(row.id)
            session.commit()
        self._bus.library_changed(LibraryScope.SONG, touched)
        return touched

    # Internals

    def _all_tracks(self) -> Playlist:
        with self._sessions() as session:
            song_ids = list(session.scalars(select(SongRow.id).order_by(SongRow.name, SongRow.id)))
        return Playlist(
            id=ALL_TRACKS_ID,
            name=ALL_TRACKS_NAME,
            created_at=_EPOCH,
            modified_at=_EPOCH,
            # Negated so a synthetic entry id can never match a real playlist_entry primary key, which is always positive.
            entries=[PlaylistEntry(entry_id=-song_id, song_id=song_id) for song_id in song_ids],
        )

    def _all_tracks_summary(self, song_count: int) -> PlaylistSummary:
        return PlaylistSummary(
            id=ALL_TRACKS_ID,
            name=ALL_TRACKS_NAME,
            created_at=_EPOCH,
            modified_at=_EPOCH,
            song_count=song_count,
        )

    def _reject_pseudo(self, playlist_id: int) -> None:
        if playlist_id == ALL_TRACKS_ID:
            raise invalid_argument(f"'{ALL_TRACKS_NAME}' is not writable")

    def _require_playlist(self, session: Session, playlist_id: int) -> PlaylistRow:
        row = session.get(PlaylistRow, playlist_id)
        if row is None:
            raise not_found(f"no playlist {playlist_id}", playlist_id=playlist_id)
        return row

    def _append_entries(self, session: Session, row: PlaylistRow, song_ids: Sequence[int], at_index: int | None) -> None:
        known = set(session.scalars(select(SongRow.id).where(SongRow.id.in_(song_ids))))
        unknown = [song_id for song_id in song_ids if song_id not in known]
        if unknown:
            raise not_found(f"no songs {unknown}", song_ids=unknown)
        ordered = list(row.entries)
        index = len(ordered) if at_index is None else at_index
        if not 0 <= index <= len(ordered):
            raise invalid_argument(f"index {at_index} is outside the playlist")
        fresh = [PlaylistEntryRow(playlist_id=row.id, song_id=song_id, position=0) for song_id in song_ids]
        session.add_all(fresh)
        ordered[index:index] = fresh
        for position, entry in enumerate(ordered):
            entry.position = position
        session.flush()
        session.refresh(row)

    def _renumber(self, session: Session, playlist_id: int) -> None:
        entries = session.scalars(
            select(PlaylistEntryRow).where(PlaylistEntryRow.playlist_id == playlist_id).order_by(PlaylistEntryRow.position)
        ).all()
        for position, entry in enumerate(entries):
            entry.position = position
        session.flush()


MIGRATIONS = Path(__file__).resolve().parent / "migrations"
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _migrate(database_path: Path) -> None:
    """Brings the database up to head on startup, so a deployed copy never needs a manual upgrade."""
    if not (MIGRATIONS / "env.py").exists():
        raise RuntimeError(f"no alembic environment at {MIGRATIONS}")
    config = AlembicConfig(str(ALEMBIC_INI)) if ALEMBIC_INI.exists() else AlembicConfig()
    config.attributes["configure_logging"] = False
    # Values go through configparser interpolation, so a literal percent has to be doubled.
    config.set_main_option("script_location", str(MIGRATIONS).replace("%", "%%"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}".replace("%", "%%"))
    command.upgrade(config, "head")


def _enable_wal(engine: Any) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(connection: Any, _record: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _touch(row: PlaylistRow) -> None:
    row.modified_at = datetime.now(timezone.utc)


def _to_song(row: SongRow) -> Song:
    return Song(
        id=row.id,
        name=row.name,
        artist=row.artist,
        duration=row.duration,
        file_size=row.file_size,
        location=row.location,
        found_on_disk=row.found_on_disk,
        metadata=row.song_metadata or {},
        added_at=_utc(row.added_at),
        last_played_at=_utc(row.last_played_at),
        play_count=row.play_count,
    )


def _to_playlist(row: PlaylistRow) -> Playlist:
    return Playlist(
        id=row.id,
        name=row.name,
        metadata=row.playlist_metadata or {},
        created_at=_utc(row.created_at),
        modified_at=_utc(row.modified_at),
        entries=[PlaylistEntry(entry_id=entry.id, song_id=entry.song_id) for entry in row.entries],
    )
