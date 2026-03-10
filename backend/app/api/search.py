import asyncio
from collections import OrderedDict
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.douban_explore_service import (
    DOUBAN_SECTION_SOURCES,
    fetch_douban_subject_detail,
    fetch_douban_section,
    resolve_douban_explore_item,
)
from app.services.explore_action_queue_service import explore_action_queue_service
from app.services.emby_service import emby_service
from app.services.explore_home_warmup_service import (
    EXPLORE_HOME_WARMUP_LIMIT,
    explore_home_warmup_service,
)
from app.services.hdhive_service import hdhive_service
from app.services.nullbr_service import nullbr_service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.seedhub_service import seedhub_service
from app.services.seedhub_task_service import seedhub_task_service
from app.services.tg_service import tg_service
from app.services.tmdb_service import tmdb_service
from app.services.tmdb_explore_service import TMDB_SECTION_SOURCES, fetch_tmdb_section
from app.services.tv_missing_service import tv_missing_service

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)
EXPLORE_HOME_SECTION_LIMIT = EXPLORE_HOME_WARMUP_LIMIT
DOUBAN_HOME_SYNC_PRIME_LIMIT = 0

POPULAR_MOVIES_URL = "https://popular-movies-data.stevenlu.com/movies.json"
POPULAR_CACHE_TTL_SECONDS = 60 * 60 * 6
PAN115_CACHE_TTL_SECONDS = 60 * 30
PAN115_EMPTY_CACHE_TTL_SECONDS = 90
POPULAR_SECTION_SOURCES = [
    {
        "key": "popular",
        "title": "综合热度榜",
        "tag": "Popular",
        "url": "https://popular-movies-data.stevenlu.com/movies.json",
    },
    {
        "key": "imdb7",
        "title": "IMDb 7+",
        "tag": "IMDb >= 7",
        "url": "https://popular-movies-data.stevenlu.com/movies-imdb-min7.json",
    },
    {
        "key": "rotten70",
        "title": "烂番茄 70+",
        "tag": "RT >= 70",
        "url": "https://popular-movies-data.stevenlu.com/movies-rottentomatoes-min70.json",
    },
    {
        "key": "metacritic70",
        "title": "Metacritic 70+",
        "tag": "MC >= 70",
        "url": "https://popular-movies-data.stevenlu.com/movies-metacritic-min70.json",
    },
]

_popular_movies_cache = {
    "expires_at": 0.0,
    "payload": None,
}
_popular_sections_cache = {
    source["key"]: {"expires_at": 0.0, "payload": None}
    for source in POPULAR_SECTION_SOURCES
}
_movie_pan115_cache: dict[str, dict] = {}
_tv_pan115_cache: dict[str, dict] = {}
_image_proxy_user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
IMAGE_PROXY_CACHE_TTL_SECONDS = 60 * 60
IMAGE_PROXY_CACHE_MAX_ITEMS = 512
_image_proxy_cache: "OrderedDict[str, tuple[float, bytes, str]]" = OrderedDict()
_image_proxy_cache_lock = asyncio.Lock()
EMBY_BADGE_CACHE_TTL_SECONDS = 60 * 10
_emby_badge_cache: dict[str, dict[str, Any]] = {}
_emby_badge_cache_lock = asyncio.Lock()
_pan115_share_url_pattern = re.compile(
    r"(https?://(?:115(?:cdn)?\.com/s/[A-Za-z0-9]+(?:[^\s\"'<>]*)?|share\.115\.com/[A-Za-z0-9]+(?:[^\s\"'<>]*)?))",
    re.IGNORECASE,
)
_pan115_receive_code_pattern = re.compile(
    r"(?:提取码|提取碼|密码|密碼|password|pwd)\s*[:：=]?\s*([A-Za-z0-9]{4})",
    re.IGNORECASE,
)
_pan115_share_code_hint_pattern = re.compile(
    r"(?:分享码|分享碼|share(?:_|\s*)code)\s*[:：=]?\s*([A-Za-z0-9]{6,32})",
    re.IGNORECASE,
)


class HDHiveUnlockRequest(BaseModel):
    slug: str


class ExploreQueueBaseRequest(BaseModel):
    source: str = "douban"
    id: str | int | None = None
    douban_id: str | None = None
    title: str = ""
    name: str = ""
    original_title: str = ""
    original_name: str = ""
    aliases: list[str] | None = None
    year: str = ""
    media_type: str = "movie"
    tmdb_id: int | None = None
    poster_path: str = ""
    poster_url: str = ""
    overview: str = ""
    intro: str = ""
    rating: float | None = None
    vote_average: float | None = None


class ExploreQueueSubscribeRequest(ExploreQueueBaseRequest):
    intent: str = "subscribe"


class EmbyStatusMapItem(BaseModel):
    media_type: str
    tmdb_id: int


class EmbyStatusMapRequest(BaseModel):
    items: list[EmbyStatusMapItem]


def _normalize_emby_media_type(raw_media_type: Any) -> str:
    value = str(raw_media_type or "").strip().lower()
    if value == "tv":
        return "tv"
    if value == "movie":
        return "movie"
    return ""


