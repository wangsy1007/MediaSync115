"""猫眼电影探索榜单服务（热映 / 待映 / 实时票房）。"""

import asyncio
import re
import time
from typing import Any, Optional

import httpx

from app.core.timezone_utils import beijing_now
from app.services import douban_explore_service as douban_explore
from app.services.douban_explore_service import prepare_douban_items_for_library_status

MAOYAN_CACHE_TTL_SECONDS = 60 * 30
MAOYAN_SECTION_MAX_COUNT = 50
MAOYAN_DETAIL_CONCURRENCY = 6
MAOYAN_MORE_LIST_BATCH_SIZE = 8

MAOYAN_SECTION_SOURCES = [
    {
        "key": "movie_on_show",
        "title": "猫眼热映",
        "tag": "热映",
        "fetch_type": "on_show",
        "media_type": "movie",
        "source_url": "https://m.maoyan.com/ajax/movieOnInfoList",
    },
    {
        "key": "movie_coming",
        "title": "猫眼待映",
        "tag": "待映",
        "fetch_type": "coming",
        "media_type": "movie",
        "source_url": "https://m.maoyan.com/ajax/comingList",
    },
    {
        "key": "box_office",
        "title": "猫眼实时票房",
        "tag": "票房",
        "fetch_type": "box_office",
        "media_type": "movie",
        "source_url": "https://piaofang.maoyan.com/dashboard-ajax",
    },
]

_maoyan_sections_cache: dict[str, dict[str, Any]] = {}
_maoyan_full_list_cache: dict[str, dict[str, Any]] = {}


def _build_mobile_headers(referer: str = "https://m.maoyan.com/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
    }


def _build_piaofang_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://piaofang.maoyan.com/",
    }


def _normalize_poster_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url


def _extract_year(raw_date: Any) -> Optional[str]:
    if not isinstance(raw_date, str):
        return None
    match = re.search(r"(?:19|20)\d{2}", raw_date)
    return match.group(0) if match else None


def _extract_rating(raw_score: Any) -> Optional[float]:
    if raw_score is None:
        return None
    try:
        score = float(raw_score)
    except Exception:
        return None
    if score <= 0:
        return None
    return score


def _build_maoyan_web_url(movie_id: Any) -> str:
    try:
        normalized_id = int(movie_id)
    except Exception:
        return ""
    if normalized_id <= 0:
        return ""
    return f"https://m.maoyan.com/movie/{normalized_id}"


def _build_intro(
    *,
    star: Any = None,
    show_info: Any = None,
    extra: Any = None,
    fallback: str = "猫眼榜单推荐",
) -> str:
    parts: list[str] = []
    if isinstance(star, str) and star.strip():
        parts.append(f"主演：{star.strip()}")
    if isinstance(show_info, str) and show_info.strip():
        parts.append(show_info.strip())
    if isinstance(extra, str) and extra.strip():
        parts.append(extra.strip())
    return " · ".join(parts) if parts else fallback


