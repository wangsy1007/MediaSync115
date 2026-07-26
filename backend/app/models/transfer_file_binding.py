from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timezone_utils import beijing_now


class TransferFileBinding(Base):
    """转存文件绑定：115 视频 file_fid 与 TMDB 影视一一对应，供归档优先识别。"""

    __tablename__ = "transfer_file_bindings"
    __table_args__ = (
        UniqueConstraint("file_fid", name="uq_transfer_file_bindings_file_fid"),
        Index("ix_transfer_file_bindings_tmdb_media", "tmdb_id", "media_type"),
        Index("ix_transfer_file_bindings_parent_cid", "parent_cid"),
        Index("ix_transfer_file_bindings_created_at", "created_at"),
        Index("ix_transfer_file_bindings_download_record_id", "download_record_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_fid: Mapped[str] = mapped_column(String(100), nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="movie")
    display_title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    parent_cid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    download_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=beijing_now)
