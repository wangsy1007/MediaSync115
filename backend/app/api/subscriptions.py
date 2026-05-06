import json
import re
import asyncio

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sa_delete, select, or_, and_
from sqlalchemy.exc import IntegrityError, OperationalError
from app.core.database import get_db
from app.models.models import (
    DownloadRecord,
    ExecutionStatus,
    MediaStatus,
    MediaType,
    Subscription,
    SubscriptionExecutionLog,
    SubscriptionStepLog,
)
from app.services.operation_log_service import operation_log_service
from app.services.subscription_service import subscription_service
from app.services.subscription_run_task_service import subscription_run_task_service
from app.services.tmdb_service import tmdb_service
from app.services.tv_missing_service import tv_missing_service
from pydantic import BaseModel
from typing import Any, Optional, List
from datetime import datetime

router = APIRouter(prefix="/subscriptions", tags=["订阅"])

_tmdb_poster_path_pattern = re.compile(
    r"(?:https?:)?//image\.tmdb\.org/t/p/[^/]+(/.+)$", re.IGNORECASE
)


def normalize_tmdb_poster_path(raw_path: str | None) -> str | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    if value.startswith("/"):
        return value

    matched = _tmdb_poster_path_pattern.match(value)
    if matched:
        normalized = str(matched.group(1) or "").strip()
        return normalized if normalized.startswith("/") else None
    return None


def sanitize_poster_path(raw_path: str | None) -> str | None:
    """Only keep TMDB-compatible poster path, otherwise return None."""
    return normalize_tmdb_poster_path(raw_path)


async def resolve_tmdb_poster_path(
    tmdb_id: int | None, media_type: MediaType | None
) -> str | None:
    if tmdb_id is None:
        return None
    if media_type not in {MediaType.MOVIE, MediaType.TV}:
        return None

    try:
        payload = (
            await tmdb_service.get_movie_detail(tmdb_id)
            if media_type == MediaType.MOVIE
            else await tmdb_service.get_tv_detail(tmdb_id)
        )
    except Exception:
        return None

    return sanitize_poster_path(payload.get("poster_path"))


def _build_subscription_status_payload(
    subscriptions: list[Subscription],
) -> dict[str, Any]:
    items = []
    douban_id_map = {}
    imdb_id_map = {}

    for sub in subscriptions:
        media_type_value = sub.media_type.value if sub.media_type else None
        item = {
            "id": sub.id,
            "tmdb_id": sub.tmdb_id,
            "douban_id": sub.douban_id,
            "imdb_id": sub.imdb_id,
            "media_type": media_type_value,
            "title": sub.title,
        }
        items.append(item)

        if sub.douban_id:
            douban_id_map[sub.douban_id] = {
                "id": sub.id,
                "tmdb_id": sub.tmdb_id,
                "media_type": media_type_value,
            }
        if sub.imdb_id:
            imdb_id_map[sub.imdb_id] = {
                "id": sub.id,
                "tmdb_id": sub.tmdb_id,
                "douban_id": sub.douban_id,
                "media_type": media_type_value,
            }

    return {
        "items": items,
        "douban_id_map": douban_id_map,
        "imdb_id_map": imdb_id_map,
    }


def classify_failure_reason(error_text: str) -> str:
    text = str(error_text or "").lower()
    if not text:
        return "other"

    risk_tokens = (
        "code=405",
        "method not allowed",
        "rate",
        "too many",
        "频繁",
        "受限",
        "timeout",
    )
    permission_tokens = (
        "4100010",
        "4100012",
        "access",
        "denied",
        "is_access",
        "无权限",
        "禁止",
    )
    invalid_link_tokens = (
        "4100018",
        "share code",
        "提取码",
        "密码",
        "不存在",
        "失效",
        "not found",
        "invalid",
    )

    if any(token in text for token in risk_tokens):
        return "risk"
    if any(token in text for token in permission_tokens):
        return "permission"
    if any(token in text for token in invalid_link_tokens):
        return "invalid_link"
    return "other"


def summarize_failure_groups(details: Any) -> dict[str, int]:
    summary = {"permission": 0, "risk": 0, "invalid_link": 0, "other": 0}
    if not isinstance(details, list):
        return summary

    for item in details:
        if not isinstance(item, dict):
            continue
        category = classify_failure_reason(str(item.get("error") or ""))
        summary[category] = summary.get(category, 0) + 1
    return summary