def _extract_emby_status_candidates(items: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    candidates: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        media_type = _normalize_emby_media_type(item.get("media_type"))
        if not media_type:
            continue
        tmdb_id = int(item.get("tmdb_id") or 0)
        if tmdb_id <= 0:
            continue
        key = f"{media_type}:{tmdb_id}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append((key, media_type, tmdb_id))
    return candidates


def _collect_section_items(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        items = section.get("items")
        if not isinstance(items, list):
            continue
        rows.extend([item for item in items if isinstance(item, dict)])
    return rows


async def _get_cached_emby_badge_status(cache_key: str) -> dict[str, Any] | None:
    now_ts = time.time()
    async with _emby_badge_cache_lock:
        cached = _emby_badge_cache.get(cache_key)
        if not cached:
            return None
        expires_at = float(cached.get("expires_at") or 0)
        if expires_at <= now_ts:
            _emby_badge_cache.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        return dict(payload) if isinstance(payload, dict) else None


async def _set_cached_emby_badge_status(cache_key: str, payload: dict[str, Any]) -> None:
    async with _emby_badge_cache_lock:
        _emby_badge_cache[cache_key] = {
            "expires_at": time.time() + EMBY_BADGE_CACHE_TTL_SECONDS,
            "payload": dict(payload),
        }
        if len(_emby_badge_cache) > 2000:
            oldest_key = min(
                _emby_badge_cache.items(),
                key=lambda item: float(item[1].get("expires_at") or 0),
            )[0]
            _emby_badge_cache.pop(oldest_key, None)


async def _resolve_emby_status_payload(media_type: str, tmdb_id: int) -> dict[str, Any]:
    if media_type == "tv":
        tv_status = await tv_missing_service.get_tv_missing_status(tmdb_id, include_specials=False)
        status_text = str(tv_status.get("status") or "")
        missing_count = int((tv_status.get("counts") or {}).get("missing") or 0)
        exists_in_emby = status_text == "ok" and missing_count == 0
        return {
            "exists_in_emby": exists_in_emby,
            "status": status_text or "request_failed",
            "matched_type": "tv_complete" if exists_in_emby else "",
        }

    movie_status = await emby_service.get_movie_status_by_tmdb(tmdb_id)
    status_text = str(movie_status.get("status") or "")
    exists_in_emby = status_text == "ok" and bool(movie_status.get("exists"))
    return {
        "exists_in_emby": exists_in_emby,
        "status": status_text or "request_failed",
        "matched_type": "movie" if exists_in_emby else "",
    }


async def _build_emby_status_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates = _extract_emby_status_candidates(items)
    if not candidates:
        return {}

    status_map: dict[str, dict[str, Any]] = {}
    uncached: list[tuple[str, str, int]] = []
    for cache_key, media_type, tmdb_id in candidates:
        cached_payload = await _get_cached_emby_badge_status(cache_key)
        if cached_payload is not None:
            status_map[cache_key] = cached_payload
            continue
        uncached.append((cache_key, media_type, tmdb_id))

    results = await asyncio.gather(
        *(_resolve_emby_status_payload(media_type, tmdb_id) for _, media_type, tmdb_id in uncached),
        return_exceptions=True,
    )
    for (cache_key, _, _), result in zip(uncached, results):
        if isinstance(result, Exception):
            payload = {
                "exists_in_emby": False,
                "status": "request_failed",
                "matched_type": "",
            }
            logger.warning("resolve emby status failed for %s: %s", cache_key, result)
        else:
            payload = result
        status_map[cache_key] = payload
        await _set_cached_emby_badge_status(cache_key, payload)

    return status_map


def _extract_search_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("items", "results", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("items", "results", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _is_115_share_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return (
        "115.com" in host
        or "115cdn.com" in host
        or "anxia.com" in host
    )


def _is_likely_115_share_identifier(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False

    if raw.startswith(("http://", "https://", "//")):
        normalized = raw
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        return _is_115_share_url(normalized)

    return bool(re.match(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]{4})?$", raw))


def _extract_first_string_value(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _iter_string_values(node: Any, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(node, str):
        text = node.strip()
        return [text] if text else []
    if isinstance(node, list):
        values: list[str] = []
        for item in node:
            values.extend(_iter_string_values(item, depth + 1))
        return values
    if isinstance(node, dict):
        values: list[str] = []
        for value in node.values():
            values.extend(_iter_string_values(value, depth + 1))
        return values
    return []


def _extract_pan115_share_link_from_text(text: str, allow_plain_code: bool = False) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    if raw.startswith("//"):
        raw = f"https:{raw}"

    url_match = _pan115_share_url_pattern.search(raw)
    if url_match:
        return url_match.group(1).strip()

    if allow_plain_code and re.fullmatch(r"[A-Za-z0-9]{6,32}(?:-[A-Za-z0-9]{4})?", raw):
        return raw

    receive_code = ""
    receive_match = _pan115_receive_code_pattern.search(raw)
    if receive_match:
        receive_code = receive_match.group(1).strip()

    share_code_match = _pan115_share_code_hint_pattern.search(raw)
    if share_code_match:
        share_code = share_code_match.group(1).strip()
        final_receive = receive_code
        if final_receive and share_code:
            return f"{share_code}-{final_receive}"
        return share_code

    return ""


def _extract_pansou_share_link(row: dict) -> str:
    prioritized_candidate = _extract_first_string_value(
        row,
        [
            "share_link",
            "share_url",
            "url",
            "link",
            "resource_url",
            "source_url",
            "href",
            "share_code",
            "sharecode",
            "code",
        ],
    )
    if prioritized_candidate:
        parsed = _extract_pan115_share_link_from_text(prioritized_candidate, allow_plain_code=True)
        if parsed:
            return parsed

    for text in _iter_string_values(row):
        parsed = _extract_pan115_share_link_from_text(text, allow_plain_code=False)
        if parsed:
            return parsed
    return ""


def _extract_pansou_rows(node: Any, depth: int = 0) -> list[dict]:
    if depth > 5:
        return []

    rows: list[dict] = []
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                rows.append(item)
            rows.extend(_extract_pansou_rows(item, depth + 1))
    elif isinstance(node, dict):
        for value in node.values():
            rows.extend(_extract_pansou_rows(value, depth + 1))
    return rows


def _normalize_pansou_items(payload: Any) -> list[dict]:
    raw_rows = _extract_pansou_rows(payload)
    normalized: list[dict] = []
    seen: set[str] = set()

    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            continue

        share_url = _extract_pansou_share_link(row)

        title = _extract_first_string_value(
            row,
            [
                "title",
                "name",
                "resource_name",
                "file_name",
                "filename",
                "text",
            ],
        )
        if not title and not share_url:
            continue
        if not title:
            title = "盘搜资源"

        cloud_type = _extract_first_string_value(row, ["cloud_type", "cloud", "pan_type"]) or "115"
        summary = _extract_first_string_value(row, ["summary", "desc", "description", "content"])
        size = _extract_first_string_value(row, ["size"])
        if size:
            summary = f"{summary} | {size}" if summary else size

        pan115_savable = _is_likely_115_share_identifier(share_url)

        unique_key = f"{title}|{share_url}"
        if unique_key in seen:
            continue
        seen.add(unique_key)

        resource_id = row.get("id")
        if resource_id is None:
            resource_id = f"pansou-{hashlib.md5(unique_key.encode('utf-8')).hexdigest()[:12]}-{index}"

        normalized.append(
            {
                "id": resource_id,
                "media_type": "resource",
                "title": title,
                "name": title,
                "overview": summary,
                "poster_path": "",
                "source_service": "pansou",
                "pan115_share_link": share_url,
                "pan115_savable": pan115_savable,
                "raw_item": row,
                "cloud_type": cloud_type,
            }
        )

    return normalized


def _build_pansou_search_result(query: str, page: int, payload: Any) -> dict:
    items = _normalize_pansou_items(payload)
    return {
        "query": query,
        "page": page,
        "total_pages": 1 if items else 0,
        "total_results": len(items),
        "items": items,
        "results": items,
    }


def _apply_source_service(items: list[dict], source_service: str) -> list[dict]:
    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["source_service"] = row.get("source_service") or source_service
        normalized.append(row)
    return normalized


def _extract_year_from_date_like(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return ""


def _normalize_keyword_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _strip_keyword_punctuation(value: str) -> str:
    return re.sub(r"[\s\-_·:：,.，。!！?？'\"“”‘’()（）\[\]【】/\\]+", "", value or "")


def _build_pansou_keyword_candidates(payload: dict, media_type: str, tmdb_id: int) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    if media_type == "tv":
        title = _normalize_keyword_text(payload.get("name") or payload.get("title"))
        original_title = _normalize_keyword_text(payload.get("original_name") or payload.get("original_title"))
        date_like = payload.get("first_air_date") or payload.get("release_date") or payload.get("release")
    else:
        title = _normalize_keyword_text(payload.get("title") or payload.get("name"))
        original_title = _normalize_keyword_text(payload.get("original_title") or payload.get("original_name"))
        date_like = payload.get("release_date") or payload.get("release")

    year = _extract_year_from_date_like(date_like)

    def add_keyword(keyword: str) -> None:
        normalized = _normalize_keyword_text(keyword)
        if not normalized:
            return
        fingerprint = normalized.casefold()
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        candidates.append(normalized)

    # Prefer localized title with year, then fallback to localized title.
    if title and year:
        add_keyword(f"{title} {year}")
    add_keyword(title)

    # Then try original title with and without year.
    if original_title and year:
        add_keyword(f"{original_title} {year}")
    add_keyword(original_title)

    if media_type != "tv":
        # Movie-specific fallback variants: de-yeared / punctuation-stripped / subtitle split.
        for raw_title in [title, original_title]:
            base = _normalize_keyword_text(raw_title)
            if not base:
                continue
            if year:
                no_year = _normalize_keyword_text(base.replace(year, ""))
                add_keyword(no_year)
            add_keyword(_strip_keyword_punctuation(base))
            for separator in [":", "：", "-", "·"]:
                if separator not in base:
                    continue
                left, right = [part.strip() for part in base.split(separator, 1)]
                add_keyword(left)
                add_keyword(right)
                if year and left:
                    add_keyword(f"{left} {year}")

    # Last fallback keeps behavior deterministic when TMDB title is missing.
    add_keyword(f"TMDB {tmdb_id}")
    return candidates


def _build_tg_keyword_candidates(payload: dict, media_type: str, tmdb_id: int) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    if media_type == "tv":
        title = _normalize_keyword_text(payload.get("name") or payload.get("title"))
        original_title = _normalize_keyword_text(payload.get("original_name") or payload.get("original_title"))
        date_like = payload.get("first_air_date") or payload.get("release_date") or payload.get("release")
    else:
        title = _normalize_keyword_text(payload.get("title") or payload.get("name"))
        original_title = _normalize_keyword_text(payload.get("original_title") or payload.get("original_name"))
        date_like = payload.get("release_date") or payload.get("release")

    year = _extract_year_from_date_like(date_like)

    def add_keyword(keyword: str) -> None:
        normalized = _normalize_keyword_text(keyword)
        if not normalized:
            return
        fingerprint = normalized.casefold()
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        candidates.append(normalized)

    if title and year:
        add_keyword(f"{title} {year}")
    add_keyword(title)
    if original_title and year:
        add_keyword(f"{original_title} {year}")
    add_keyword(original_title)
    add_keyword(f"TMDB {tmdb_id}")
    return candidates


def _extract_tg_expected_context(payload: dict, media_type: str) -> dict[str, str]:
    if media_type == "tv":
        title = _normalize_keyword_text(payload.get("name") or payload.get("title"))
        original_title = _normalize_keyword_text(payload.get("original_name") or payload.get("original_title"))
        date_like = payload.get("first_air_date") or payload.get("release_date") or payload.get("release")
    else:
        title = _normalize_keyword_text(payload.get("title") or payload.get("name"))
        original_title = _normalize_keyword_text(payload.get("original_title") or payload.get("original_name"))
        date_like = payload.get("release_date") or payload.get("release")
    year = _extract_year_from_date_like(date_like)
    return {
        "expected_title": title,
        "expected_original_title": original_title,
        "expected_year": year,
    }


def _build_pansou_keyword_from_media(payload: dict, media_type: str) -> str:
    if not isinstance(payload, dict):
        return ""
    # Keep compatibility for callers that only need a single preferred keyword.
    candidates = _build_pansou_keyword_candidates(payload, media_type, tmdb_id=0)
    for keyword in candidates:
        if keyword != "TMDB 0":
            return keyword
    return ""


def _normalize_pansou_pan115_list(payload: Any) -> list[dict]:
    rows = _extract_pansou_rows(payload)
    items: list[dict] = []
    seen_links: set[str] = set()

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        share_link = _extract_pansou_share_link(row)
        if not _is_likely_115_share_identifier(share_link):
            continue

        # 基于 share_link 去重，避免同一个分享链接出现多次
        link_key = share_link.strip().lower()
        if link_key in seen_links:
            continue
        seen_links.add(link_key)

        title = _extract_first_string_value(
            row,
            ["title", "name", "resource_name", "file_name", "filename", "text"],
        )
        if not title or title == "盘搜资源":
            # 尝试从 share_link 中提取更有意义的标题
            title = f"115资源 #{len(items) + 1}"

        size = _extract_first_string_value(row, ["size"])
        resolution = _extract_first_string_value(row, ["resolution"])
        quality = _extract_first_string_value(row, ["quality"])

        resource_id = row.get("id")
        if resource_id is None:
            resource_id = f"pansou-pan115-{hashlib.md5(link_key.encode('utf-8')).hexdigest()[:12]}-{index}"

        items.append(
            {
                "id": resource_id,
                "title": title,
                "size": size,
                "resolution": resolution,
                "quality": quality,
                "share_link": share_link,
                "source_service": "pansou",
                "raw_item": row,
            }
        )

    return items


def _mark_nullbr_pan115_source(items: list[dict]) -> list[dict]:
    marked: list[dict] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["source_service"] = item.get("source_service") or "nullbr"
        marked.append(item)
    return marked


def _mark_hdhive_pan115_source(items: list[dict]) -> list[dict]:
    marked: list[dict] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["source_service"] = item.get("source_service") or "hdhive"
        marked.append(item)
    return marked


def _mark_tg_pan115_source(items: list[dict]) -> list[dict]:
    marked: list[dict] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["source_service"] = item.get("source_service") or "tg"
        marked.append(item)
    return marked


def _is_allowed_image_proxy_url(raw_url: str) -> bool:
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False

    if host == "doubanio.com" or host.endswith(".doubanio.com"):
        return True
    if host == "image.tmdb.org":
        return True
    return False


def _normalize_image_proxy_size(raw_size: str | None) -> str:
    normalized = str(raw_size or "").strip().lower()
    if normalized in {"small", "medium", "large"}:
        return normalized
    return "medium"


def _rewrite_tmdb_poster_size(raw_url: str, size: str) -> str:
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return raw_url

    host = (parsed.hostname or "").lower()
    if host != "image.tmdb.org":
        return raw_url

    target_size = {
        "small": "w342",
        "medium": "w500",
        "large": "w780",
    }.get(size, "w500")

    rewritten_path = re.sub(r"^/t/p/[^/]+/", f"/t/p/{target_size}/", parsed.path)
    if rewritten_path == parsed.path:
        return raw_url

    base = f"{parsed.scheme or 'https'}://image.tmdb.org{rewritten_path}"
    if parsed.query:
        return f"{base}?{parsed.query}"
    return base


async def _get_cached_proxy_image(cache_key: str) -> tuple[bytes, str] | None:
    now = time.time()
    async with _image_proxy_cache_lock:
        cached = _image_proxy_cache.get(cache_key)
        if not cached:
            return None
        expires_at, content, content_type = cached
        if expires_at <= now:
            _image_proxy_cache.pop(cache_key, None)
            return None
        _image_proxy_cache.move_to_end(cache_key)
        return content, content_type


async def _set_cached_proxy_image(cache_key: str, content: bytes, content_type: str) -> None:
    async with _image_proxy_cache_lock:
        _image_proxy_cache[cache_key] = (time.time() + IMAGE_PROXY_CACHE_TTL_SECONDS, content, content_type)
        _image_proxy_cache.move_to_end(cache_key)
        while len(_image_proxy_cache) > IMAGE_PROXY_CACHE_MAX_ITEMS:
            _image_proxy_cache.popitem(last=False)


def _normalize_popular_items(raw_items):
    if not isinstance(raw_items, list):
        raise ValueError("invalid popular movies response format")

    items = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue

        tmdb_id = item.get("tmdb_id")
        movie_id = tmdb_id or item.get("id")
        if not movie_id:
            continue

        genres = item.get("genres") or []
        if not isinstance(genres, list):
            genres = []
        intro = " / ".join(genres[:3]) if genres else "热门电影推荐"

        poster_url = item.get("poster_url") or ""
        if isinstance(poster_url, str) and poster_url.startswith("http://"):
            poster_url = poster_url.replace("http://", "https://", 1)

        items.append(
            {
                "rank": index + 1,
                "id": movie_id,
                "tmdb_id": tmdb_id,
                "media_type": "movie",
                "title": item.get("title") or "",
                "year": item.get("year"),
                "poster_url": poster_url,
                "imdb_id": item.get("imdb_id"),
                "intro": intro,
                "genres": genres,
            }
        )
    return items


def _get_cached_payload(cache: dict, key: str):
    cache_item = cache.get(key)
    if not cache_item:
        return None, False
    payload = cache_item.get("payload")
    expires_at = cache_item.get("expires_at", 0.0)
    is_fresh = time.time() < expires_at
    return payload, is_fresh


def _set_cached_payload(cache: dict, key: str, payload: dict, ttl_seconds: int):
    cache[key] = {
        "payload": payload,
        "expires_at": time.time() + ttl_seconds,
    }


def _resolve_pan115_cache_ttl_seconds(resource_list: list[dict]) -> int:
    return PAN115_CACHE_TTL_SECONDS if resource_list else PAN115_EMPTY_CACHE_TTL_SECONDS


def _set_pan115_cached_payload(cache: dict, key: str, payload: dict) -> None:
    resources = payload.get("list") if isinstance(payload, dict) else []
    resource_list = resources if isinstance(resources, list) else []
    ttl_seconds = _resolve_pan115_cache_ttl_seconds(resource_list)
    _set_cached_payload(cache, key, payload, ttl_seconds)


def _find_douban_source(section_key: str):
    return next((source for source in DOUBAN_SECTION_SOURCES if source["key"] == section_key), None)


def _find_tmdb_source(section_key: str):
    return next((source for source in TMDB_SECTION_SOURCES if source["key"] == section_key), None)


async def _fetch_popular_section(source, refresh):
    key = source["key"]
    now = time.time()
    cache_item = _popular_sections_cache[key]

    if (
        not refresh
        and cache_item["payload"] is not None
        and now < cache_item["expires_at"]
    ):
        return cache_item["payload"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(source["url"])
            response.raise_for_status()
            raw_items = response.json()

        items = _normalize_popular_items(raw_items)
        payload = {
            "key": source["key"],
            "title": source["title"],
            "tag": source["tag"],
            "source_url": source["url"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "total": len(items),
            "items": items,
        }
        cache_item["payload"] = payload
        cache_item["expires_at"] = now + POPULAR_CACHE_TTL_SECONDS
        return payload
    except Exception as exc:
        if cache_item["payload"] is not None:
            return cache_item["payload"]
        raise exc


@router.get("")
async def search(
    query: str = Query(..., description="Search keyword"),
    page: int = Query(1, ge=1, description="Page number"),
):
    keyword = str(query or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="Search keyword is required")

    try:
        payload = await tmdb_service.search_multi(keyword, page)
        if not isinstance(payload, dict):
            payload = {}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        payload["emby_status_map"] = await _build_emby_status_map(items)
        return payload
    except ValueError as exc:
        if "TMDB_API_KEY is not configured" in str(exc):
            raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB 搜索失败: {str(exc)}")


@router.get("/explore/popular")
async def get_explore_popular_movies(
    limit: int = Query(30, ge=1, le=200, description="Number of items to return"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    source = POPULAR_SECTION_SOURCES[0]
    try:
        payload = await _fetch_popular_section(source, refresh)
        _popular_movies_cache["payload"] = payload
        _popular_movies_cache["expires_at"] = time.time() + POPULAR_CACHE_TTL_SECONDS
        return {
            "source": payload["source_url"],
            "fetched_at": payload["fetched_at"],
            "total": payload["total"],
            "items": payload.get("items", [])[:limit],
        }
    except Exception as exc:
        if _popular_movies_cache["payload"] is not None:
            cached_payload = _popular_movies_cache["payload"]
            return {
                "source": cached_payload.get("source_url", POPULAR_MOVIES_URL),
                "fetched_at": cached_payload.get("fetched_at"),
                "total": cached_payload.get("total", 0),
                "items": cached_payload.get("items", [])[:limit],
            }
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch recommendations: {str(exc)}",
        )


@router.get("/explore/popular-sections")
async def get_explore_popular_sections(
    limit: int = Query(24, ge=1, le=100, description="Number of items per section"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    tasks = [_fetch_popular_section(source, refresh) for source in POPULAR_SECTION_SOURCES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    sections = []
    errors = []
    for source, result in zip(POPULAR_SECTION_SOURCES, results):
        if isinstance(result, Exception):
            errors.append({"key": source["key"], "error": str(result)})
            continue
        if not isinstance(result, dict):
            errors.append({"key": source["key"], "error": "Invalid section payload"})
            continue
        sections.append(
            {
                "key": result["key"],
                "title": result["title"],
                "tag": result["tag"],
                "source_url": result["source_url"],
                "fetched_at": result["fetched_at"],
                "total": result["total"],
                "items": result.get("items", [])[:limit],
            }
        )

    if not sections:
        raise HTTPException(status_code=502, detail="Failed to fetch all recommendation sections")

    emby_status_map = await _build_emby_status_map(_collect_section_items(sections))
    return {
        "source": "popular-movies-data.stevenlu.com",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "errors": errors,
        "emby_status_map": emby_status_map,
    }


@router.get("/explore/douban-sections")
async def get_explore_douban_sections(
    limit: int = Query(24, ge=1, le=100, description="Number of items per section"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    async with httpx.AsyncClient(timeout=12.0, http2=True) as client:
        tasks = [
            fetch_douban_section(source, limit, refresh, client=client)
            for source in DOUBAN_SECTION_SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    sections = []
    errors = []
    for source, result in zip(DOUBAN_SECTION_SOURCES, results):
        if isinstance(result, Exception):
            errors.append({"key": source["key"], "error": str(result)})
            continue
        if not isinstance(result, dict):
            errors.append({"key": source["key"], "error": "Invalid section payload"})
            continue
        sections.append(
            {
                "key": result["key"],
                "title": result["title"],
                "tag": result["tag"],
                "source_url": result["source_url"],
                "fetched_at": result["fetched_at"],
                "total": result["total"],
                "items": result.get("items", [])[:limit],
            }
        )

    if not sections:
        fallback = await get_explore_popular_sections(limit=limit, refresh=refresh)
        fallback_source = fallback.get("source", "popular-movies-data.stevenlu.com")
        fallback_errors = fallback.get("errors", [])
        return {
            "source": f"fallback:{fallback_source}",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sections": fallback.get("sections", []),
            "errors": errors + fallback_errors,
            "emby_status_map": fallback.get("emby_status_map", {}),
        }

    emby_status_map = await _build_emby_status_map(_collect_section_items(sections))
    return {
        "source": "douban-frodo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "errors": errors,
        "emby_status_map": emby_status_map,
    }


@router.get("/explore/sections")
async def get_explore_sections(
    source: str = Query("douban", pattern="^(douban|tmdb)$", description="Explore source"),
    limit: int = Query(24, ge=1, le=100, description="Number of items per section"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    normalized_source = source if source in {"douban", "tmdb"} else "douban"

    if normalized_source == "tmdb":
        async with httpx.AsyncClient(timeout=12.0, http2=True) as client:
            tasks = [
                fetch_tmdb_section(section, limit, refresh, client=client)
                for section in TMDB_SECTION_SOURCES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        sections = []
        errors = []
        for section, result in zip(TMDB_SECTION_SOURCES, results):
            if isinstance(result, Exception):
                errors.append({"key": section["key"], "error": str(result)})
                continue
            if not isinstance(result, dict):
                errors.append({"key": section["key"], "error": "Invalid TMDB section payload"})
                continue
            sections.append(
                {
                    "key": result["key"],
                    "title": result["title"],
                    "tag": result["tag"],
                    "source_url": result["source_url"],
                    "fetched_at": result["fetched_at"],
                    "total": result["total"],
                    "items": result.get("items", [])[:limit],
                }
            )

        if not sections:
            if errors:
                first_error = str(errors[0].get("error") or "")
                if "TMDB_API_KEY is not configured" in first_error:
                    raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
            raise HTTPException(status_code=502, detail="Failed to fetch TMDB explore sections")

        emby_status_map = await _build_emby_status_map(_collect_section_items(sections))
        return {
            "source": "tmdb",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
            "errors": errors,
            "emby_status_map": emby_status_map,
        }

    async with httpx.AsyncClient(timeout=12.0, http2=True) as client:
        tasks = [
            fetch_douban_section(section, limit, refresh, client=client)
            for section in DOUBAN_SECTION_SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    sections = []
    errors = []
    for section, result in zip(DOUBAN_SECTION_SOURCES, results):
        if isinstance(result, Exception):
            errors.append({"key": section["key"], "error": str(result)})
            continue
        if not isinstance(result, dict):
            errors.append({"key": section["key"], "error": "Invalid Douban section payload"})
            continue
        sections.append(
            {
                "key": result["key"],
                "title": result["title"],
                "tag": result["tag"],
                "source_url": result["source_url"],
                "fetched_at": result["fetched_at"],
                "total": result["total"],
                "items": result.get("items", [])[:limit],
            }
        )

    if not sections:
        fallback = await get_explore_popular_sections(limit=limit, refresh=refresh)
        fallback_source = fallback.get("source", "popular-movies-data.stevenlu.com")
        fallback_errors = fallback.get("errors", [])
        return {
            "source": f"fallback:{fallback_source}",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sections": fallback.get("sections", []),
            "errors": errors + fallback_errors,
            "emby_status_map": fallback.get("emby_status_map", {}),
        }

    emby_status_map = await _build_emby_status_map(_collect_section_items(sections))
    return {
        "source": "douban-frodo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "errors": errors,
        "emby_status_map": emby_status_map,
    }


@router.get("/explore/meta")
async def get_explore_meta(
    source: str = Query("douban", pattern="^(douban|tmdb)$", description="Explore source"),
):
    normalized_source = source if source in {"douban", "tmdb"} else "douban"
    source_rows = TMDB_SECTION_SOURCES if normalized_source == "tmdb" else DOUBAN_SECTION_SOURCES
    return {
        "source": "tmdb" if normalized_source == "tmdb" else "douban-frodo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sections": [
            {
                "key": row["key"],
                "title": row["title"],
                "tag": row["tag"],
            }
            for row in source_rows
        ],
    }


@router.get("/explore/home")
async def get_explore_home(
    source: str = Query("douban", pattern="^(douban|tmdb)$", description="Explore source"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    normalized_source = source if source in {"douban", "tmdb"} else "douban"
    limit = EXPLORE_HOME_SECTION_LIMIT

    if normalized_source == "tmdb":
        async with httpx.AsyncClient(timeout=12.0, http2=True) as client:
            tasks = [
                fetch_tmdb_section(section, limit, refresh, client=client)
                for section in TMDB_SECTION_SOURCES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        sections = []
        errors = []
        for section, result in zip(TMDB_SECTION_SOURCES, results):
            if isinstance(result, Exception):
                errors.append({"key": section["key"], "error": str(result)})
                continue
            if not isinstance(result, dict):
                errors.append({"key": section["key"], "error": "Invalid TMDB section payload"})
                continue
            sections.append(
                {
                    "key": result["key"],
                    "title": result["title"],
                    "tag": result["tag"],
                    "source_url": result["source_url"],
                    "fetched_at": result["fetched_at"],
                    "total": result["total"],
                    "items": result.get("items", [])[:limit],
                }
            )

        if not sections:
            if errors:
                first_error = str(errors[0].get("error") or "")
                if "TMDB_API_KEY is not configured" in first_error:
                    raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
            raise HTTPException(status_code=502, detail="Failed to fetch TMDB explore home")

        emby_status_map = await _build_emby_status_map(_collect_section_items(sections))
        return {
            "source": "tmdb",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
            "errors": errors,
            "emby_status_map": emby_status_map,
        }

    async with httpx.AsyncClient(timeout=12.0, http2=True) as client:
        tasks = [
            fetch_douban_section(
                section,
                limit,
                refresh,
                client=client,
                home_prime_limit=DOUBAN_HOME_SYNC_PRIME_LIMIT,
            )
            for section in DOUBAN_SECTION_SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    sections = []
    errors = []
    for section, result in zip(DOUBAN_SECTION_SOURCES, results):
        if isinstance(result, Exception):
            errors.append({"key": section["key"], "error": str(result)})
            continue
        if not isinstance(result, dict):
            errors.append({"key": section["key"], "error": "Invalid Douban section payload"})
            continue
        sections.append(
            {
                "key": result["key"],
                "title": result["title"],
                "tag": result["tag"],
                "source_url": result["source_url"],
                "fetched_at": result["fetched_at"],
                "total": result["total"],
                "items": result.get("items", [])[:limit],
            }
        )

    if not sections:
        fallback = await get_explore_popular_sections(limit=limit, refresh=refresh)
        fallback_source = fallback.get("source", "popular-movies-data.stevenlu.com")
        fallback_errors = fallback.get("errors", [])
        return {
            "source": f"fallback:{fallback_source}",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sections": fallback.get("sections", []),
            "errors": errors + fallback_errors,
            "emby_status_map": fallback.get("emby_status_map", {}),
        }

    emby_status_map = await _build_emby_status_map(_collect_section_items(sections))
    return {
        "source": "douban-frodo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "errors": errors,
        "emby_status_map": emby_status_map,
    }


@router.post("/emby/status-map")
async def get_emby_status_map(payload: EmbyStatusMapRequest):
    items = [row.model_dump() for row in payload.items]
    return {"items": await _build_emby_status_map(items)}


@router.get("/explore/section/{section_key}")
async def get_explore_section(
    section_key: str,
    source: str = Query("douban", pattern="^(douban|tmdb)$", description="Explore source"),
    limit: int = Query(30, ge=1, le=50, description="Number of items to return per request"),
    start: int = Query(0, ge=0, le=5000, description="Start offset for batched loading"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    normalized_source = source if source in {"douban", "tmdb"} else "douban"
    home_cached = explore_home_warmup_service.get_cached_section(
        normalized_source,
        section_key,
        start,
        limit,
    )
    if home_cached is not None and not refresh:
        return {
            **home_cached,
            "cache_hit": True,
            "cache_source": "home_warmup",
        }

    if normalized_source == "tmdb":
        section = _find_tmdb_source(section_key)
        if not section:
            raise HTTPException(status_code=404, detail=f"Unknown section key: {section_key}")

        try:
            payload = await fetch_tmdb_section(section, limit, refresh, start=start)
        except Exception as exc:
            if "TMDB_API_KEY is not configured" in str(exc):
                raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
            raise HTTPException(status_code=502, detail=f"Failed to fetch section: {str(exc)}")

        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        return {
            "source": "tmdb",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "section": {
                "key": payload["key"],
                "title": payload["title"],
                "tag": payload["tag"],
                "source_url": payload["source_url"],
                "fetched_at": payload["fetched_at"],
                "total": payload["total"],
                "start": payload.get("start", start),
                "count": payload.get("count", limit),
                "items": items,
            },
            "emby_status_map": await _build_emby_status_map(items),
            "cache_hit": False,
            "cache_source": "section_runtime",
            "cache_warmed_at": None,
        }

    section = _find_douban_source(section_key)
    if not section:
        raise HTTPException(status_code=404, detail=f"Unknown section key: {section_key}")

    try:
        payload = await fetch_douban_section(section, limit, refresh, start=start)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch section: {str(exc)}")

    items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
    return {
        "source": "douban-frodo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "section": {
            "key": payload["key"],
            "title": payload["title"],
            "tag": payload["tag"],
            "source_url": payload["source_url"],
            "fetched_at": payload["fetched_at"],
            "total": payload["total"],
            "start": payload.get("start", start),
            "count": payload.get("count", limit),
            "items": items,
        },
        "emby_status_map": await _build_emby_status_map(items),
        "cache_hit": False,
        "cache_source": "section_runtime",
        "cache_warmed_at": None,
    }


@router.get("/explore/douban-section/{section_key}")
async def get_explore_douban_section(
    section_key: str,
    limit: int = Query(30, ge=1, le=50, description="Number of items to return per request"),
    start: int = Query(0, ge=0, le=5000, description="Start offset for batched loading"),
    refresh: bool = Query(False, description="Force refresh cache"),
):
    source = _find_douban_source(section_key)
    if not source:
        raise HTTPException(status_code=404, detail=f"Unknown section key: {section_key}")

    try:
        payload = await fetch_douban_section(source, limit, refresh, start=start)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch section: {str(exc)}")

    items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
    return {
        "source": "douban-frodo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "section": {
            "key": payload["key"],
            "title": payload["title"],
            "tag": payload["tag"],
            "source_url": payload["source_url"],
            "fetched_at": payload["fetched_at"],
            "total": payload["total"],
            "start": payload.get("start", start),
            "count": payload.get("count", limit),
            "items": items,
        },
        "emby_status_map": await _build_emby_status_map(items),
    }


@router.post("/explore/resolve")
async def resolve_explore_item(payload: dict[str, Any] = Body(default={})):
    source = str(payload.get("source") or "douban").strip().lower()
    media_type = str(payload.get("media_type") or "movie").strip().lower()
    if media_type not in {"movie", "tv"}:
        media_type = "movie"

    raw_tmdb_id = payload.get("tmdb_id")
    tmdb_id: Optional[int] = None
    if raw_tmdb_id is not None and str(raw_tmdb_id).strip():
        try:
            parsed_tmdb_id = int(raw_tmdb_id)
            if parsed_tmdb_id > 0:
                tmdb_id = parsed_tmdb_id
        except Exception:
            tmdb_id = None

    if source == "tmdb":
        if not tmdb_id:
            return {
                "resolved": False,
                "media_type": media_type,
                "tmdb_id": None,
                "confidence": 0.0,
                "reason": "missing_tmdb_id",
                "candidates": [],
            }
        return {
            "resolved": True,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "confidence": 1.0,
            "reason": "provided_tmdb_id",
            "candidates": [],
        }

    title = str(payload.get("title") or payload.get("name") or "").strip()
    original_title = str(payload.get("original_title") or payload.get("original_name") or "").strip()
    aliases_payload = payload.get("aliases")
    aliases: list[str] = []
    if isinstance(aliases_payload, list):
        aliases = [str(item or "").strip() for item in aliases_payload if str(item or "").strip()]
    elif isinstance(aliases_payload, str) and aliases_payload.strip():
        aliases = [aliases_payload.strip()]
    year_value = str(payload.get("year") or "").strip()[:4]
    if year_value and not year_value.isdigit():
        year_value = ""
    year = year_value or None
    douban_id = str(payload.get("douban_id") or payload.get("id") or "").strip()

    result = await resolve_douban_explore_item(
        douban_id=douban_id,
        title=title,
        media_type=media_type,
        year=year,
        tmdb_id=tmdb_id,
        alternative_titles=[original_title, *aliases],
    )
    result["source"] = "douban"
    result["douban_id"] = douban_id
    return result


@router.post("/explore/queue/subscribe")
async def enqueue_explore_subscribe_task(payload: ExploreQueueSubscribeRequest):
    task = await explore_action_queue_service.enqueue_subscribe(
        payload.model_dump(),
        payload.intent,
    )
    return task


@router.post("/explore/queue/save")
async def enqueue_explore_save_task(payload: ExploreQueueBaseRequest):
    task = await explore_action_queue_service.enqueue_save(payload.model_dump())
    return task


@router.get("/explore/queue/tasks/{task_id}")
async def get_explore_queue_task(task_id: str):
    task = await explore_action_queue_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/explore/queue/active")
async def get_explore_queue_active_tasks(
    queue_type: str = Query("all", pattern="^(all|subscribe|save)$"),
):
    return await explore_action_queue_service.list_active(queue_type)


@router.get("/douban/subject/{douban_id}")
async def get_douban_subject_detail(
    douban_id: str,
    media_type: str = Query("movie", description="movie|tv"),
):
    normalized_type = "tv" if str(media_type or "").strip().lower() == "tv" else "movie"
    try:
        detail = await fetch_douban_subject_detail(douban_id=douban_id, media_type=normalized_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch douban subject: {str(exc)}")
    return detail


@router.get("/explore/poster")
async def proxy_explore_poster(
    url: str = Query(..., description="Poster image url"),
    size: str = Query("medium", description="Poster size: small|medium|large"),
):
    if not _is_allowed_image_proxy_url(url):
        raise HTTPException(status_code=400, detail="Poster url is not allowed")

    normalized_size = _normalize_image_proxy_size(size)
    effective_url = _rewrite_tmdb_poster_size(url, normalized_size)
    cache_key = f"{normalized_size}:{effective_url}"

    cached = await _get_cached_proxy_image(cache_key)
    if cached:
        content, content_type = cached
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=604800",
                "X-Poster-Cache": "HIT",
            },
        )

    parsed = urlparse(effective_url)
    host = (parsed.hostname or "").lower()

    headers = {
        "User-Agent": _image_proxy_user_agent,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if host == "doubanio.com" or host.endswith(".doubanio.com"):
        headers["Referer"] = "https://m.douban.com/"
        headers["Origin"] = "https://m.douban.com"

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            image_resp = await client.get(effective_url, headers=headers)
            image_resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch poster: {str(exc)}")

    content_type = image_resp.headers.get("content-type", "image/jpeg")
    await _set_cached_proxy_image(cache_key, image_resp.content, content_type)
    return Response(
        content=image_resp.content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=604800",
            "X-Poster-Cache": "MISS",
        },
    )


@router.get("/list/{list_id}")
def get_list(
    list_id: int,
    page: int = Query(1, ge=1, description="Page number"),
):
    result = nullbr_service.get_list(list_id, page)
    return result


@router.get("/movie/{tmdb_id}")
async def get_movie(tmdb_id: int):
    try:
        return await tmdb_service.get_movie_detail(tmdb_id)
    except ValueError as exc:
        if "TMDB_API_KEY is not configured" in str(exc):
            raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        if status == 404:
            raise HTTPException(status_code=404, detail="影视不存在")
        raise HTTPException(status_code=502, detail=f"TMDB 详情获取失败({status})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB 详情获取失败: {str(exc)}")


def _build_pan115_response(
    tmdb_id: int,
    media_type: str,
    page: int,
    resource_list: list[dict],
    search_service: str,
    source_counts: Optional[dict[str, int]] = None,
    attempts: Optional[list[dict[str, Any]]] = None,
    keyword: str = "",
    attempted_keywords: Optional[list[str]] = None,
    keyword_hit_index: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "id": tmdb_id,
        "media_type": media_type,
        "page": page,
        "total_page": 1,
        "list": resource_list,
        "resource_order": [search_service],
        "search_service": search_service,
        "source_counts": source_counts or {},
        "attempts": attempts or [],
        "keyword": keyword,
        "attempted_keywords": attempted_keywords or [],
        "keyword_hit_index": keyword_hit_index,
    }


def _resource_fallback_payload(
    *,
    tmdb_id: int,
    media_type: str,
    error: str,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": tmdb_id,
        "media_type": media_type,
        "list": [],
        "error": error,
    }
    if season_number is not None:
        payload["season_number"] = season_number
    if episode_number is not None:
        payload["episode_number"] = episode_number
    if media_type == "tv" and episode_number is not None:
        payload["tv_show_id"] = tmdb_id
    return payload


def _call_nullbr_resource(fetcher, fallback_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = fetcher()
        if isinstance(result, dict):
            result.setdefault("list", [])
            return result
        fallback_payload["error"] = "上游资源返回格式异常"
        return fallback_payload
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else None
        message = f"Nullbr资源接口异常({status})" if status else "Nullbr资源接口异常"
        logger.warning("Nullbr resource request failed: %s", str(exc))
        fallback_payload["error"] = message
        return fallback_payload
    except Exception as exc:
        logger.warning("Nullbr resource request failed: %s", str(exc))
        fallback_payload["error"] = f"资源获取失败: {str(exc)}"
        return fallback_payload


def _normalize_keyword_fingerprint(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-_:：·•.,，。!！?？'\"“”‘’()（）\[\]【】/\\]+", "", text)


def _pick_nullbr_tmdb_candidates(keyword: str, media_type: str, max_candidates: int = 8) -> list[int]:
    normalized_media_type = "tv" if media_type == "tv" else "movie"
    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        return []

    try:
        payload = nullbr_service.search(normalized_keyword, 1)
    except Exception:
        return []

    rows = payload.get("items") or payload.get("results") or []
    if not isinstance(rows, list):
        return []

    keyword_fp = _normalize_keyword_fingerprint(normalized_keyword)
    scored: list[tuple[int, float]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_media_type = str(row.get("media_type") or "").strip().lower()
        if row_media_type != normalized_media_type:
            continue
        raw_tmdb_id = row.get("tmdbid") or row.get("tmdb_id") or row.get("id")
        try:
            tmdb_id = int(raw_tmdb_id)
        except Exception:
            continue
        if tmdb_id <= 0 or tmdb_id in seen:
            continue
        seen.add(tmdb_id)

        title = str(row.get("title") or row.get("name") or "").strip()
        title_fp = _normalize_keyword_fingerprint(title)
        score = 0.0
        if keyword_fp and title_fp:
            if keyword_fp == title_fp:
                score = 1.0
            elif keyword_fp in title_fp or title_fp in keyword_fp:
                score = 0.9
            else:
                overlap = len(set(keyword_fp) & set(title_fp))
                score = overlap / max(len(set(keyword_fp)), 1)
        scored.append((tmdb_id, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return [tmdb_id for tmdb_id, _ in scored[:max_candidates]]


def _build_keyword_resource_payload(
    *,
    keyword: str,
    media_type: str,
    resource_list: list[dict],
    search_service: str,
    attempts: list[dict[str, Any]],
    matched_tmdb_id: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "keyword": str(keyword or "").strip(),
        "media_type": "tv" if media_type == "tv" else "movie",
        "matched_tmdb_id": matched_tmdb_id,
        "list": resource_list,
        "search_service": search_service,
        "attempts": attempts,
    }


async def _search_nullbr_resource_by_keyword(
    *,
    keyword: str,
    media_type: str,
    resource_kind: str,
    page: int = 1,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> dict[str, Any]:
    normalized_keyword = str(keyword or "").strip()
    normalized_media_type = "tv" if media_type == "tv" else "movie"
    attempts: list[dict[str, Any]] = []
    if not normalized_keyword:
        return _build_keyword_resource_payload(
            keyword=normalized_keyword,
            media_type=normalized_media_type,
            resource_list=[],
            search_service="nullbr",
            attempts=attempts,
        )

    candidate_tmdb_ids = await asyncio.to_thread(
        _pick_nullbr_tmdb_candidates,
        normalized_keyword,
        normalized_media_type,
    )
    if not candidate_tmdb_ids:
        attempts.append({"service": "nullbr-search", "status": "empty", "keyword": normalized_keyword})
        return _build_keyword_resource_payload(
            keyword=normalized_keyword,
            media_type=normalized_media_type,
            resource_list=[],
            search_service="nullbr",
            attempts=attempts,
        )

    for candidate_tmdb_id in candidate_tmdb_ids:
        attempts.append({"service": "nullbr-search", "status": "candidate", "tmdb_id": candidate_tmdb_id})
        fallback = _resource_fallback_payload(
            tmdb_id=candidate_tmdb_id,
            media_type=normalized_media_type,
            season_number=season,
            episode_number=episode,
            error="",
        )

        def fetcher():
            if resource_kind == "pan115":
                if normalized_media_type == "tv":
                    return nullbr_service.get_tv_pan115(candidate_tmdb_id, page)
                return nullbr_service.get_movie_pan115(candidate_tmdb_id, page)
            if resource_kind == "magnet":
                if normalized_media_type == "tv":
                    return nullbr_service.get_tv_magnet(candidate_tmdb_id, season, episode)
                return nullbr_service.get_movie_magnet(candidate_tmdb_id)
            if resource_kind == "ed2k":
                if normalized_media_type == "tv":
                    return nullbr_service.get_tv_ed2k(candidate_tmdb_id, season, episode)
                return nullbr_service.get_movie_ed2k(candidate_tmdb_id)
            raise ValueError(f"unsupported resource kind: {resource_kind}")

        result = await asyncio.to_thread(_call_nullbr_resource, fetcher, fallback)
        resource_list = list(result.get("list") or []) if isinstance(result, dict) else []
        if resource_list:
            attempts.append(
                {
                    "service": "nullbr",
                    "status": "ok",
                    "tmdb_id": candidate_tmdb_id,
                    "count": len(resource_list),
                }
            )
            return _build_keyword_resource_payload(
                keyword=normalized_keyword,
                media_type=normalized_media_type,
                resource_list=resource_list,
                search_service="nullbr",
                attempts=attempts,
                matched_tmdb_id=candidate_tmdb_id,
            )

        attempts.append({"service": "nullbr", "status": "empty", "tmdb_id": candidate_tmdb_id})

    return _build_keyword_resource_payload(
        keyword=normalized_keyword,
        media_type=normalized_media_type,
        resource_list=[],
        search_service="nullbr",
        attempts=attempts,
    )


async def _load_media_payload(tmdb_id: int, media_type: str) -> dict:
    try:
        if media_type == "tv":
            payload = await tmdb_service.get_tv_detail(tmdb_id)
        else:
            payload = await tmdb_service.get_movie_detail(tmdb_id)
    except ValueError:
        return {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _search_pansou_pan115_resources(tmdb_id: int, media_type: str) -> dict[str, Any]:
    pansou_service.set_base_url(runtime_settings_service.get_pansou_base_url())
    media_payload = await _load_media_payload(tmdb_id, media_type)

    keyword_candidates = _build_pansou_keyword_candidates(media_payload, media_type, tmdb_id)
    selected_keyword = keyword_candidates[0] if keyword_candidates else f"TMDB {tmdb_id}"
    attempted_keywords: list[str] = []
    attempts: list[dict[str, Any]] = []

    for keyword in keyword_candidates:
        attempted_keywords.append(keyword)
        try:
            pansou_payload = await pansou_service.search_115(keyword, res="results")
            pansou_list = _normalize_pansou_pan115_list(pansou_payload)
            attempts.append({"service": "pansou", "keyword": keyword, "status": "ok", "count": len(pansou_list)})
            if pansou_list:
                return {
                    "keyword": keyword,
                    "list": pansou_list,
                    "attempted_keywords": attempted_keywords,
                    "keyword_hit_index": len(attempted_keywords) - 1,
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append({"service": "pansou", "keyword": keyword, "status": "error", "error": str(exc)})

    return {
        "keyword": selected_keyword,
        "list": [],
        "attempted_keywords": attempted_keywords,
        "keyword_hit_index": None,
        "attempts": attempts,
    }


async def _search_tg_pan115_resources(tmdb_id: int, media_type: str) -> dict[str, Any]:
    media_payload = await _load_media_payload(tmdb_id, media_type)
    keyword_candidates = _build_tg_keyword_candidates(media_payload, media_type, tmdb_id)
    context = _extract_tg_expected_context(media_payload, media_type)
    selected_keyword = keyword_candidates[0] if keyword_candidates else f"TMDB {tmdb_id}"
    attempted_keywords: list[str] = []
    attempts: list[dict[str, Any]] = []

    for keyword in keyword_candidates:
        attempted_keywords.append(keyword)
        try:
            tg_list = await tg_service.search_115_by_keyword(
                keyword,
                media_type=media_type,
                expected_title=context.get("expected_title", ""),
                expected_original_title=context.get("expected_original_title", ""),
                expected_year=context.get("expected_year", ""),
            )
            tg_list = _mark_tg_pan115_source(tg_list)
            attempts.append(
                {
                    "service": "tg",
                    "keyword": keyword,
                    "status": "ok",
                    "count": len(tg_list),
                    "raw_count": len(tg_list),
                    "filtered_count": len(tg_list),
                    "rejected_by_precision": 0,
                }
            )
            if tg_list:
                return {
                    "keyword": keyword,
                    "list": tg_list,
                    "attempted_keywords": attempted_keywords,
                    "keyword_hit_index": len(attempted_keywords) - 1,
                    "attempts": attempts,
                }
        except Exception as exc:
            attempts.append({"service": "tg", "keyword": keyword, "status": "error", "error": str(exc)})
    return {
        "keyword": selected_keyword,
        "list": [],
        "attempted_keywords": attempted_keywords,
        "keyword_hit_index": None,
        "attempts": attempts,
    }


async def _search_seedhub_magnet_resources(tmdb_id: int, media_type: str) -> tuple[str, list[dict]]:
    media_payload = await _load_media_payload(tmdb_id, media_type)
    keyword_candidates = _build_pansou_keyword_candidates(media_payload, media_type, tmdb_id)
    selected_keyword = keyword_candidates[0] if keyword_candidates else f"TMDB {tmdb_id}"

    for keyword in keyword_candidates:
        items = await seedhub_service.search_magnets_by_keyword(keyword, limit=40)
        if items:
            return keyword, items
    return selected_keyword, []


def _serialize_seedhub_task(task: dict[str, Any]) -> dict[str, Any]:
    items = list(task.get("items") or [])
    return {
        "task_id": str(task.get("task_id") or ""),
        "status": str(task.get("status") or "queued"),
        "message": str(task.get("message") or ""),
        "media_type": str(task.get("media_type") or ""),
        "tmdb_id": task.get("tmdb_id"),
        "keyword": str(task.get("keyword") or ""),
        "progress": {
            "total_candidates": int(task.get("total_candidates") or 0),
            "resolved_count": int(task.get("resolved_count") or 0),
            "success_count": int(task.get("success_count") or 0),
            "failed_count": int(task.get("failed_count") or 0),
        },
        "items": items,
        "error": task.get("error"),
        "started_at": task.get("started_at"),
        "updated_at": task.get("updated_at"),
        "finished_at": task.get("finished_at"),
        "already_running": bool(task.get("already_running")),
    }


@router.post("/{media_type}/{tmdb_id}/magnet/seedhub/tasks")
async def create_seedhub_magnet_task(
    media_type: str,
    tmdb_id: int,
    limit: int = Query(40, ge=1, le=80, description="结果上限"),
    force_refresh: bool = Query(False, description="是否绕过缓存"),
):
    normalized_media_type = str(media_type or "").strip().lower()
    if normalized_media_type not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type must be movie or tv")

    media_payload = await _load_media_payload(tmdb_id, normalized_media_type)
    keyword_candidates = _build_pansou_keyword_candidates(media_payload, normalized_media_type, tmdb_id)

    task = await seedhub_task_service.start(
        media_type=normalized_media_type,
        tmdb_id=tmdb_id,
        keyword_candidates=keyword_candidates,
        limit=limit,
        force_refresh=force_refresh,
    )
    return _serialize_seedhub_task(task)


@router.get("/magnet/seedhub/tasks/{task_id}")
async def get_seedhub_magnet_task(task_id: str):
    task = await seedhub_task_service.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return _serialize_seedhub_task(task)


@router.delete("/magnet/seedhub/tasks/{task_id}")
async def cancel_seedhub_magnet_task(task_id: str):
    task = await seedhub_task_service.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return _serialize_seedhub_task(task)


@router.get("/movie/{tmdb_id}/115")
async def get_movie_pan115(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:nullbr"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_movie_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    attempts: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    nullbr_list: list[dict] = []

    try:
        nullbr_payload = await asyncio.to_thread(nullbr_service.get_movie_pan115, tmdb_id, page)
        nullbr_list = _mark_nullbr_pan115_source(
            list(nullbr_payload.get("list", [])) if isinstance(nullbr_payload, dict) else []
        )
        attempts.append({"service": "nullbr", "status": "ok", "count": len(nullbr_list)})
        if nullbr_list:
            source_counts["nullbr"] = len(nullbr_list)
    except Exception as exc:
        attempts.append({"service": "nullbr", "status": "error", "error": str(exc)})

    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="movie",
        page=page,
        resource_list=nullbr_list,
        search_service="nullbr",
        source_counts=source_counts,
        attempts=attempts,
    )
    result["can_try_pansou"] = True

    _set_pan115_cached_payload(_movie_pan115_cache, cache_key, result)
    return result


@router.get("/movie/{tmdb_id}/115/pansou")
async def get_movie_pan115_with_pansou(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:pansou"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_movie_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    search_result = await _search_pansou_pan115_resources(tmdb_id, "movie")
    pansou_list: list[dict] = list(search_result.get("list") or [])
    pansou_keyword = str(search_result.get("keyword") or "")
    attempts = list(search_result.get("attempts") or [])
    attempted_keywords = list(search_result.get("attempted_keywords") or [])
    keyword_hit_index = search_result.get("keyword_hit_index")

    source_counts = {"pansou": len(pansou_list)} if pansou_list else {}
    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="movie",
        page=page,
        resource_list=pansou_list,
        search_service="pansou",
        source_counts=source_counts,
        attempts=attempts,
        keyword=pansou_keyword,
        attempted_keywords=attempted_keywords,
        keyword_hit_index=keyword_hit_index,
    )

    _set_pan115_cached_payload(_movie_pan115_cache, cache_key, result)
    return result


@router.get("/movie/{tmdb_id}/115/hdhive")
async def get_movie_pan115_with_hdhive(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:hdhive"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_movie_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    attempts: list[dict[str, Any]] = []
    hdhive_list: list[dict] = []

    try:
        hdhive_list = _mark_hdhive_pan115_source(await hdhive_service.get_movie_pan115(tmdb_id))
        attempts.append({"service": "hdhive", "status": "ok", "count": len(hdhive_list)})
    except Exception as exc:
        attempts.append({"service": "hdhive", "status": "error", "error": str(exc)})

    source_counts = {"hdhive": len(hdhive_list)} if hdhive_list else {}
    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="movie",
        page=page,
        resource_list=hdhive_list,
        search_service="hdhive",
        source_counts=source_counts,
        attempts=attempts,
    )
    _set_pan115_cached_payload(_movie_pan115_cache, cache_key, result)
    return result


@router.get("/movie/{tmdb_id}/115/tg")
async def get_movie_pan115_with_tg(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:tg"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_movie_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    search_result = await _search_tg_pan115_resources(tmdb_id, "movie")
    tg_list: list[dict] = list(search_result.get("list") or [])
    tg_keyword = str(search_result.get("keyword") or "")
    attempts = list(search_result.get("attempts") or [])
    attempted_keywords = list(search_result.get("attempted_keywords") or [])
    keyword_hit_index = search_result.get("keyword_hit_index")

    source_counts = {"tg": len(tg_list)} if tg_list else {}
    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="movie",
        page=page,
        resource_list=tg_list,
        search_service="tg",
        source_counts=source_counts,
        attempts=attempts,
        keyword=tg_keyword,
        attempted_keywords=attempted_keywords,
        keyword_hit_index=keyword_hit_index,
    )
    _set_pan115_cached_payload(_movie_pan115_cache, cache_key, result)
    return result


@router.get("/movie/{tmdb_id}/magnet")
async def get_movie_magnet(
    tmdb_id: int,
    source: str = Query("nullbr", pattern="^(nullbr|seedhub)$", description="Magnet source"),
):
    if source == "seedhub":
        keyword, items = await _search_seedhub_magnet_resources(tmdb_id, "movie")
        return {
            "id": tmdb_id,
            "media_type": "movie",
            "list": items,
            "attempts": [{"service": "seedhub", "status": "ok", "count": len(items), "keyword": keyword}],
            "keyword": keyword,
            "search_service": "seedhub",
        }

    fallback = _resource_fallback_payload(tmdb_id=tmdb_id, media_type="movie", error="")
    return _call_nullbr_resource(lambda: nullbr_service.get_movie_magnet(tmdb_id), fallback)


@router.get("/movie/{tmdb_id}/magnet/seedhub")
async def get_movie_magnet_seedhub(tmdb_id: int):
    attempts: list[dict[str, Any]] = []
    keyword = ""
    items: list[dict] = []

    try:
        keyword, items = await _search_seedhub_magnet_resources(tmdb_id, "movie")
        attempts.append({"service": "seedhub", "status": "ok", "count": len(items), "keyword": keyword})
    except Exception as exc:
        attempts.append({"service": "seedhub", "status": "error", "error": str(exc)})

    return {
        "id": tmdb_id,
        "media_type": "movie",
        "list": items,
        "attempts": attempts,
        "keyword": keyword,
        "search_service": "seedhub",
    }


@router.get("/movie/{tmdb_id}/ed2k")
def get_movie_ed2k(tmdb_id: int):
    fallback = _resource_fallback_payload(tmdb_id=tmdb_id, media_type="movie", error="")
    return _call_nullbr_resource(lambda: nullbr_service.get_movie_ed2k(tmdb_id), fallback)


@router.get("/movie/{tmdb_id}/video")
def get_movie_video(tmdb_id: int):
    fallback = _resource_fallback_payload(tmdb_id=tmdb_id, media_type="movie", error="")
    return _call_nullbr_resource(lambda: nullbr_service.get_movie_video(tmdb_id), fallback)


@router.get("/tv/{tmdb_id}")
async def get_tv(tmdb_id: int):
    try:
        return await tmdb_service.get_tv_detail(tmdb_id)
    except ValueError as exc:
        if "TMDB_API_KEY is not configured" in str(exc):
            raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        if status == 404:
            raise HTTPException(status_code=404, detail="影视不存在")
        raise HTTPException(status_code=502, detail=f"TMDB 详情获取失败({status})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB 详情获取失败: {str(exc)}")


@router.get("/tv/{tmdb_id}/115")
async def get_tv_pan115(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:nullbr"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_tv_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    attempts: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    nullbr_list: list[dict] = []

    try:
        nullbr_payload = await asyncio.to_thread(nullbr_service.get_tv_pan115, tmdb_id, page)
        nullbr_list = _mark_nullbr_pan115_source(
            list(nullbr_payload.get("list", [])) if isinstance(nullbr_payload, dict) else []
        )
        attempts.append({"service": "nullbr", "status": "ok", "count": len(nullbr_list)})
        if nullbr_list:
            source_counts["nullbr"] = len(nullbr_list)
    except Exception as exc:
        attempts.append({"service": "nullbr", "status": "error", "error": str(exc)})

    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="tv",
        page=page,
        resource_list=nullbr_list,
        search_service="nullbr",
        source_counts=source_counts,
        attempts=attempts,
    )
    result["can_try_pansou"] = True

    _set_pan115_cached_payload(_tv_pan115_cache, cache_key, result)
    return result


@router.get("/tv/{tmdb_id}/115/pansou")
async def get_tv_pan115_with_pansou(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:pansou"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_tv_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    search_result = await _search_pansou_pan115_resources(tmdb_id, "tv")
    pansou_list: list[dict] = list(search_result.get("list") or [])
    pansou_keyword = str(search_result.get("keyword") or "")
    attempts = list(search_result.get("attempts") or [])
    attempted_keywords = list(search_result.get("attempted_keywords") or [])
    keyword_hit_index = search_result.get("keyword_hit_index")

    source_counts = {"pansou": len(pansou_list)} if pansou_list else {}
    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="tv",
        page=page,
        resource_list=pansou_list,
        search_service="pansou",
        source_counts=source_counts,
        attempts=attempts,
        keyword=pansou_keyword,
        attempted_keywords=attempted_keywords,
        keyword_hit_index=keyword_hit_index,
    )

    _set_pan115_cached_payload(_tv_pan115_cache, cache_key, result)
    return result


@router.get("/tv/{tmdb_id}/115/hdhive")
async def get_tv_pan115_with_hdhive(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:hdhive"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_tv_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    attempts: list[dict[str, Any]] = []
    hdhive_list: list[dict] = []

    try:
        hdhive_list = _mark_hdhive_pan115_source(await hdhive_service.get_tv_pan115(tmdb_id))
        attempts.append({"service": "hdhive", "status": "ok", "count": len(hdhive_list)})
    except Exception as exc:
        attempts.append({"service": "hdhive", "status": "error", "error": str(exc)})

    source_counts = {"hdhive": len(hdhive_list)} if hdhive_list else {}
    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="tv",
        page=page,
        resource_list=hdhive_list,
        search_service="hdhive",
        source_counts=source_counts,
        attempts=attempts,
    )
    _set_pan115_cached_payload(_tv_pan115_cache, cache_key, result)
    return result


@router.get("/tv/{tmdb_id}/115/tg")
async def get_tv_pan115_with_tg(
    tmdb_id: int,
    page: int = Query(1, ge=1),
    refresh: bool = Query(False, description="是否绕过缓存"),
):
    cache_key = f"{tmdb_id}:{page}:tg"
    if not refresh:
        cached_payload, is_fresh = _get_cached_payload(_tv_pan115_cache, cache_key)
        if is_fresh:
            return cached_payload

    search_result = await _search_tg_pan115_resources(tmdb_id, "tv")
    tg_list: list[dict] = list(search_result.get("list") or [])
    tg_keyword = str(search_result.get("keyword") or "")
    attempts = list(search_result.get("attempts") or [])
    attempted_keywords = list(search_result.get("attempted_keywords") or [])
    keyword_hit_index = search_result.get("keyword_hit_index")

    source_counts = {"tg": len(tg_list)} if tg_list else {}
    result = _build_pan115_response(
        tmdb_id=tmdb_id,
        media_type="tv",
        page=page,
        resource_list=tg_list,
        search_service="tg",
        source_counts=source_counts,
        attempts=attempts,
        keyword=tg_keyword,
        attempted_keywords=attempted_keywords,
        keyword_hit_index=keyword_hit_index,
    )
    _set_pan115_cached_payload(_tv_pan115_cache, cache_key, result)
    return result


@router.get("/hdhive/115/by-keyword")
async def get_hdhive_pan115_by_keyword(
    keyword: str = Query(..., min_length=1, description="影视名称关键词"),
    media_type: str = Query("movie", pattern="^(movie|tv)$", description="媒体类型"),
):
    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        raise HTTPException(status_code=400, detail="关键词不能为空")

    attempts: list[dict[str, Any]] = []
    hdhive_list: list[dict] = []
    try:
        hdhive_list = _mark_hdhive_pan115_source(
            await hdhive_service.get_pan115_by_keyword(normalized_keyword, media_type=media_type)
        )
        attempts.append({"service": "hdhive", "status": "ok", "count": len(hdhive_list)})
    except Exception as exc:
        attempts.append({"service": "hdhive", "status": "error", "error": str(exc)})

    return {
        "keyword": normalized_keyword,
        "media_type": media_type,
        "list": hdhive_list,
        "attempts": attempts,
        "search_service": "hdhive",
    }


@router.get("/tg/115/by-keyword")
async def get_tg_pan115_by_keyword(
    keyword: str = Query(..., min_length=1, description="影视名称关键词"),
    media_type: str = Query("movie", pattern="^(movie|tv)$", description="媒体类型"),
):
    normalized_keyword = str(keyword or "").strip()
    if not normalized_keyword:
        raise HTTPException(status_code=400, detail="关键词不能为空")

    attempts: list[dict[str, Any]] = []
    tg_list: list[dict] = []
    try:
        tg_list = _mark_tg_pan115_source(await tg_service.search_115_by_keyword(normalized_keyword, media_type=media_type))
        attempts.append({"service": "tg", "status": "ok", "count": len(tg_list)})
    except Exception as exc:
        attempts.append({"service": "tg", "status": "error", "error": str(exc)})

    return {
        "keyword": normalized_keyword,
        "media_type": media_type,
        "list": tg_list,
        "attempts": attempts,
        "search_service": "tg",
    }


@router.get("/nullbr/{media_type}/115/by-keyword")
async def get_nullbr_pan115_by_keyword(
    media_type: str,
    keyword: str = Query(..., min_length=1, description="影视名称关键词"),
    page: int = Query(1, ge=1),
):
    normalized_media_type = str(media_type or "").strip().lower()
    if normalized_media_type not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type must be movie or tv")
    return await _search_nullbr_resource_by_keyword(
        keyword=keyword,
        media_type=normalized_media_type,
        resource_kind="pan115",
        page=page,
    )


@router.get("/nullbr/{media_type}/magnet/by-keyword")
async def get_nullbr_magnet_by_keyword(
    media_type: str,
    keyword: str = Query(..., min_length=1, description="影视名称关键词"),
    season: Optional[int] = Query(None, description="Season"),
    episode: Optional[int] = Query(None, description="Episode"),
):
    normalized_media_type = str(media_type or "").strip().lower()
    if normalized_media_type not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type must be movie or tv")
    return await _search_nullbr_resource_by_keyword(
        keyword=keyword,
        media_type=normalized_media_type,
        resource_kind="magnet",
        season=season,
        episode=episode,
    )


@router.get("/nullbr/{media_type}/ed2k/by-keyword")
async def get_nullbr_ed2k_by_keyword(
    media_type: str,
    keyword: str = Query(..., min_length=1, description="影视名称关键词"),
    season: Optional[int] = Query(None, description="Season"),
    episode: Optional[int] = Query(None, description="Episode"),
):
    normalized_media_type = str(media_type or "").strip().lower()
    if normalized_media_type not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type must be movie or tv")
    return await _search_nullbr_resource_by_keyword(
        keyword=keyword,
        media_type=normalized_media_type,
        resource_kind="ed2k",
        season=season,
        episode=episode,
    )


@router.get("/seedhub/{media_type}/magnet/by-keyword")
async def get_seedhub_magnet_by_keyword(
    media_type: str,
    keyword: str = Query(..., min_length=1, description="影视名称关键词"),
):
    normalized_media_type = str(media_type or "").strip().lower()
    if normalized_media_type not in {"movie", "tv"}:
        raise HTTPException(status_code=400, detail="media_type must be movie or tv")

    normalized_keyword = str(keyword or "").strip()
    items: list[dict] = []
    attempts: list[dict[str, Any]] = []
    try:
        items = await seedhub_service.search_magnets_by_keyword(normalized_keyword, limit=40)
        attempts.append({"service": "seedhub", "status": "ok", "count": len(items), "keyword": normalized_keyword})
    except Exception as exc:
        attempts.append({"service": "seedhub", "status": "error", "error": str(exc), "keyword": normalized_keyword})
    return {
        "keyword": normalized_keyword,
        "media_type": normalized_media_type,
        "list": items,
        "attempts": attempts,
        "search_service": "seedhub",
    }


@router.post("/hdhive/resource/unlock")
async def unlock_hdhive_resource(payload: HDHiveUnlockRequest):
    slug = str(payload.slug or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="资源 slug 不能为空")

    try:
        result = await hdhive_service.unlock_resource(slug)
        return result
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        raise HTTPException(status_code=502, detail=f"HDHive 解锁失败({status})")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"HDHive 解锁失败: {str(exc)}")


@router.get("/tv/{tmdb_id}/season/{season_number}")
async def get_tv_season(tmdb_id: int, season_number: int):
    try:
        return await tmdb_service.get_tv_season_detail(tmdb_id, season_number)
    except ValueError as exc:
        if "TMDB_API_KEY is not configured" in str(exc):
            raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        if status == 404:
            raise HTTPException(status_code=404, detail="季信息不存在")
        raise HTTPException(status_code=502, detail=f"TMDB 季信息获取失败({status})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB 季信息获取失败: {str(exc)}")


@router.get("/tv/{tmdb_id}/season/{season_number}/magnet")
def get_tv_season_magnet(tmdb_id: int, season_number: int):
    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season_number,
        error="",
    )
    return _call_nullbr_resource(lambda: nullbr_service.get_tv_season_magnet(tmdb_id, season_number), fallback)


@router.get("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")
async def get_tv_episode(tmdb_id: int, season_number: int, episode_number: int):
    try:
        return await tmdb_service.get_tv_episode_detail(tmdb_id, season_number, episode_number)
    except ValueError as exc:
        if "TMDB_API_KEY is not configured" in str(exc):
            raise HTTPException(status_code=400, detail="TMDB API Key 未配置")
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        if status == 404:
            raise HTTPException(status_code=404, detail="集信息不存在")
        raise HTTPException(status_code=502, detail=f"TMDB 集信息获取失败({status})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB 集信息获取失败: {str(exc)}")


@router.get("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/magnet")
def get_tv_episode_magnet(tmdb_id: int, season_number: int, episode_number: int):
    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season_number,
        episode_number=episode_number,
        error="",
    )
    return _call_nullbr_resource(
        lambda: nullbr_service.get_tv_episode_magnet(tmdb_id, season_number, episode_number),
        fallback,
    )


@router.get("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/ed2k")
def get_tv_episode_ed2k(tmdb_id: int, season_number: int, episode_number: int):
    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season_number,
        episode_number=episode_number,
        error="",
    )
    return _call_nullbr_resource(
        lambda: nullbr_service.get_tv_episode_ed2k(tmdb_id, season_number, episode_number),
        fallback,
    )


@router.get("/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}/video")
def get_tv_episode_video(tmdb_id: int, season_number: int, episode_number: int):
    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season_number,
        episode_number=episode_number,
        error="",
    )
    return _call_nullbr_resource(
        lambda: nullbr_service.get_tv_episode_video(tmdb_id, season_number, episode_number),
        fallback,
    )


@router.get("/tv/{tmdb_id}/magnet")
async def get_tv_magnet(
    tmdb_id: int,
    season: Optional[int] = Query(None, description="Season"),
    episode: Optional[int] = Query(None, description="Episode"),
    source: str = Query("nullbr", pattern="^(nullbr|seedhub)$", description="Magnet source"),
):
    if source == "seedhub":
        keyword, items = await _search_seedhub_magnet_resources(tmdb_id, "tv")
        return {
            "id": tmdb_id,
            "media_type": "tv",
            "list": items,
            "attempts": [{"service": "seedhub", "status": "ok", "count": len(items), "keyword": keyword}],
            "keyword": keyword,
            "search_service": "seedhub",
        }

    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season,
        episode_number=episode,
        error="",
    )
    return _call_nullbr_resource(lambda: nullbr_service.get_tv_magnet(tmdb_id, season, episode), fallback)


@router.get("/tv/{tmdb_id}/magnet/seedhub")
async def get_tv_magnet_seedhub(tmdb_id: int):
    attempts: list[dict[str, Any]] = []
    keyword = ""
    items: list[dict] = []

    try:
        keyword, items = await _search_seedhub_magnet_resources(tmdb_id, "tv")
        attempts.append({"service": "seedhub", "status": "ok", "count": len(items), "keyword": keyword})
    except Exception as exc:
        attempts.append({"service": "seedhub", "status": "error", "error": str(exc)})

    return {
        "id": tmdb_id,
        "media_type": "tv",
        "list": items,
        "attempts": attempts,
        "keyword": keyword,
        "search_service": "seedhub",
    }


@router.get("/tv/{tmdb_id}/ed2k")
def get_tv_ed2k(
    tmdb_id: int,
    season: Optional[int] = Query(None, description="Season"),
    episode: Optional[int] = Query(None, description="Episode"),
):
    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season,
        episode_number=episode,
        error="",
    )
    return _call_nullbr_resource(lambda: nullbr_service.get_tv_ed2k(tmdb_id, season, episode), fallback)


@router.get("/tv/{tmdb_id}/video")
def get_tv_video(
    tmdb_id: int,
    season: Optional[int] = Query(None, description="Season"),
    episode: Optional[int] = Query(None, description="Episode"),
):
    fallback = _resource_fallback_payload(
        tmdb_id=tmdb_id,
        media_type="tv",
        season_number=season,
        episode_number=episode,
        error="",
    )
    return _call_nullbr_resource(lambda: nullbr_service.get_tv_video(tmdb_id, season, episode), fallback)


@router.get("/collection/{collection_id}")
def get_collection(collection_id: int):
    result = nullbr_service.get_collection(collection_id)
    return result


@router.get("/collection/{collection_id}/115")
def get_collection_pan115(collection_id: int, page: int = Query(1, ge=1)):
    result = nullbr_service.get_collection_pan115(collection_id, page)
    return result


@router.get("/bridge/imdb/{imdb_id}")
async def get_bridge_by_imdb_id(
    imdb_id: str,
    media_type: str = Query("movie", pattern="^(movie|tv)$", description="媒体类型: movie 或 tv"),
):
    """通过 IMDB ID 获取豆瓣和 TMDB 的关联信息

    这个接口作为桥梁，通过 IMDB ID 关联豆瓣和 TMDB 的数据：
    - 从 TMDB 查找对应的影片信息
    - 尝试从 Wikidata 查找对应的豆瓣 ID

    Args:
        imdb_id: IMDB ID，如 "tt1375666"
        media_type: 媒体类型，movie 或 tv

    Returns:
        {
            "imdb_id": "tt1375666",
            "media_type": "movie",
            "tmdb": {
                "found": True,
                "tmdb_id": 27205,
                "title": "Inception",
                "poster_path": "/...",
                ...
            },
            "douban": {
                "found": True,
                "douban_id": "3541415",
                "title": "盗梦空间",
                ...
            }
        }
    """
    normalized_imdb = str(imdb_id or "").strip().lower()
    if not normalized_imdb or not normalized_imdb.startswith("tt"):
        raise HTTPException(status_code=400, detail="无效的 IMDB ID")

    normalized_type = "tv" if media_type == "tv" else "movie"

    # 1. 从 TMDB 查找
    tmdb_result = {"found": False, "data": None}
    try:
        tmdb_find_result = await tmdb_service.find_by_imdb_id(normalized_imdb)
        if tmdb_find_result.get("found"):
            tmdb_item = tmdb_find_result.get("movie") if normalized_type == "movie" else tmdb_find_result.get("tv")
            if not tmdb_item:
                # 如果没有找到对应类型的结果，尝试使用另一个类型
                tmdb_item = tmdb_find_result.get("tv") if normalized_type == "movie" else tmdb_find_result.get("movie")

            if tmdb_item:
                tmdb_result = {
                    "found": True,
                    "tmdb_id": tmdb_item.get("tmdb_id"),
                    "title": tmdb_item.get("title") or tmdb_item.get("name"),
                    "poster_path": tmdb_item.get("poster_path"),
                    "overview": tmdb_item.get("overview"),
                    "vote_average": tmdb_item.get("vote_average"),
                    "release_date": tmdb_item.get("release_date") or tmdb_item.get("first_air_date"),
                    "media_type": tmdb_item.get("media_type"),
                }
    except Exception as exc:
        tmdb_result["error"] = str(exc)

    # 2. 尝试从 Wikidata 查找豆瓣 ID
    douban_result = {"found": False, "data": None}
    try:
        # 查询 Wikidata 获取豆瓣 ID
        query = f'''
SELECT ?doubanId WHERE {{
  ?item wdt:P345 "{normalized_imdb}" .
  OPTIONAL {{ ?item wdt:P4529 ?doubanId . }}
}}
LIMIT 1
'''.strip()

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://query.wikidata.org/sparql",
                params={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
            )
            response.raise_for_status()
            payload = response.json()
            bindings = (((payload or {}).get("results") or {}).get("bindings") or [])
            if bindings:
                douban_id = ((bindings[0].get("doubanId") or {}).get("value"))
                if douban_id:
                    douban_result = {
                        "found": True,
                        "douban_id": douban_id,
                        "source": "wikidata",
                    }
    except Exception:
        pass

    return {
        "imdb_id": normalized_imdb,
        "media_type": normalized_type,
        "tmdb": tmdb_result,
        "douban": douban_result,
    }
