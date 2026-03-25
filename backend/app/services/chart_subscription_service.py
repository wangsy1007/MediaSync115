"""
影视榜单订阅服务。

定时抓取 TMDB / 豆瓣榜单内容，自动为榜单中的影视创建订阅，
后续由现有的"订阅转存"任务完成资源查找与转存。
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_maker
from app.models.models import MediaType, Subscription
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)


# ── 可选榜单定义 ──────────────────────────────────────────────

AVAILABLE_CHARTS: list[dict[str, Any]] = []


def _build_available_charts() -> list[dict[str, Any]]:
    """从 TMDB / 豆瓣 section 定义构建可选榜单列表。"""
    from app.services.tmdb_explore_service import TMDB_SECTION_SOURCES
    from app.services.douban_explore_service import DOUBAN_SECTION_SOURCES

    charts: list[dict[str, Any]] = []
    for src in TMDB_SECTION_SOURCES:
        charts.append({
            "source": "tmdb",
            "key": src["key"],
            "title": src["title"],
            "media_type": src.get("media_type", "mixed"),
        })
    for src in DOUBAN_SECTION_SOURCES:
        charts.append({
            "source": "douban",
            "key": src["key"],
            "title": src["title"],
            "media_type": src.get("media_type", "mixed"),
        })
    return charts


def get_available_charts() -> list[dict[str, Any]]:
    global AVAILABLE_CHARTS
    if not AVAILABLE_CHARTS:
        AVAILABLE_CHARTS = _build_available_charts()
    return AVAILABLE_CHARTS


# ── 核心逻辑 ──────────────────────────────────────────────────

async def run_chart_subscription() -> dict[str, Any]:
    """
    主入口：抓取启用的榜单，为新影视自动创建订阅。

    Returns:
        统计信息 dict。
    """
    settings_data = runtime_settings_service.get_all()
    enabled = bool(settings_data.get("chart_subscription_enabled", False))
    if not enabled:
        await operation_log_service.log_background_event(
            source_type="background_task", module="chart_subscription",
            action="chart_subscription.skip", status="info",
            message="榜单订阅未启用，跳过执行",
        )
        return {"success": True, "message": "榜单订阅未启用", "skipped": True}

    sources: list[dict[str, str]] = settings_data.get("chart_subscription_sources") or []
    if not sources:
        return {"success": True, "message": "未配置任何榜单", "skipped": True}

    limit = int(settings_data.get("chart_subscription_limit", 20) or 20)
    limit = max(1, min(50, limit))

    started_at = datetime.now(timezone.utc).isoformat()
    total_new = 0
    total_existing = 0
    total_failed = 0
    chart_results: list[dict[str, Any]] = []

    for src in sources:
        source_type = str(src.get("source") or "").strip()
        section_key = str(src.get("key") or "").strip()
        if not source_type or not section_key:
            continue

        try:
            items = await _fetch_chart_items(source_type, section_key, limit)
            new_count, existing_count, failed_count = await _subscribe_items(items, source_type)
            total_new += new_count
            total_existing += existing_count
            total_failed += failed_count
            chart_results.append({
                "source": source_type,
                "key": section_key,
                "fetched": len(items),
                "new": new_count,
                "existing": existing_count,
                "failed": failed_count,
            })
            await operation_log_service.log_background_event(
                source_type="background_task", module="chart_subscription",
                action="chart_subscription.chart_done", status="success",
                message=f"榜单 {source_type}:{section_key} 处理完成：抓取 {len(items)} 条，新增 {new_count}，已有 {existing_count}，失败 {failed_count}",
                extra={"source": source_type, "key": section_key, "fetched": len(items), "new": new_count},
            )
        except Exception as exc:
            logger.exception("榜单 %s:%s 抓取失败: %s", source_type, section_key, exc)
            chart_results.append({
                "source": source_type,
                "key": section_key,
                "error": str(exc),
            })
            await operation_log_service.log_background_event(
                source_type="background_task", module="chart_subscription",
                action="chart_subscription.chart_failed", status="failed",
                message=f"榜单 {source_type}:{section_key} 抓取失败：{str(exc)[:200]}",
                extra={"source": source_type, "key": section_key, "error": str(exc)[:300]},
            )

    finished_at = datetime.now(timezone.utc).isoformat()
    message = f"榜单订阅完成：新增 {total_new}，已有 {total_existing}，失败 {total_failed}"
    logger.info(message)
    await operation_log_service.log_background_event(
        source_type="background_task", module="chart_subscription",
        action="chart_subscription.finish", status="success" if total_failed == 0 else "warning",
        message=message,
        extra={"total_new": total_new, "total_existing": total_existing, "total_failed": total_failed},
    )

    return {
        "success": True,
        "message": message,
        "started_at": started_at,
        "finished_at": finished_at,
        "total_new": total_new,
        "total_existing": total_existing,
        "total_failed": total_failed,
        "charts": chart_results,
    }


# ── 榜单抓取 ──────────────────────────────────────────────────

async def _fetch_chart_items(
    source_type: str,
    section_key: str,
    limit: int,
) -> list[dict[str, Any]]:
    """从指定榜单获取条目列表。"""
    if source_type == "tmdb":
        return await _fetch_tmdb_chart(section_key, limit)
    elif source_type == "douban":
        return await _fetch_douban_chart(section_key, limit)
    else:
        raise ValueError(f"不支持的榜单来源: {source_type}")


async def _fetch_tmdb_chart(section_key: str, limit: int) -> list[dict[str, Any]]:
    from app.services.tmdb_explore_service import TMDB_SECTION_SOURCES, fetch_tmdb_section

    source = next((s for s in TMDB_SECTION_SOURCES if s["key"] == section_key), None)
    if not source:
        raise ValueError(f"未知 TMDB 榜单: {section_key}")

    result = await fetch_tmdb_section(source, limit=limit, refresh=True, start=0)
    items = result.get("items") or []
    # TMDB 条目已有 tmdb_id，直接返回
    return items


async def _fetch_douban_chart(section_key: str, limit: int) -> list[dict[str, Any]]:
    from app.services.douban_explore_service import (
        DOUBAN_SECTION_SOURCES,
        fetch_douban_section,
    )

    source = next((s for s in DOUBAN_SECTION_SOURCES if s["key"] == section_key), None)
    if not source:
        raise ValueError(f"未知豆瓣榜单: {section_key}")

    result = await fetch_douban_section(
        source, limit=limit, refresh=True, start=0,
        home_prime_limit=0, sync_prime_limit=limit, async_backfill_limit=0,
    )
    items = result.get("items") or []
    return items


# ── 自动订阅 ──────────────────────────────────────────────────

async def _subscribe_items(
    items: list[dict[str, Any]],
    source_type: str,
) -> tuple[int, int, int]:
    """
    为榜单条目创建订阅。

    Returns:
        (new_count, existing_count, failed_count)
    """
    new_count = 0
    existing_count = 0
    failed_count = 0

    for item in items:
        try:
            tmdb_id = item.get("tmdb_id")
            if tmdb_id is None:
                # 豆瓣条目可能没有 tmdb_id，需要尝试解析
                if source_type == "douban":
                    tmdb_id = await _resolve_douban_tmdb_id(item)
                if tmdb_id is None:
                    failed_count += 1
                    continue

            tmdb_id = int(tmdb_id)
            media_type_str = str(item.get("media_type") or "movie").strip().lower()
            media_enum = MediaType.TV if media_type_str == "tv" else MediaType.MOVIE

            title = str(
                item.get("title") or item.get("name") or ""
            ).strip() or f"TMDB {tmdb_id}"
            year = _normalize_year(item.get("year"))
            rating = _normalize_rating(item.get("rating") or item.get("vote_average"))
            overview = str(item.get("intro") or item.get("overview") or "").strip()
            poster_path = str(
                item.get("poster_url") or item.get("poster_path") or ""
            ).strip() or None
            douban_id = str(item.get("douban_id") or "").strip() or None

            created = await _create_subscription_if_not_exists(
                tmdb_id=tmdb_id,
                media_type=media_enum,
                title=title,
                year=year,
                rating=rating,
                overview=overview,
                poster_path=poster_path,
                douban_id=douban_id,
            )
            if created:
                new_count += 1
            else:
                existing_count += 1
        except Exception as exc:
            logger.warning("榜单条目订阅失败: %s — %s", item.get("title"), exc)
            failed_count += 1

    return new_count, existing_count, failed_count


async def _resolve_douban_tmdb_id(item: dict[str, Any]) -> int | None:
    """尝试将豆瓣条目解析为 TMDB ID。"""
    from app.services.douban_explore_service import resolve_douban_explore_item

    douban_id = str(item.get("douban_id") or item.get("id") or "").strip()
    title = str(item.get("title") or item.get("name") or "").strip()
    media_type = str(item.get("media_type") or "movie").strip()
    year = str(item.get("year") or "").strip() or None

    if not douban_id or not title:
        return None

    try:
        result = await resolve_douban_explore_item(
            douban_id=douban_id,
            title=title,
            media_type=media_type,
            year=year,
            tmdb_id=item.get("tmdb_id"),
            alternative_titles=item.get("aliases"),
        )
        if result and result.get("resolved"):
            return int(result["tmdb_id"])
    except Exception as exc:
        logger.debug("豆瓣 → TMDB 解析失败: %s — %s", title, exc)
    return None


async def _create_subscription_if_not_exists(
    *,
    tmdb_id: int,
    media_type: MediaType,
    title: str,
    year: str | None,
    rating: float | None,
    overview: str,
    poster_path: str | None,
    douban_id: str | None,
) -> bool:
    """
    创建订阅（如果不存在）。

    Returns:
        True 表示新建成功，False 表示已存在。
    """
    async with async_session_maker() as db:
        conditions = [
            and_(Subscription.tmdb_id == tmdb_id, Subscription.media_type == media_type)
        ]
        if douban_id:
            conditions.append(Subscription.douban_id == douban_id)

        existing = await db.execute(
            select(Subscription).where(or_(*conditions)).limit(1)
        )
        if existing.scalar_one_or_none():
            return False

        sub = Subscription(
            tmdb_id=tmdb_id,
            douban_id=douban_id,
            title=title,
            media_type=media_type,
            poster_path=poster_path,
            overview=overview,
            year=year,
            rating=rating,
            is_active=True,
            auto_download=True,
        )
        db.add(sub)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return False
        return True


# ── 辅助 ──────────────────────────────────────────────────────

def _normalize_year(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()[:4]
    return s if s.isdigit() and len(s) == 4 else None


def _normalize_rating(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None
