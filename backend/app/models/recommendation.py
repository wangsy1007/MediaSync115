"""AI 推荐结果缓存模型（猜你想看）。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timezone_utils import beijing_now


class RecommendationCache(Base):
    """最近一次「猜你想看」推荐结果缓存，单行设计（id=1）。"""

    __tablename__ = "recommendation_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    items_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, onupdate=beijing_now
    )
