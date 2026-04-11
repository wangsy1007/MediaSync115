import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings


TMDB_EXPLORE_CACHE_TTL_SECONDS = 60 * 30
TMDB_SECTION_PAGE_SIZE = 20
TMDB_SECTION_MAX_COUNT = 50

TMDB_SECTION_SOURCES = [
    {
        "key": "trending_all_week",
        "title": "TMDB 趋势总榜（周）",
        "tag": "Trending All / Week",
        "path": "/trending/all/week",
        "media_type": "mixed",
    },
    {
        "key": "trending_movie_week",
        "title": "TMDB 电影趋势（周）",
        "tag": "Trending Movie / Week",
        "path": "/trending/movie/week",
        "media_type": "movie",
    },
    {
        "key": "trending_tv_week",
        "title": "TMDB 剧集趋势（周）",
        "tag": "Trending TV / Week",
        "path": "/trending/tv/week",
        "media_type": "tv",
    },
    {
        "key": "movie_popular",
        "title": "TMDB 热门电影",
        "tag": "Movie Popular",
        "path": "/movie/popular",
        "media_type": "movie",
    },
    {
        "key": "movie_top_rated",
        "title": "TMDB 高分电影",
        "tag": "Movie Top Rated",
        "path": "/movie/top_rated",
        "media_type": "movie",
    },
    {
        "key": "movie_now_playing",
        "title": "TMDB 正在热映",
        "tag": "Movie Now Playing",
        "path": "/movie/now_playing",
        "media_type": "movie",
    },
    {
        "key": "movie_upcoming",
        "title": "TMDB 即将上映",
        "tag": "Movie Upcoming",
        "path": "/movie/upcoming",
        "media_type": "movie",
    },
    {
        "key": "tv_popular",
        "title": "TMDB 热门剧集",
        "tag": "TV Popular",
        "path": "/tv/popular",
        "media_type": "tv",
    },
    {
        "key": "tv_top_rated",
        "title": "TMDB 高分剧集",
        "tag": "TV Top Rated",
        "path": "/tv/top_rated",
        "media_type": "tv",
    },
    {
        "key": "tv_on_the_air",
        "title": "TMDB 播出中剧集",
        "tag": "TV On The Air",
        "path": "/tv/on_the_air",
        "media_type": "tv",
    },
    {
        "key": "tv_airing_today",
        "title": "TMDB 今日播出",
        "tag": "TV Airing Today",
        "path": "/tv/airing_today",
        "media_type": "tv",
    },
    {
        "key": "discover_movie_score",
        "title": "TMDB 年度高分电影",
        "tag": "Discover Movie Score",
        "path": "/discover/movie",
        "media_type": "movie",
        "extra_params": {
            "sort_by": "vote_average.desc",
            "vote_count.gte": 2000,
            "vote_average.gte": 7,
        },
    },
    {
        "key": "discover_tv_score",
        "title": "TMDB 年度高分剧集",
        "tag": "Discover TV Score",
        "path": "/discover/tv",
        "media_type": "tv",
        "extra_params": {
            "sort_by": "vote_average.desc",
            "vote_count.gte": 800,
            "vote_average.gte": 7,
        },
    },
]


_tmdb_sections_cache: dict[str, dict[str, Any]] = {}


def _build_section_cache_key(section_key: str, start: int, count: int) -> str:
    return f"{section_key}:{start}:{count}"


def _normalize_media_type(source_type: str, raw_item: dict[str, Any]) -> str:
    if source_type in {"movie", "tv"}:
        return source_type
    raw_type = str(raw_item.get("media_type") or "").strip().lower()
    if raw_type in {"movie", "tv"}:
        return raw_type
    return "movie"


def _normalize_item(
    raw_item: dict[str, Any], source_type: str, rank: int
) -> Optional[dict[str, Any]]:
    media_type = _normalize_media_type(source_type, raw_item)
    raw_id = raw_item.get("id")
    try:
        tmdb_id = int(raw_id)
    except Exception:
        return None

    if media_type == "tv":
        title = str(raw_item.get("name") or raw_item.get("title") or "").strip()
        date_value = str(raw_item.get("first_air_date") or "").strip()
    else:
        title = str(raw_item.get("title") or raw_item.get("name") or "").strip()
        date_value = str(raw_item.get("release_date") or "").strip()

    if not title:
        return None

    year = date_value[:4] if len(date_value) >= 4 and date_value[:4].isdigit() else None
    poster_path = str(raw_item.get("poster_path") or "").strip()
    poster_url = ""
    if poster_path:
        poster_url = f"{settings.TMDB_IMAGE_BASE_URL}{poster_path}"

    rating = raw_item.get("vote_average")
    try:
        rating = float(rating)
    except Exception:
        rating = None
    if rating is not None and rating <= 0:
        rating = None

    intro = str(raw_item.get("overview") or "").strip() or "TMDB 榜单推荐"

    return {
        "rank": rank,
        "id": tmdb_id,
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "year": year,
        "poster_url": poster_url,
        "intro": intro,
        "rating": rating,
    }


