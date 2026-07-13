from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timezone_utils import beijing_now


class StrmFileIndex(Base):
    """115 视频文件到本地 STRM 文件的持久化索引。"""

    __tablename__ = "strm_file_index"
    __table_args__ = (
        UniqueConstraint("output_cid", "fid", name="uq_strm_file_index_output_fid"),
        Index("ix_strm_file_index_output_path", "output_cid", "relative_path"),
        Index("ix_strm_file_index_output_parent", "output_cid", "parent_cid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    output_cid: Mapped[str] = mapped_column(String(100), nullable=False)
    fid: Mapped[str] = mapped_column(String(100), nullable=False)
    pick_code: Mapped[str] = mapped_column(String(200), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    parent_cid: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    sha1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )


class StrmFolderIndex(Base):
    """目录的确定性直接子项快照。"""

    __tablename__ = "strm_folder_index"
    __table_args__ = (
        UniqueConstraint("output_cid", "fid", name="uq_strm_folder_index_output_fid"),
        Index("ix_strm_folder_index_output_path", "output_cid", "relative_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    output_cid: Mapped[str] = mapped_column(String(100), nullable=False)
    fid: Mapped[str] = mapped_column(String(100), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parent_cid: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )


class StrmSyncState(Base):
    """每个 115 输出目录的增量同步状态。"""

    __tablename__ = "strm_sync_state"

    output_cid: Mapped[str] = mapped_column(String(100), primary_key=True)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    root_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    last_status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    folder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )
