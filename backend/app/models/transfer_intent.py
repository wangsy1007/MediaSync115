from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timezone_utils import beijing_now


class TransferIntent(Base):
    """转存意图：记录用户转存时对应的影视中文名与目录，供归档命名关联。"""

    __tablename__ = "transfer_intents"
    __table_args__ = (
        Index("ix_transfer_intents_tmdb_media", "tmdb_id", "media_type"),
        Index("ix_transfer_intents_target_folder_id", "target_folder_id"),
        Index("ix_transfer_intents_target_parent_id", "target_parent_id"),
        Index("ix_transfer_intents_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    douban_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="movie")
    display_title: Mapped[str] = mapped_column(String(500), nullable=False)
    target_folder_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_parent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=beijing_now)