def _required_tmdb_params(page: int) -> dict[str, Any]:
    if not settings.TMDB_API_KEY:
        raise ValueError("TMDB_API_KEY is not configured")
    return {
        "api_key": settings.TMDB_API_KEY,
        "language": settings.TMDB_LANGUAGE,
        "region": settings.TMDB_REGION,
        "page": page,
    }


async def _fetch_tmdb_page(
    source: dict[str, Any],
    page: int,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    params = _required_tmdb_params(page)
    extra_params = source.get("extra_params") or {}
    params.update(extra_params)
    response = await client.get(
        f"{settings.TMDB_BASE_URL}{source['path']}",
        params=params,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    return {}


def _prepare_pages(start: int, count: int) -> tuple[int, int, int, int]:
    page_start = (start // TMDB_SECTION_PAGE_SIZE) + 1
    page_end = ((start + count - 1) // TMDB_SECTION_PAGE_SIZE) + 1
    global_offset = (page_start - 1) * TMDB_SECTION_PAGE_SIZE
    local_start = max(start - global_offset, 0)
    local_end = local_start + count
    return page_start, page_end, local_start, local_end


async def fetch_tmdb_section(
    source: dict[str, Any],
    limit: int,
    refresh: bool,
    start: int = 0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    key = source["key"]
    now = time.time()
    count = min(max(limit, 1), TMDB_SECTION_MAX_COUNT)
    start = max(start, 0)
    cache_key = _build_section_cache_key(key, start, count)
    cache_item = _tmdb_sections_cache.setdefault(
        cache_key,
        {"expires_at": 0.0, "payload": None},
    )

    if (
        not refresh
        and cache_item["payload"] is not None
        and now < cache_item["expires_at"]
    ):
        return cache_item["payload"]

    page_start, page_end, local_start, local_end = _prepare_pages(start, count)
    base_url = f"{settings.TMDB_BASE_URL}{source['path']}"

    async def _request_with_client(active_client: httpx.AsyncClient) -> dict[str, Any]:
        page_payloads = await asyncio.gather(
            *[
                _fetch_tmdb_page(source=source, page=page, client=active_client)
                for page in range(page_start, page_end + 1)
            ]
        )

        all_items = []
        total_results = 0
        for idx, payload in enumerate(page_payloads):
            if idx == 0:
                try:
                    total_results = int(payload.get("total_results") or 0)
                except Exception:
                    total_results = 0
            page_items = payload.get("results")
            if isinstance(page_items, list):
                all_items.extend([row for row in page_items if isinstance(row, dict)])

        sliced = all_items[local_start:local_end]
        normalized_items = []
        for index, raw_item in enumerate(sliced):
            normalized = _normalize_item(
                raw_item=raw_item,
                source_type=source["media_type"],
                rank=start + index + 1,
            )
            if normalized:
                normalized_items.append(normalized)

        discovered_total = start + len(normalized_items)
        section_total = max(total_results, discovered_total)
        result = {
            "key": source["key"],
            "title": source["title"],
            "tag": source["tag"],
            "source_url": base_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "total": section_total,
            "start": start,
            "count": count,
            "items": normalized_items,
        }
        return result

    try:
        if client is None:
            from app.utils.proxy import proxy_manager

            async with proxy_manager.create_httpx_client(
                timeout=30.0, http2=False
            ) as local_client:
                result = await _request_with_client(local_client)
        else:
            result = await _request_with_client(client)

        cache_item["payload"] = result
        cache_item["expires_at"] = now + TMDB_EXPLORE_CACHE_TTL_SECONDS
        return result
    except Exception as exc:
        if cache_item["payload"] is not None:
            return cache_item["payload"]
        raise exc
