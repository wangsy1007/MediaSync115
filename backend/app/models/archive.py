import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SQLEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ArchiveStatus(str, enum.Enum):
    """归档任务状态"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ArchiveTask(Base):
    """归档任务记录"""

    __tablename__ = "archive_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tmdb_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tmdb_year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    genre_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[ArchiveStatus] = mapped_column(
        SQLEnum(ArchiveStatus), default=ArchiveStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