def _normalize_maoyan_movie(
    raw_item: dict[str, Any],
    *,
    rank: int,
    intro: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    try:
        movie_id = int(raw_item.get("id") or raw_item.get("movieId") or 0)
    except Exception:
        return None
    if movie_id <= 0:
        return None

    title = str(raw_item.get("nm") or raw_item.get("movieName") or "").strip()
    if not title:
        return None

    year = _extract_year(raw_item.get("rt") or raw_item.get("releaseInfo"))
    poster_url = _normalize_poster_url(raw_item.get("img"))
    rating = _extract_rating(raw_item.get("sc"))
    resolved_intro = intro or _build_intro(
        star=raw_item.get("star"),
        show_info=raw_item.get("showInfo") or raw_item.get("comingTitle"),
    )

    return {
        "rank": rank,
        "id": f"maoyan:{movie_id}",
        "maoyan_id": movie_id,
        "tmdb_id": None,
        "media_type": "movie",
        "title": title,
        "year": year,
        "poster_url": poster_url,
        "intro": resolved_intro,
        "rating": rating,
        "mapping_status": "unresolved",
        "source_url": _build_maoyan_web_url(movie_id),
    }


def _build_section_cache_key(section_key: str, start: int, count: int) -> str:
    return f"{section_key}:{start}:{count}"


def _build_full_list_cache_key(section_key: str) -> str:
    return section_key


async def _fetch_movie_detail(
    movie_id: int,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    response = await client.get(
        "https://m.maoyan.com/ajax/detailmovie",
        params={"movieId": movie_id},
        headers=_build_mobile_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    detail = payload.get("detailMovie") if isinstance(payload, dict) else None
    return detail if isinstance(detail, dict) else {}


async def _enrich_items_with_details(
    items: list[dict[str, Any]],
    client: httpx.AsyncClient,
) -> None:
    pending = [
        item
        for item in items
        if isinstance(item, dict) and (not item.get("poster_url") or item.get("rating") is None)
    ]
    if not pending:
        return

    semaphore = asyncio.Semaphore(MAOYAN_DETAIL_CONCURRENCY)

    async def _worker(item: dict[str, Any]) -> None:
        try:
            movie_id = int(item.get("maoyan_id") or item.get("id") or 0)
        except Exception:
            return
        if movie_id <= 0:
            return
        async with semaphore:
            try:
                detail = await _fetch_movie_detail(movie_id, client)
            except Exception:
                return
        if not detail:
            return
        if not item.get("poster_url"):
            poster_url = _normalize_poster_url(detail.get("img"))
            if poster_url:
                item["poster_url"] = poster_url
        if item.get("rating") is None:
            rating = _extract_rating(detail.get("sc"))
            if rating is not None:
                item["rating"] = rating
        if not item.get("year"):
            item["year"] = _extract_year(detail.get("rt") or detail.get("pubDesc"))
        enm = str(detail.get("enm") or "").strip()
        if enm:
            item["original_title"] = enm

    await asyncio.gather(*[_worker(item) for item in pending], return_exceptions=True)


async def _fetch_more_movies_by_ids(
    movie_ids: list[int],
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    if not movie_ids:
        return []

    collected: list[dict[str, Any]] = []
    for offset in range(0, len(movie_ids), MAOYAN_MORE_LIST_BATCH_SIZE):
        chunk = movie_ids[offset : offset + MAOYAN_MORE_LIST_BATCH_SIZE]
        ids_param = ",".join(str(movie_id) for movie_id in chunk)
        response = await client.get(
            "https://m.maoyan.com/ajax/moreComingList",
            params={
                "token": "",
                "optimus_code": "10",
                "movieIds": ids_param,
                "optimus_risk_level": "71",
            },
            headers=_build_mobile_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("coming") or payload.get("movieList") or []
        if isinstance(rows, list):
            collected.extend([row for row in rows if isinstance(row, dict)])
    return collected


async def _fetch_on_show_items(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        "https://m.maoyan.com/ajax/movieOnInfoList",
        params={"token": ""},
        headers=_build_mobile_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("invalid maoyan on-show response format")

    raw_items: list[dict[str, Any]] = []
    movie_list = payload.get("movieList")
    if isinstance(movie_list, list):
        raw_items.extend([row for row in movie_list if isinstance(row, dict)])

    seen_ids: set[int] = set()
    for row in raw_items:
        try:
            seen_ids.add(int(row.get("id") or 0))
        except Exception:
            continue

    remaining_ids: list[int] = []
    movie_ids = payload.get("movieIds")
    if isinstance(movie_ids, list):
        for raw_id in movie_ids:
            try:
                movie_id = int(raw_id)
            except Exception:
                continue
            if movie_id > 0 and movie_id not in seen_ids:
                remaining_ids.append(movie_id)

    if remaining_ids:
        raw_items.extend(await _fetch_more_movies_by_ids(remaining_ids, client))

    normalized: list[dict[str, Any]] = []
    dedup_ids: set[int] = set()
    for raw_item in raw_items:
        try:
            movie_id = int(raw_item.get("id") or 0)
        except Exception:
            continue
        if movie_id <= 0 or movie_id in dedup_ids:
            continue
        dedup_ids.add(movie_id)
        item = _normalize_maoyan_movie(raw_item, rank=len(normalized) + 1)
        if item:
            normalized.append(item)
    return normalized


async def _fetch_coming_items(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        "https://m.maoyan.com/ajax/comingList",
        params={"ci": 1, "token": "", "limit": MAOYAN_SECTION_MAX_COUNT},
        headers=_build_mobile_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("invalid maoyan coming response format")

    rows = payload.get("coming") or []
    if not isinstance(rows, list):
        rows = []

    normalized: list[dict[str, Any]] = []
    for raw_item in rows:
        if not isinstance(raw_item, dict):
            continue
        item = _normalize_maoyan_movie(raw_item, rank=len(normalized) + 1)
        if item:
            normalized.append(item)
    return normalized


async def _fetch_box_office_items(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        "https://piaofang.maoyan.com/dashboard-ajax",
        params={
            "orderType": 0,
            "uuid": "mediasync115",
            "version_name": "999.9",
            "channelId": 40009,
            "sType": 0,
            "token": "",
        },
        headers=_build_piaofang_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("invalid maoyan box office response format")

    rows = ((payload.get("movieList") or {}).get("data") or {}).get("list") or []
    if not isinstance(rows, list):
        rows = []

    normalized: list[dict[str, Any]] = []
    for raw_item in rows:
        if not isinstance(raw_item, dict):
            continue
        movie_info = raw_item.get("movieInfo")
        if not isinstance(movie_info, dict):
            continue
        intro = _build_intro(
            extra=" · ".join(
                part
                for part in [
                    str(raw_item.get("sumBoxDesc") or "").strip(),
                    str(raw_item.get("boxRate") or "").strip(),
                    str(movie_info.get("releaseInfo") or "").strip(),
                ]
                if part
            ),
            fallback="猫眼实时票房",
        )
        item = _normalize_maoyan_movie(movie_info, rank=len(normalized) + 1, intro=intro)
        if item:
            normalized.append(item)

    await _enrich_items_with_details(normalized, client)
    return normalized


async def _fetch_full_section_items(
    source: dict[str, Any],
    client: httpx.AsyncClient,
    refresh: bool,
) -> list[dict[str, Any]]:
    cache_key = _build_full_list_cache_key(source["key"])
    now = time.time()
    cache_item = _maoyan_full_list_cache.setdefault(
        cache_key,
        {"expires_at": 0.0, "items": None},
    )
    if (
        not refresh
        and cache_item["items"] is not None
        and now < cache_item["expires_at"]
    ):
        return list(cache_item["items"])

    fetch_type = source.get("fetch_type")
    if fetch_type == "on_show":
        items = await _fetch_on_show_items(client)
    elif fetch_type == "coming":
        items = await _fetch_coming_items(client)
    elif fetch_type == "box_office":
        items = await _fetch_box_office_items(client)
    else:
        raise ValueError(f"unsupported maoyan fetch_type: {fetch_type}")

    cache_item["items"] = items
    cache_item["expires_at"] = now + MAOYAN_CACHE_TTL_SECONDS
    return list(items)


async def _apply_tmdb_mapping_pipeline(
    items: list[dict[str, Any]],
    *,
    sync_prime_limit: Optional[int] = None,
    async_backfill_limit: Optional[int] = None,
) -> None:
    if not items:
        return

    douban_explore._hydrate_tmdb_ids_from_cache(items)
    await douban_explore._hydrate_tmdb_ids_from_db(items)

    backfill_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("tmdb_id"):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        media_type = item.get("media_type")
        if media_type not in {"movie", "tv"}:
            continue
        year = item.get("year") if isinstance(item.get("year"), str) else None
        cache_key = douban_explore._build_tmdb_cache_key(
            title=title.strip(), year=year, media_type=media_type
        )
        if cache_key in seen:
            continue
        seen.add(cache_key)
        backfill_candidates.append(
            {
                "douban_id": "",
                "cache_key": cache_key,
                "title": title.strip(),
                "media_type": media_type,
                "year": year,
            }
        )
    if sync_prime_limit is not None:
        await douban_explore._prime_tmdb_ids_for_home_screen(
            items,
            backfill_candidates,
            sync_prime_limit,
        )
    elif async_backfill_limit is None:
        await douban_explore._prime_tmdb_ids_for_first_screen(items, backfill_candidates)

    effective_async_limit = (
        min(max(int(async_backfill_limit or 0), 0), len(items))
        if async_backfill_limit is not None
        else min(len(items), douban_explore.TMDB_BACKFILL_MAX_ITEMS_PER_SECTION)
    )
    douban_explore._schedule_tmdb_backfill(
        candidates=backfill_candidates,
        limit=effective_async_limit,
    )
    douban_explore._hydrate_tmdb_ids_from_cache(items)


async def fetch_maoyan_section(
    source: dict[str, Any],
    limit: int,
    refresh: bool,
    start: int = 0,
    client: Optional[httpx.AsyncClient] = None,
    sync_prime_limit: Optional[int] = None,
    async_backfill_limit: Optional[int] = None,
) -> dict[str, Any]:
    key = source["key"]
    now = time.time()
    count = min(max(limit, 1), MAOYAN_SECTION_MAX_COUNT)
    start = max(start, 0)
    cache_key = _build_section_cache_key(key, start, count)
    cache_item = _maoyan_sections_cache.setdefault(
        cache_key,
        {"expires_at": 0.0, "payload": None},
    )
    if (
        not refresh
        and cache_item["payload"] is not None
        and now < cache_item["expires_at"]
    ):
        douban_explore._hydrate_tmdb_ids_from_cache(cache_item["payload"].get("items", []))
        return cache_item["payload"]

    async def _request_with_client(active_client: httpx.AsyncClient) -> dict[str, Any]:
        full_items = await _fetch_full_section_items(source, active_client, refresh)
        sliced = full_items[start : start + count]
        for index, item in enumerate(sliced):
            item["rank"] = start + index + 1

        await _apply_tmdb_mapping_pipeline(
            sliced,
            sync_prime_limit=sync_prime_limit,
            async_backfill_limit=async_backfill_limit,
        )

        section_total = len(full_items)
        return {
            "key": source["key"],
            "title": source["title"],
            "tag": source["tag"],
            "source_url": source.get("source_url") or "",
            "fetched_at": beijing_now().isoformat(),
            "total": section_total,
            "start": start,
            "count": count,
            "items": sliced,
        }

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
        cache_item["expires_at"] = now + MAOYAN_CACHE_TTL_SECONDS
        return result
    except Exception as exc:
        if cache_item["payload"] is not None:
            douban_explore._hydrate_tmdb_ids_from_cache(
                cache_item["payload"].get("items", [])
            )
            return cache_item["payload"]
        raise exc


async def prepare_maoyan_items_for_library_status(
    items: list[dict[str, Any]],
    limit: int | None = None,
) -> None:
    """为媒体库角标同步解析猫眼条目的 TMDB ID。"""
    await prepare_douban_items_for_library_status(items, limit)
