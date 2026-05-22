"""豆瓣 ↔ TMDB 映射的持久化缓存服务

为 `douban_explore_service` 内的内存缓存提供 SQLite 后备，避免容器重启
后冷启动时反复调用 TMDB 搜索 / Wikidata SPARQL 等慢接口。

读路径：内存 miss → DB 查询（命中即回填到内存）
写路径：内存 set 时同时 upsert 到 DB（fire-and-forget，不阻塞主流程）

负缓存：tmdb_id 为 NULL 表示已确认无法匹配；负缓存的 DB 行带 30 天过期。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.database import async_session_maker, ensure_tables_exist, is_missing_table_error
from app.core.timezone_utils import beijing_now
from app.models.douban_tmdb_mapping import (
    DoubanSubjectTmdbMapping,
    DoubanTitleTmdbMapping,
)

logger = logging.getLogger(__name__)

# 负缓存（tmdb_id is NULL）的有效期；正缓存永不过期（除非外部触发 refresh）
NEGATIVE_CACHE_VALID_DAYS = 30


class DoubanTmdbMappingService:
    """读写豆瓣 ↔ TMDB 映射缓存。所有方法都是 fire-and-forget，DB 异常不抛出。"""

    async def _ensure_tables(self) -> None:
        await ensure_tables_exist(
            "douban_subject_tmdb_mapping",
            "douban_title_tmdb_mapping",
        )

    # ───── subject (douban_id) ─────

    async def get_subject_mapping(
        self, douban_id: str, media_type: str
    ) -> tuple[bool, Optional[int]]:
        """查询 (media_type, douban_id) → tmdb_id

        Returns:
            (cache_hit, tmdb_id)
            - cache_hit=True, tmdb_id=int → 已成功匹配
            - cache_hit=True, tmdb_id=None → 已确认无法匹配（负缓存）
            - cache_hit=False, tmdb_id=None → 未缓存，需要在线解析
        """
        normalized_id = str(douban_id or "").strip()
        normalized_type = "tv" if media_type == "tv" else "movie"
        if not normalized_id:
            return False, None

        try:
            return await self._get_subject_mapping(normalized_id, normalized_type)
        except OperationalError as exc:
            if not is_missing_table_error(
                exc, "douban_subject_tmdb_mapping", "douban_title_tmdb_mapping"
            ):
                logger.warning("get_subject_mapping failed: %s", exc)
                return False, None
            await self._ensure_tables()
            try:
                return await self._get_subject_mapping(normalized_id, normalized_type)
            except Exception:
                return False, None
        except Exception as exc:
            logger.warning("get_subject_mapping unexpected error: %s", exc)
            return False, None

    async def _get_subject_mapping(
        self, douban_id: str, media_type: str
    ) -> tuple[bool, Optional[int]]:
        async with async_session_maker() as db:
            result = await db.execute(
                select(DoubanSubjectTmdbMapping).where(
                    DoubanSubjectTmdbMapping.media_type == media_type,
                    DoubanSubjectTmdbMapping.douban_id == douban_id,
                )
            )
            row = result.scalar_one_or_none()
            await db.commit()

        if row is None:
            return False, None

        # 负缓存检查过期（兼容 SQLite 取出的 naive datetime）
        if row.tmdb_id is None:
            cutoff = beijing_now() - timedelta(days=NEGATIVE_CACHE_VALID_DAYS)
            row_updated = row.updated_at
            if row_updated is not None:
                if row_updated.tzinfo is None and cutoff.tzinfo is not None:
                    row_updated = row_updated.replace(tzinfo=cutoff.tzinfo)
                if row_updated < cutoff:
                    return False, None

        return True, row.tmdb_id

    async def set_subject_mapping(
        self,
        douban_id: str,
        media_type: str,
        tmdb_id: Optional[int],
        *,
        resolution_source: Optional[str] = None,
    ) -> None:
        """写入或更新 (media_type, douban_id) → tmdb_id

        tmdb_id 为 None 表示负缓存。
        """
        normalized_id = str(douban_id or "").strip()
        normalized_type = "tv" if media_type == "tv" else "movie"
        if not normalized_id:
            return

        try:
            await self._set_subject_mapping(
                normalized_id, normalized_type, tmdb_id, resolution_source
            )
        except OperationalError as exc:
            if not is_missing_table_error(
                exc, "douban_subject_tmdb_mapping", "douban_title_tmdb_mapping"
            ):
                logger.warning("set_subject_mapping failed: %s", exc)
                return
            await self._ensure_tables()
            try:
                await self._set_subject_mapping(
                    normalized_id, normalized_type, tmdb_id, resolution_source
                )
            except Exception:
                pass
        except Exception as exc:
            logger.warning("set_subject_mapping unexpected error: %s", exc)

    async def _set_subject_mapping(
        self,
        douban_id: str,
        media_type: str,
        tmdb_id: Optional[int],
        resolution_source: Optional[str],
    ) -> None:
        async with async_session_maker() as db:
            result = await db.execute(
                select(DoubanSubjectTmdbMapping).where(
                    DoubanSubjectTmdbMapping.media_type == media_type,
                    DoubanSubjectTmdbMapping.douban_id == douban_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = DoubanSubjectTmdbMapping(
                    media_type=media_type,
                    douban_id=douban_id,
                    tmdb_id=tmdb_id,
                    resolution_source=resolution_source,
                )
                db.add(row)
            else:
                row.tmdb_id = tmdb_id
                if resolution_source:
                    row.resolution_source = resolution_source
            await db.commit()

    # ───── title+year (退化匹配) ─────

    async def get_title_mapping(
        self, title_normalized: str, year: str, media_type: str
    ) -> tuple[bool, Optional[int]]:
        """查询 (media_type, title_normalized, year) → tmdb_id"""
        normalized_title = str(title_normalized or "").strip().lower()
        normalized_year = str(year or "").strip()
        normalized_type = "tv" if media_type == "tv" else "movie"
        if not normalized_title:
            return False, None

        try:
            return await self._get_title_mapping(
                normalized_title, normalized_year, normalized_type
            )
        except OperationalError as exc:
            if not is_missing_table_error(
                exc, "douban_subject_tmdb_mapping", "douban_title_tmdb_mapping"
            ):
                logger.warning("get_title_mapping failed: %s", exc)
                return False, None
            await self._ensure_tables()
            try:
                return await self._get_title_mapping(
                    normalized_title, normalized_year, normalized_type
                )
            except Exception:
                return False, None
        except Exception as exc:
            logger.warning("get_title_mapping unexpected error: %s", exc)
            return False, None

    async def _get_title_mapping(
        self, title_normalized: str, year: str, media_type: str
    ) -> tuple[bool, Optional[int]]:
        async with async_session_maker() as db:
            result = await db.execute(
                select(DoubanTitleTmdbMapping).where(
                    DoubanTitleTmdbMapping.media_type == media_type,
                    DoubanTitleTmdbMapping.title_normalized == title_normalized,
                    DoubanTitleTmdbMapping.year == year,
                )
            )
            row = result.scalar_one_or_none()
            await db.commit()

        if row is None:
            return False, None

        if row.tmdb_id is None:
            cutoff = beijing_now() - timedelta(days=NEGATIVE_CACHE_VALID_DAYS)
            row_updated = row.updated_at
            if row_updated is not None:
                if row_updated.tzinfo is None and cutoff.tzinfo is not None:
                    row_updated = row_updated.replace(tzinfo=cutoff.tzinfo)
                if row_updated < cutoff:
                    return False, None

        return True, row.tmdb_id

    async def set_title_mapping(
        self,
        title_normalized: str,
        year: str,
        media_type: str,
        tmdb_id: Optional[int],
        *,
        resolution_source: Optional[str] = None,
    ) -> None:
        normalized_title = str(title_normalized or "").strip().lower()
        normalized_year = str(year or "").strip()
        normalized_type = "tv" if media_type == "tv" else "movie"
        if not normalized_title:
            return

        try:
            await self._set_title_mapping(
                normalized_title,
                normalized_year,
                normalized_type,
                tmdb_id,
                resolution_source,
            )
        except OperationalError as exc:
            if not is_missing_table_error(
                exc, "douban_subject_tmdb_mapping", "douban_title_tmdb_mapping"
            ):
                logger.warning("set_title_mapping failed: %s", exc)
                return
            await self._ensure_tables()
            try:
                await self._set_title_mapping(
                    normalized_title,
                    normalized_year,
                    normalized_type,
                    tmdb_id,
                    resolution_source,
                )
            except Exception:
                pass
        except Exception as exc:
            logger.warning("set_title_mapping unexpected error: %s", exc)

    async def _set_title_mapping(
        self,
        title_normalized: str,
        year: str,
        media_type: str,
        tmdb_id: Optional[int],
        resolution_source: Optional[str],
    ) -> None:
        async with async_session_maker() as db:
            result = await db.execute(
                select(DoubanTitleTmdbMapping).where(
                    DoubanTitleTmdbMapping.media_type == media_type,
                    DoubanTitleTmdbMapping.title_normalized == title_normalized,
                    DoubanTitleTmdbMapping.year == year,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = DoubanTitleTmdbMapping(
                    media_type=media_type,
                    title_normalized=title_normalized,
                    year=year,
                    tmdb_id=tmdb_id,
                    resolution_source=resolution_source,
                )
                db.add(row)
            else:
                row.tmdb_id = tmdb_id
                if resolution_source:
                    row.resolution_source = resolution_source
            await db.commit()


douban_tmdb_mapping_service = DoubanTmdbMappingService()


def schedule_persist_subject_mapping(
    douban_id: str,
    media_type: str,
    tmdb_id: Optional[int],
    *,
    resolution_source: Optional[str] = None,
) -> None:
    """Fire-and-forget 写入持久化缓存，不阻塞主流程。"""
    try:
        asyncio.create_task(
            douban_tmdb_mapping_service.set_subject_mapping(
                douban_id,
                media_type,
                tmdb_id,
                resolution_source=resolution_source,
            )
        )
    except RuntimeError:
        # 没有运行中的 event loop（极少见），忽略
        pass


def schedule_persist_title_mapping(
    title_normalized: str,
    year: str,
    media_type: str,
    tmdb_id: Optional[int],
    *,
    resolution_source: Optional[str] = None,
) -> None:
    """Fire-and-forget 写入持久化缓存，不阻塞主流程。"""
    try:
        asyncio.create_task(
            douban_tmdb_mapping_service.set_title_mapping(
                title_normalized,
                year,
                media_type,
                tmdb_id,
                resolution_source=resolution_source,
            )
        )
    except RuntimeError:
        pass