def normalize_tv_subscription_options(payload: dict[str, Any], media_type: MediaType) -> None:
    if media_type != MediaType.TV:
        payload["tv_scope"] = "all"
        payload["tv_season_number"] = None
        payload["tv_episode_start"] = None
        payload["tv_episode_end"] = None
        payload["tv_follow_mode"] = "missing"
        payload["tv_include_specials"] = False
        return

    scope = str(payload.get("tv_scope") or "all").strip().lower()
    if scope not in {"all", "season", "episode_range"}:
        raise HTTPException(status_code=400, detail="无效的剧集订阅范围")
    follow_mode = str(payload.get("tv_follow_mode") or "missing").strip().lower()
    if follow_mode not in {"missing", "new"}:
        raise HTTPException(status_code=400, detail="无效的剧集追踪模式")

    season_number = payload.get("tv_season_number")
    episode_start = payload.get("tv_episode_start")
    episode_end = payload.get("tv_episode_end")
    if scope in {"season", "episode_range"}:
        if season_number is None or int(season_number) < 0:
            raise HTTPException(status_code=400, detail="指定季订阅需要有效季号")
        payload["tv_season_number"] = int(season_number)
    else:
        payload["tv_season_number"] = None

    if scope == "episode_range":
        if episode_start is None or episode_end is None:
            raise HTTPException(status_code=400, detail="指定集段订阅需要起止集号")
        episode_start = int(episode_start)
        episode_end = int(episode_end)
        if episode_start <= 0 or episode_end <= 0 or episode_start > episode_end:
            raise HTTPException(status_code=400, detail="无效的订阅集段范围")
        payload["tv_episode_start"] = episode_start
        payload["tv_episode_end"] = episode_end
    else:
        payload["tv_episode_start"] = None
        payload["tv_episode_end"] = None

    payload["tv_scope"] = scope
    payload["tv_follow_mode"] = follow_mode
    payload["tv_include_specials"] = bool(payload.get("tv_include_specials"))


class SubscriptionCreate(BaseModel):
    douban_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    title: str
    media_type: MediaType
    poster_path: Optional[str] = None
    overview: Optional[str] = None
    year: Optional[str] = None
    rating: Optional[float] = None
    auto_download: bool = True
    tv_scope: str = "all"
    tv_season_number: Optional[int] = None
    tv_episode_start: Optional[int] = None
    tv_episode_end: Optional[int] = None
    tv_follow_mode: str = "missing"
    tv_include_specials: bool = False
    preferred_resolutions: Optional[List[str]] = None
    preferred_codecs: Optional[List[str]] = None
    preferred_hdr: Optional[List[str]] = None
    preferred_audio: Optional[List[str]] = None
    preferred_subtitles: Optional[List[str]] = None
    exclude_tags: Optional[List[str]] = None
    min_size_gb: Optional[float] = None
    max_size_gb: Optional[float] = None


class SubscriptionUpdate(BaseModel):
    title: Optional[str] = None
    is_active: Optional[bool] = None
    tv_scope: Optional[str] = None
    tv_season_number: Optional[int] = None
    tv_episode_start: Optional[int] = None
    tv_episode_end: Optional[int] = None
    tv_follow_mode: Optional[str] = None
    tv_include_specials: Optional[bool] = None
    preferred_resolutions: Optional[List[str]] = None
    preferred_codecs: Optional[List[str]] = None
    preferred_hdr: Optional[List[str]] = None
    preferred_audio: Optional[List[str]] = None
    preferred_subtitles: Optional[List[str]] = None
    exclude_tags: Optional[List[str]] = None
    min_size_gb: Optional[float] = None
    max_size_gb: Optional[float] = None


class DownloadRecordCreate(BaseModel):
    resource_name: str
    resource_url: str
    resource_type: str
    file_id: Optional[str] = None


class SubscriptionRunRequest(BaseModel):
    channel: str
    force_auto_download: bool = False


class DownloadRecordUpdate(BaseModel):
    status: Optional[MediaStatus] = None
    error_message: Optional[str] = None
    offline_info_hash: Optional[str] = None
    offline_task_id: Optional[str] = None
    offline_status: Optional[str] = None


