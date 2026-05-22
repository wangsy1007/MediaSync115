"""豆瓣 ID 与 TMDB ID 的映射缓存表

用于持久化豆瓣 ↔ TMDB 解析结果，避免容器重启后冷启动时反复调用
TMDB 搜索 / Wikidata SPARQL 等慢接口。

- subject 索引：(media_type, douban_id) → tmdb_id（含负缓存：tmdb_id 为 NULL 表示已确认无法匹配）
- title 索引：(media_type, normalized_title, year) → tmdb_id（兼容老缓存键）
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timezone_utils import beijing_now


class DoubanSubjectTmdbMapping(Base):
    """豆瓣 subject_id → TMDB ID 持久化映射"""

    __tablename__ = "douban_subject_tmdb_mapping"
    __table_args__ = (
        UniqueConstraint(
            "media_type", "douban_id", name="uq_douban_subject_tmdb_mapping_key"
        ),
        Index(
            "ix_douban_subject_tmdb_mapping_media_douban",
            "media_type",
            "douban_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_type: Mapped[str] = mapped_column(String(10), nullable=False)
    douban_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """tmdb_id 为 NULL 表示已确认无法匹配（负缓存）；非空为成功匹配。"""

    resolution_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """记录解析来源（imdb_id / wikidata / tmdb_search 等），便于排查。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )


class DoubanTitleTmdbMapping(Base):
    """归一化 title+year → TMDB ID 持久化映射

    用于豆瓣条目缺少 douban_id 时的退化匹配（按标题+年份命中）。
    """

    __tablename__ = "douban_title_tmdb_mapping"
    __table_args__ = (
        UniqueConstraint(
            "media_type",
            "title_normalized",
            "year",
            name="uq_douban_title_tmdb_mapping_key",
        ),
        Index(
            "ix_douban_title_tmdb_mapping_media_title",
            "media_type",
            "title_normalized",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_type: Mapped[str] = mapped_column(String(10), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(256), nullable=False)
    year: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    resolution_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )
