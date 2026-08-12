from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class SongRow(Base):
    __tablename__ = "song"
    __table_args__ = (
        Index("ix_song_uuid", "uuid", unique=True),
        Index("ix_song_location", "location", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String, nullable=False, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    found_on_disk: Mapped[bool] = mapped_column(default=True, nullable=False)
    song_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    entries: Mapped[list["PlaylistEntryRow"]] = relationship(back_populates="song", cascade="all, delete-orphan")


class PlaylistRow(Base):
    __tablename__ = "playlist"
    __table_args__ = (Index("ix_playlist_uuid", "uuid", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String, nullable=False, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    playlist_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    entries: Mapped[list["PlaylistEntryRow"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistEntryRow.position",
    )


class PlaylistEntryRow(Base):
    __tablename__ = "playlist_entry"
    # Positions are renumbered in place, so they are transiently duplicated.
    __table_args__ = (Index("ix_playlist_entry_playlist_position", "playlist_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlist.id", ondelete="CASCADE"), nullable=False)
    song_id: Mapped[int] = mapped_column(ForeignKey("song.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    playlist: Mapped[PlaylistRow] = relationship(back_populates="entries")
    song: Mapped[SongRow] = relationship(back_populates="entries")