async def _enrich_subscription_ids(
    douban_id: Optional[str],
    tmdb_id: Optional[int],
    media_type: MediaType,
) -> dict[str, Any]:
    """自动补全订阅的 ID 信息（douban_id, tmdb_id, imdb_id）

    通过 IMDB ID 作为桥梁，关联豆瓣和 TMDB 的数据。
    """
    from app.services.douban_explore_service import (
        _query_wikidata_bridge,
        _normalize_external_id,
    )

    result: dict[str, Any] = {}

    # 如果提供了豆瓣 ID，尝试获取 IMDB ID 和 TMDB ID
    if douban_id and not tmdb_id:
        try:
            wikidata_bridge = await _query_wikidata_bridge(douban_id)
            imdb_id = _normalize_external_id(wikidata_bridge.get("imdb_id"))
            if imdb_id:
                result["imdb_id"] = imdb_id

            # 根据媒体类型获取对应的 TMDB ID
            normalized_type = "tv" if media_type == MediaType.TV else "movie"
            tmdb_key = "tmdb_tv_id" if normalized_type == "tv" else "tmdb_movie_id"
            wikidata_tmdb = wikidata_bridge.get(tmdb_key)
            if wikidata_tmdb:
                try:
                    result["tmdb_id"] = int(wikidata_tmdb)
                except (ValueError, TypeError):
                    pass

            # 如果 Wikidata 没有 TMDB ID，但有 IMDB ID，尝试从 TMDB 查找
            if "tmdb_id" not in result and imdb_id:
                try:
                    tmdb_find_result = await tmdb_service.find_by_imdb_id(imdb_id)
                    if tmdb_find_result.get("found"):
                        tmdb_item = (
                            tmdb_find_result.get("movie")
                            if normalized_type == "movie"
                            else tmdb_find_result.get("tv")
                        )
                        if not tmdb_item:
                            tmdb_item = (
                                tmdb_find_result.get("tv")
                                if normalized_type == "movie"
                                else tmdb_find_result.get("movie")
                            )
                        if tmdb_item:
                            result["tmdb_id"] = tmdb_item.get("tmdb_id")
                except Exception:
                    pass
        except Exception:
            pass

    # 如果提供了 TMDB ID，尝试获取 IMDB ID 和豆瓣 ID
    elif tmdb_id and not douban_id:
        try:
            normalized_type = "tv" if media_type == MediaType.TV else "movie"
            if normalized_type == "tv":
                external_ids = await tmdb_service.get_tv_external_ids(tmdb_id)
            else:
                external_ids = await tmdb_service.get_movie_external_ids(tmdb_id)

            imdb_id = _normalize_external_id(external_ids.get("imdb_id"))
            if imdb_id:
                result["imdb_id"] = imdb_id

                # 尝试从 Wikidata 获取豆瓣 ID
                try:
                    query = f'''
SELECT ?doubanId WHERE {{
  ?item wdt:P345 "{imdb_id}" .
  OPTIONAL {{ ?item wdt:P4529 ?doubanId . }}
}}
LIMIT 1
'''.strip()

                    async with httpx.AsyncClient(timeout=15.0) as client:
                        wikidata_response = await client.get(
                            "https://query.wikidata.org/sparql",
                            params={"query": query, "format": "json"},
                            headers={"Accept": "application/sparql-results+json"},
                        )
                        wikidata_response.raise_for_status()
                        wikidata_payload = wikidata_response.json()
                        bindings = ((wikidata_payload or {}).get("results") or {}).get(
                            "bindings"
                        ) or []
                        if bindings:
                            douban_id_from_wiki = (
                                bindings[0].get("doubanId") or {}
                            ).get("value")
                            if douban_id_from_wiki:
                                result["douban_id"] = douban_id_from_wiki
                except Exception:
                    pass
        except Exception:
            pass

    return result


@router.post("")
async def create_subscription(
    subscription: SubscriptionCreate, db: AsyncSession = Depends(get_db)
):
    dedupe_conditions = []
    if subscription.douban_id:
        dedupe_conditions.append(Subscription.douban_id == subscription.douban_id)
    if subscription.tmdb_id is not None:
        dedupe_conditions.append(
            and_(
                Subscription.tmdb_id == subscription.tmdb_id,
                Subscription.media_type == subscription.media_type,
            )
        )

    if not dedupe_conditions:
        raise HTTPException(status_code=400, detail="至少需要提供 douban_id 或 tmdb_id")

    existing = await db.execute(select(Subscription).where(or_(*dedupe_conditions)))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Subscription already exists")

    payload = subscription.model_dump()
    normalize_tv_subscription_options(payload, subscription.media_type)

    # 自动补全 ID 信息
    enriched_ids = await _enrich_subscription_ids(
        subscription.douban_id,
        subscription.tmdb_id,
        subscription.media_type,
    )
    payload.update(enriched_ids)

    payload["poster_path"] = await resolve_tmdb_poster_path(
        payload.get("tmdb_id"),
        payload.get("media_type"),
    ) or sanitize_poster_path(payload.get("poster_path"))

    new_subscription = Subscription(**payload)
    new_subscription.auto_download = True
    db.add(new_subscription)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Subscription already exists")
    await db.refresh(new_subscription)
    media_label = "电影" if subscription.media_type == MediaType.MOVIE else "电视剧"
    await operation_log_service.log_background_event(
        source_type="api",
        module="subscriptions",
        action="subscription.create",
        status="success",
        message=f"新增{media_label}订阅：{new_subscription.title}（TMDB: {new_subscription.tmdb_id or '无'}）",
        extra={
            "subscription_id": new_subscription.id,
            "title": new_subscription.title,
            "media_type": media_label,
            "tmdb_id": new_subscription.tmdb_id,
        },
    )

    # 发送订阅创建事件到 Kafka
    try:
        from app.analytics import kafka_producer

        if kafka_producer._enabled:
            kafka_producer.send(
                event_type="subscription_create",
                data={
                    "subscription_id": new_subscription.id,
                    "title": new_subscription.title,
                    "media_type": str(subscription.media_type),
                    "tmdb_id": new_subscription.tmdb_id,
                    "year": new_subscription.year,
                    "rating": new_subscription.rating,
                },
                key=str(new_subscription.id),
            )
    except Exception:
        pass

    return new_subscription


@router.get("")
async def list_subscriptions(
    is_active: Optional[bool] = None,
    media_type: Optional[MediaType] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Subscription)
    if is_active is not None:
        query = query.where(Subscription.is_active == is_active)
    if media_type:
        query = query.where(Subscription.media_type == media_type)
    result = await db.execute(query.order_by(Subscription.created_at.desc()))
    subscriptions = result.scalars().all()

    need_enrich: list[Subscription] = []
    dirty = False
    for sub in subscriptions:
        normalized_path = sanitize_poster_path(sub.poster_path)
        if normalized_path:
            if normalized_path != sub.poster_path:
                sub.poster_path = normalized_path
                dirty = True
            continue

        if sub.tmdb_id is None or sub.media_type not in {MediaType.MOVIE, MediaType.TV}:
            if sub.poster_path is not None:
                sub.poster_path = None
                dirty = True
            continue

        need_enrich.append(sub)

    if need_enrich:
        semaphore = asyncio.Semaphore(5)

        async def enrich_one(sub: Subscription) -> tuple[Subscription, str | None]:
            async with semaphore:
                poster_path = await resolve_tmdb_poster_path(
                    sub.tmdb_id, sub.media_type
                )
                return sub, poster_path

        enrich_results = await asyncio.gather(*(enrich_one(sub) for sub in need_enrich))
        for sub, poster_path in enrich_results:
            if poster_path != sub.poster_path:
                sub.poster_path = poster_path
                dirty = True

    if dirty:
        await db.commit()

    payload = _build_subscription_status_payload(subscriptions)
    payload["items"] = subscriptions
    return payload


@router.get("/status-map")
async def get_subscription_status_map(
    is_active: Optional[bool] = True,
    media_type: Optional[MediaType] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Subscription)
    if is_active is not None:
        query = query.where(Subscription.is_active == is_active)
    if media_type:
        query = query.where(Subscription.media_type == media_type)

    result = await db.execute(query.order_by(Subscription.created_at.desc()))
    subscriptions = result.scalars().all()
    return _build_subscription_status_payload(subscriptions)


