from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


class MediaType(str, enum.Enum):
    MOVIE = "movie"
    TV = "tv"
    COLLECTION = "collection"


class MediaStatus(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStatus(str, enum.Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    douban_id: Mapped[str | None] = mapped_column(
        String(50), unique=True, nullable=True
    )
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    poster_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rating: Mapped[float | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    downloads: Mapped[list["DownloadRecord"]] = relationship(
        "DownloadRecord", back_populates="subscription"
    )


class DownloadRecord(Base):
    __tablename__ = "download_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subscriptions.id"), nullable=False
    )
    resource_name: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_url: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[MediaStatus] = mapped_column(
        SQLEnum(MediaStatus), default=MediaStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    subscription: Mapped["Subscription"] = relationship(
        "Subscription", back_populates="downloads"
    )


class SubscriptionExecutionLog(Base):
    __tablename__ = "subscription_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        SQLEnum(ExecutionStatus), nullable=False
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    checked_count: Mapped[int] = mapped_column(Integer, default=0)
    new_resource_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubscriptionStepLog(Base):
    __tablename__ = "subscription_step_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    subscription_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    subscription_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    step: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, default="info"
    )
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    request_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class TgMessageIndex(Base):
    __tablename__ = "tg_message_index"
    __table_args__ = (
        UniqueConstraint(
            "channel_username",
            "message_id",
            "share_link",
            name="uq_tg_message_index_unique",
        ),
        Index("ix_tg_message_index_channel_date", "channel_username", "message_date"),
        Index("ix_tg_message_index_search_text", "search_text"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_username: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    share_link: Mapped[str] = mapped_column(Text, nullable=False)
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type_hint: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TgSyncState(Base):
    __tablename__ = "tg_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_username: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True, index=True
    )
    last_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    backfill_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TgSyncJob(Base):
    __tablename__ = "tg_sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(40), nullable=False, unique=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    current_channel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_channels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
