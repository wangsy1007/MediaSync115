from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmbyMediaIndex(Base):
    __tablename__ = "emby_media_index"
    __table_args__ = (
        UniqueConstraint("media_type", "tmdb_id", name="uq_emby_media_index_media_tmdb"),
        Index("ix_emby_media_index_media_type_tmdb", "media_type", "tmdb_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_type: Mapped[str] = mapped_column(String(10), nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    emby_item_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmbyTvEpisodeIndex(Base):
    __tablename__ = "emby_tv_episode_index"
    __table_args__ = (
        UniqueConstraint("tmdb_id", "season_number", "episode_number", name="uq_emby_tv_episode_index_episode"),
        Index("ix_emby_tv_episode_index_tmdb", "tmdb_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class EmbySyncState(Base):
    __tablename__ = "emby_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    last_trigger: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    movie_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tv_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    episode_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