@router.get("/{subscription_id}")
async def get_subscription(subscription_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return subscription


@router.get("/missing-status/tv")
async def list_tv_missing_status(
    only_missing: bool = Query(True),
    limit: int = Query(200, ge=1, le=1000),
    refresh: bool = Query(False, description="是否忽略缓存强制刷新"),
    db: AsyncSession = Depends(get_db),
):
    try:
        has_successful_transfer = (
            select(DownloadRecord.id)
            .where(
                DownloadRecord.subscription_id == Subscription.id,
                or_(
                    DownloadRecord.completed_at.is_not(None),
                    DownloadRecord.status.in_(
                        (MediaStatus.COMPLETED, MediaStatus.OFFLINE_COMPLETED)
                    ),
                ),
            )
            .exists()
        )
        result = await db.execute(
            select(Subscription)
            .where(
                Subscription.media_type == MediaType.TV,
                Subscription.is_active == True,  # noqa: E712
                ~has_successful_transfer,
            )
            .order_by(Subscription.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()

        tmdb_ids = [int(sub.tmdb_id) for sub in rows if sub.tmdb_id is not None]
        options_by_tmdb = {
            int(sub.tmdb_id): {
                "include_specials": bool(sub.tv_include_specials),
                "season_number": sub.tv_season_number if sub.tv_scope in {"season", "episode_range"} else None,
                "episode_start": sub.tv_episode_start if sub.tv_scope == "episode_range" else None,
                "episode_end": sub.tv_episode_end if sub.tv_scope == "episode_range" else None,
                "aired_only": sub.tv_follow_mode == "new",
            }
            for sub in rows
            if sub.tmdb_id is not None
        }
        status_by_tmdb = await tv_missing_service.get_tv_missing_statuses(
            tmdb_ids,
            include_specials=False,
            refresh=bool(refresh),
            options_by_tmdb=options_by_tmdb,
        )

        def build_one(sub: Subscription) -> dict[str, Any]:
            if sub.tmdb_id is None:
                return {
                    "subscription_id": sub.id,
                    "tmdb_id": None,
                    "title": sub.title,
                    "year": sub.year,
                    "poster_path": sub.poster_path,
                    "status": "no_tmdb",
                    "message": "缺少 TMDB ID，无法进行缺集比对",
                    "aired_count": 0,
                    "existing_count": 0,
                    "missing_count": 0,
                    "missing_by_season": {},
                }

            status = status_by_tmdb.get(int(sub.tmdb_id)) or {}
            counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
            return {
                "subscription_id": sub.id,
                "tmdb_id": sub.tmdb_id,
                "title": sub.title,
                "year": sub.year,
                "poster_path": sub.poster_path,
                "status": str(status.get("status") or "unknown"),
                "message": str(status.get("message") or ""),
                "total_count": int(counts.get("total") or counts.get("aired") or 0),
                "aired_count": int(counts.get("aired") or 0),
                "existing_count": int(counts.get("existing") or 0),
                "missing_count": int(counts.get("missing") or 0),
                "missing_by_season": status.get("missing_by_season") or {},
            }

        resolved = [build_one(sub) for sub in rows]
        items: list[dict[str, Any]] = []
        for payload in resolved:
            if only_missing and int(payload.get("missing_count") or 0) == 0:
                continue
            items.append(payload)

        return {
            "items": items,
            "count": len(items),
        }
    except OperationalError:
        raise HTTPException(
            status_code=503,
            detail="数据库繁忙，请稍后重试（后台任务正在写入，访问量较大时建议调整订阅间隔）",
        )


@router.get("/{subscription_id}/tv/missing-status")
async def get_tv_missing_status(
    subscription_id: int,
    refresh: bool = Query(False, description="是否忽略缓存强制刷新"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if subscription.media_type != MediaType.TV:
        raise HTTPException(status_code=400, detail="仅支持电视剧订阅")
    if subscription.tmdb_id is None:
        return {
            "subscription_id": subscription.id,
            "tmdb_id": None,
            "title": subscription.title,
            "year": subscription.year,
            "poster_path": subscription.poster_path,
            "status": "no_tmdb",
            "message": "缺少 TMDB ID，无法进行缺集比对",
            "aired_episodes": [],
            "existing_episodes": [],
            "missing_episodes": [],
            "missing_by_season": {},
            "counts": {"aired": 0, "existing": 0, "missing": 0},
        }

    try:
        status = await tv_missing_service.get_tv_missing_status(
            int(subscription.tmdb_id),
            include_specials=bool(subscription.tv_include_specials),
            refresh=bool(refresh),
            season_number=subscription.tv_season_number if subscription.tv_scope in {"season", "episode_range"} else None,
            episode_start=subscription.tv_episode_start if subscription.tv_scope == "episode_range" else None,
            episode_end=subscription.tv_episode_end if subscription.tv_scope == "episode_range" else None,
            aired_only=subscription.tv_follow_mode == "new",
        )
    except Exception as exc:
        status = {
            "status": "error",
            "message": f"获取缺集状态失败: {exc}",
            "aired_episodes": [],
            "existing_episodes": [],
            "missing_episodes": [],
            "missing_by_season": {},
            "counts": {"aired": 0, "existing": 0, "missing": 0},
        }
    return {
        "subscription_id": subscription.id,
        "tmdb_id": subscription.tmdb_id,
        "title": subscription.title,
        "year": subscription.year,
        "poster_path": subscription.poster_path,
        "status": status.get("status"),
        "message": status.get("message"),
        "aired_episodes": status.get("aired_episodes") or [],
        "existing_episodes": status.get("existing_episodes") or [],
        "missing_episodes": status.get("missing_episodes") or [],
        "missing_by_season": status.get("missing_by_season") or {},
        "counts": status.get("counts") or {"aired": 0, "existing": 0, "missing": 0},
    }


@router.put("/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    update_data: SubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    update_payload = update_data.model_dump(exclude_unset=True)
    if any(key.startswith("tv_") for key in update_payload):
        merged_payload = {
            "tv_scope": subscription.tv_scope,
            "tv_season_number": subscription.tv_season_number,
            "tv_episode_start": subscription.tv_episode_start,
            "tv_episode_end": subscription.tv_episode_end,
            "tv_follow_mode": subscription.tv_follow_mode,
            "tv_include_specials": subscription.tv_include_specials,
        }
        merged_payload.update(
            {key: value for key, value in update_payload.items() if key.startswith("tv_")}
        )
        normalize_tv_subscription_options(merged_payload, subscription.media_type)
        update_payload.update(merged_payload)

    for key, value in update_payload.items():
        setattr(subscription, key, value)

    # 订阅默认始终开启自动转存，避免前后端状态不一致。
    subscription.auto_download = True

    await db.commit()
    await db.refresh(subscription)
    return subscription


@router.delete("/batch/{media_type}")
async def delete_subscriptions_by_type(
    media_type: str, db: AsyncSession = Depends(get_db)
):
    if media_type not in ("movie", "tv"):
        raise HTTPException(status_code=400, detail="media_type 必须为 movie 或 tv")

    subs_result = await db.execute(
        select(Subscription.id).where(Subscription.media_type == media_type)
    )
    sub_ids = [row[0] for row in subs_result.all()]
    if not sub_ids:
        return {"deleted_count": 0}

    await db.execute(
        sa_delete(DownloadRecord).where(DownloadRecord.subscription_id.in_(sub_ids))
    )
    await db.execute(sa_delete(Subscription).where(Subscription.id.in_(sub_ids)))
    await db.commit()
    label = "电影" if media_type == "movie" else "电视剧"
    await operation_log_service.log_background_event(
        source_type="api",
        module="subscriptions",
        action="subscription.batch_delete",
        status="success",
        message=f"批量清空{label}订阅：共删除 {len(sub_ids)} 条",
        extra={"media_type": media_type, "deleted_count": len(sub_ids)},
    )
    return {"deleted_count": len(sub_ids)}


@router.delete("/{subscription_id}")
async def delete_subscription(subscription_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    sub_title = subscription.title
    media_label = "电影" if subscription.media_type == MediaType.MOVIE else "电视剧"

    # 先删除关联下载记录，避免外键约束导致 500。
    downloads = await db.execute(
        select(DownloadRecord).where(DownloadRecord.subscription_id == subscription_id)
    )
    for record in downloads.scalars().all():
        await db.delete(record)

    await db.delete(subscription)
    await db.commit()
    await operation_log_service.log_background_event(
        source_type="api",
        module="subscriptions",
        action="subscription.delete",
        status="success",
        message=f"删除{media_label}订阅：{sub_title}",
        extra={
            "subscription_id": subscription_id,
            "title": sub_title,
            "media_type": media_label,
        },
    )

    # 发送订阅删除事件到 Kafka
    try:
        from app.analytics import kafka_producer

        if kafka_producer._enabled:
            kafka_producer.send(
                event_type="subscription_delete",
                data={
                    "subscription_id": subscription_id,
                    "title": sub_title,
                    "media_type": str(subscription.media_type),
                },
                key=str(subscription_id),
            )
    except Exception:
        pass

    return {"message": "Subscription deleted"}


# ==================== 下载记录相关 ====================


@router.get("/{subscription_id}/downloads")
async def get_subscription_downloads(
    subscription_id: int,
    status: Optional[MediaStatus] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    获取订阅的下载记录列表

    Args:
        subscription_id: 订阅ID
        status: 可选的状态过滤

    Returns:
        下载记录列表
    """
    # 验证订阅存在
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Subscription not found")

    # 查询下载记录
    query = select(DownloadRecord).where(
        DownloadRecord.subscription_id == subscription_id
    )
    if status:
        query = query.where(DownloadRecord.status == status)

    result = await db.execute(query.order_by(DownloadRecord.created_at.desc()))
    return result.scalars().all()


@router.post("/{subscription_id}/downloads")
async def create_download_record(
    subscription_id: int,
    record: DownloadRecordCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建下载记录

    Args:
        subscription_id: 订阅ID
        record: 下载记录信息

    Returns:
        新创建的下载记录
    """
    # 验证订阅存在
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # 创建下载记录
    new_record = DownloadRecord(
        subscription_id=subscription_id,
        resource_name=record.resource_name,
        resource_url=record.resource_url,
        resource_type=record.resource_type,
        file_id=record.file_id,
    )
    db.add(new_record)
    await db.commit()
    await db.refresh(new_record)

    return new_record


@router.get("/{subscription_id}/downloads/{record_id}")
async def get_download_record(
    subscription_id: int, record_id: int, db: AsyncSession = Depends(get_db)
):
    """
    获取单个下载记录详情

    Args:
        subscription_id: 订阅ID
        record_id: 下载记录ID

    Returns:
        下载记录详情
    """
    result = await db.execute(
        select(DownloadRecord).where(
            DownloadRecord.id == record_id,
            DownloadRecord.subscription_id == subscription_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Download record not found")
    return record


@router.put("/{subscription_id}/downloads/{record_id}")
async def update_download_record(
    subscription_id: int,
    record_id: int,
    update_data: DownloadRecordUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新下载记录状态

    Args:
        subscription_id: 订阅ID
        record_id: 下载记录ID
        update_data: 更新数据

    Returns:
        更新后的下载记录
    """
    result = await db.execute(
        select(DownloadRecord).where(
            DownloadRecord.id == record_id,
            DownloadRecord.subscription_id == subscription_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Download record not found")

    if update_data.status is not None:
        record.status = update_data.status
        if update_data.status in {MediaStatus.COMPLETED, MediaStatus.OFFLINE_COMPLETED}:
            now = datetime.utcnow()
            record.completed_at = now
            if update_data.status == MediaStatus.OFFLINE_COMPLETED:
                record.offline_completed_at = now
            record.error_message = None
        elif update_data.status == MediaStatus.OFFLINE_SUBMITTED:
            record.completed_at = None
            if record.offline_submitted_at is None:
                record.offline_submitted_at = datetime.utcnow()
        elif update_data.status == MediaStatus.FAILED:
            record.completed_at = None
        elif update_data.status in {
            MediaStatus.PENDING,
            MediaStatus.MATCHED,
            MediaStatus.DOWNLOADING,
            MediaStatus.TRANSFERRING,
            MediaStatus.ARCHIVING,
        }:
            record.completed_at = None

    if update_data.error_message is not None:
        record.error_message = update_data.error_message
    if update_data.offline_info_hash is not None:
        record.offline_info_hash = update_data.offline_info_hash
    if update_data.offline_task_id is not None:
        record.offline_task_id = update_data.offline_task_id
    if update_data.offline_status is not None:
        record.offline_status = update_data.offline_status

    await db.commit()
    await db.refresh(record)
    return record


@router.delete("/{subscription_id}/downloads/{record_id}")
async def delete_download_record(
    subscription_id: int, record_id: int, db: AsyncSession = Depends(get_db)
):
    """
    删除下载记录

    Args:
        subscription_id: 订阅ID
        record_id: 下载记录ID

    Returns:
        删除结果
    """
    result = await db.execute(
        select(DownloadRecord).where(
            DownloadRecord.id == record_id,
            DownloadRecord.subscription_id == subscription_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Download record not found")

    await db.delete(record)
    await db.commit()
    return {"message": "Download record deleted"}


@router.post("/{subscription_id}/downloads/{record_id}/complete")
async def mark_download_complete(
    subscription_id: int, record_id: int, db: AsyncSession = Depends(get_db)
):
    """
    标记下载记录为已完成

    Args:
        subscription_id: 订阅ID
        record_id: 下载记录ID

    Returns:
        更新后的下载记录
    """
    return await update_download_record(
        subscription_id,
        record_id,
        DownloadRecordUpdate(status=MediaStatus.COMPLETED),
        db,
    )


@router.post("/{subscription_id}/downloads/{record_id}/fail")
async def mark_download_failed(
    subscription_id: int,
    record_id: int,
    error_message: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    标记下载记录为失败

    Args:
        subscription_id: 订阅ID
        record_id: 下载记录ID
        error_message: 错误信息

    Returns:
        更新后的下载记录
    """
    return await update_download_record(
        subscription_id,
        record_id,
        DownloadRecordUpdate(status=MediaStatus.FAILED, error_message=error_message),
        db,
    )


@router.post("/actions/run")
@router.post("/system/run")
async def run_subscription_check(
    payload: SubscriptionRunRequest, db: AsyncSession = Depends(get_db)
):
    await operation_log_service.log_background_event(
        source_type="api",
        module="subscriptions",
        action="subscription.run.manual",
        status="info",
        message=f"手动触发订阅检查（频道：{payload.channel}，强制转存：{'是' if payload.force_auto_download else '否'}）",
        extra={
            "channel": payload.channel,
            "force_auto_download": payload.force_auto_download,
        },
    )
    try:
        return await subscription_service.run_channel_check(
            db,
            payload.channel,
            force_auto_download=bool(payload.force_auto_download),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/actions/run/background")
@router.post("/system/run/background")
async def start_subscription_check_background(payload: SubscriptionRunRequest):
    await operation_log_service.log_background_event(
        source_type="api",
        module="subscriptions",
        action="subscription.run.background",
        status="info",
        message=f"后台启动订阅检查（频道：{payload.channel}，强制转存：{'是' if payload.force_auto_download else '否'}）",
        extra={
            "channel": payload.channel,
            "force_auto_download": payload.force_auto_download,
        },
    )
    try:
        return await subscription_run_task_service.start(
            payload.channel,
            force_auto_download=bool(payload.force_auto_download),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/actions/run/tasks/{task_id}")
@router.get("/system/run/tasks/{task_id}")
async def get_subscription_check_task(task_id: str):
    task = await subscription_run_task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/actions/logs")
@router.get("/system/logs")
async def list_subscription_logs(
    channel: Optional[str] = None,
    status: Optional[ExecutionStatus] = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(SubscriptionExecutionLog)
    if channel:
        query = query.where(SubscriptionExecutionLog.channel == channel)
    if status:
        query = query.where(SubscriptionExecutionLog.status == status)

    result = await db.execute(
        query.order_by(SubscriptionExecutionLog.started_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    items = []
    for item in logs:
        details = None
        if item.details:
            try:
                details = json.loads(item.details)
            except Exception:
                details = item.details
        items.append(
            {
                "id": item.id,
                "channel": item.channel,
                "status": item.status,
                "message": item.message,
                "checked_count": item.checked_count,
                "new_resource_count": item.new_resource_count,
                "failed_count": item.failed_count,
                "details": details,
                "failure_groups": summarize_failure_groups(details),
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
        )
    return items


@router.get("/actions/logs/steps")
@router.get("/system/logs/steps")
async def list_subscription_step_logs(
    channel: Optional[str] = None,
    run_id: Optional[str] = None,
    subscription_id: Optional[int] = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    query = select(SubscriptionStepLog)
    if channel:
        query = query.where(SubscriptionStepLog.channel == channel)
    if run_id:
        query = query.where(SubscriptionStepLog.run_id == run_id)
    if subscription_id is not None:
        query = query.where(SubscriptionStepLog.subscription_id == subscription_id)

    result = await db.execute(
        query.order_by(
            SubscriptionStepLog.created_at.desc(), SubscriptionStepLog.id.desc()
        ).limit(limit)
    )
    rows = result.scalars().all()

    items = []
    for row in rows:
        payload = None
        if row.payload:
            try:
                payload = json.loads(row.payload)
            except Exception:
                payload = row.payload
        items.append(
            {
                "id": row.id,
                "run_id": row.run_id,
                "channel": row.channel,
                "subscription_id": row.subscription_id,
                "subscription_title": row.subscription_title,
                "step": row.step,
                "status": row.status,
                "message": row.message,
                "payload": payload,
                "created_at": row.created_at,
            }
        )
    return items
