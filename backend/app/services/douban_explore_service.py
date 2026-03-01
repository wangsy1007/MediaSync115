import asyncio
import base64
import difflib
import hashlib
import hmac
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.services.nullbr_service import nullbr_service
from app.services.tmdb_service import tmdb_service


DOUBAN_FRODO_BASE_URL = "https://frodo.douban.com/api/v2"
DOUBAN_API_KEY = "0dad551ec0f84ed02907ff5c42e8ec70"
DOUBAN_API_SECRET = "bf7dddc7c9cfe6f7"
DOUBAN_CACHE_TTL_SECONDS = 60 * 60 * 6
TMDB_ID_CACHE_TTL_SECONDS = 60 * 60 * 24
TMDB_ID_NEGATIVE_CACHE_TTL_SECONDS = 60 * 10
TMDB_BACKFILL_CONCURRENCY = 3
TMDB_BACKFILL_MAX_ITEMS_PER_SECTION = 12
DOUBAN_SECTION_MAX_COUNT = 50

DOUBAN_SECTION_SOURCES = [
    {
        "key": "movie_hot",
        "title": "豆瓣电影热门",
        "tag": "电影热门",
        "path": "/subject_collection/movie_hot_gaia/items",
        "media_type": "movie",
    },
    {
        "key": "movie_showing",
        "title": "豆瓣院线热映",
        "tag": "院线热映",
        "path": "/subject_collection/movie_showing/items",
        "media_type": "movie",
    },
    {
        "key": "movie_latest",
        "title": "豆瓣电影新片",
        "tag": "电影新片",
        "path": "/subject_collection/movie_latest/items",
        "media_type": "movie",
    },
    {
        "key": "movie_top250",
        "title": "豆瓣电影 Top 250",
        "tag": "Top 250",
        "path": "/subject_collection/movie_top250/items",
        "media_type": "movie",
    },
    {
        "key": "tv_hot",
        "title": "豆瓣剧集热门",
        "tag": "剧集热门",
        "path": "/subject_collection/tv_hot/items",
        "media_type": "tv",
    },
    {
        "key": "tv_variety",
        "title": "豆瓣综艺",
        "tag": "综艺",
        "path": "/subject_collection/tv_variety_show/items",
        "media_type": "tv",
    },
    {
        "key": "tv_domestic",
        "title": "豆瓣国产剧",
        "tag": "国产剧",
        "path": "/subject_collection/tv_domestic/items",
        "media_type": "tv",
    },
    {
        "key": "tv_american",
        "title": "豆瓣美剧",
        "tag": "美剧",
        "path": "/subject_collection/tv_american/items",
        "media_type": "tv",
    },
    {
        "key": "tv_animation",
        "title": "豆瓣动画",
        "tag": "动画",
        "path": "/subject_collection/tv_animation/items",
        "media_type": "tv",
    },
]

_douban_sections_cache: dict[str, dict[str, Any]] = {}
_tmdb_id_cache: dict[str, dict[str, Any]] = {}
_douban_subject_tmdb_cache: dict[str, dict[str, Any]] = {}
_tmdb_backfill_inflight: set[str] = set()

_douban_user_agents = [
    (
        "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 "
        "product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI "
        "rom/android network/wifi platform/AndroidPad"
    ),
    (
        "api-client/1 com.douban.frodo/7.18.0(230) Android/22 "
        "product/MI 9 vendor/Xiaomi model/MI 9 brand/Android "
        "rom/miui6 network/wifi platform/mobile nd/1"
    ),
]

_season_suffix_patterns = [
    re.compile(r"\s*第[一二三四五六七八九十百千零两0-9]+季\s*$", re.IGNORECASE),
    re.compile(r"\s*season\s*[0-9]{1,2}\s*$", re.IGNORECASE),
    re.compile(r"\s*s[0-9]{1,2}\s*$", re.IGNORECASE),
]


def _douban_sign(path: str, ts: str, method: str = "GET") -> str:
    raw_sign = "&".join([method.upper(), quote(path, safe=""), ts])
    digest = hmac.new(
        DOUBAN_API_SECRET.encode("utf-8"),
        raw_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _build_douban_api_headers(now: float) -> dict[str, str]:
    user_agent = _douban_user_agents[int(now) % len(_douban_user_agents)]
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://m.douban.com/",
        "Origin": "https://m.douban.com",
    }


def _normalize_poster_url(item: dict[str, Any]) -> str:
    def normalize_url(value: Any) -> str:
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

    cover = item.get("cover")
    if isinstance(cover, dict):
        cover_url = normalize_url(cover.get("url"))
        if cover_url:
            return cover_url
    elif isinstance(cover, str):
        cover_url = normalize_url(cover)
        if cover_url:
            return cover_url

    cover_url = normalize_url(item.get("cover_url"))
    if cover_url:
        return cover_url

    pic = item.get("pic")
    if isinstance(pic, dict):
        large = normalize_url(pic.get("large"))
        normal = normalize_url(pic.get("normal"))
        url = normalize_url(pic.get("url"))
        if large:
            return large
        if normal:
            return normal
        if url:
            return url

    avatar = item.get("avatar")
    if isinstance(avatar, dict):
        avatar_url = normalize_url(avatar.get("large") or avatar.get("normal") or avatar.get("url"))
        if avatar_url:
            return avatar_url

    return ""


def _extract_intro(item: dict[str, Any]) -> str:
    card_subtitle = item.get("card_subtitle")
    if isinstance(card_subtitle, str) and card_subtitle.strip():
        return card_subtitle.strip()

    info = item.get("info")
    if isinstance(info, str) and info.strip():
        return info.strip()

    description = item.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()

    return "豆瓣榜单推荐"


def _extract_year(item: dict[str, Any]) -> Optional[str]:
    year = item.get("year")
    if isinstance(year, str) and year:
        match = re.search(r"(?:19|20)\d{2}", year)
        if match:
            return match.group(0)

    # Frodo list payload often omits the dedicated year field.
    # Fall back to subtitle text like: "2001 / 日本 / ...".
    card_subtitle = item.get("card_subtitle")
    if isinstance(card_subtitle, str) and card_subtitle:
        match = re.search(r"(?:19|20)\d{2}", card_subtitle)
        if match:
            return match.group(0)

    description = item.get("description")
    if isinstance(description, str) and description:
        match = re.search(r"(?:19|20)\d{2}", description)
        if match:
            return match.group(0)

    return None


def _extract_rating(item: dict[str, Any]) -> Optional[float]:
    rating = item.get("rating")
    if not isinstance(rating, dict):
        return None
    value: Any = rating.get("value")
    if not isinstance(value, (int, float, str)):
        return None
    try:
        score = float(value)
    except Exception:
        return None
    if score <= 0:
        return None
    return score


def _extract_douban_subject_id(item: dict[str, Any]) -> str:
    value = item.get("id")
    return str(value) if value is not None else ""


def _build_douban_web_subject_url(douban_id: str, media_type: str) -> str:
    normalized_id = str(douban_id or "").strip()
    if not normalized_id:
        return ""
    normalized_type = "tv" if media_type == "tv" else "movie"
    return f"https://movie.douban.com/subject/{quote(normalized_id, safe='')}/"


def _build_tmdb_cache_key(title: str, year: Optional[str], media_type: str) -> str:
    return f"{media_type}|{title.strip().lower()}|{year or ''}"


def _build_subject_tmdb_cache_key(douban_id: str, media_type: str) -> str:
    return f"{media_type}|{str(douban_id or '').strip()}"


def _build_section_cache_key(section_key: str, start: int, count: int) -> str:
    return f"{section_key}:{start}:{count}"


def _get_cached_tmdb_id(cache_key: str) -> tuple[bool, Optional[int]]:
    cache_item = _tmdb_id_cache.get(cache_key)
    if not cache_item:
        return False, None

    expires_at = cache_item.get("expires_at", 0.0)
    if time.time() >= expires_at:
        _tmdb_id_cache.pop(cache_key, None)
        return False, None

    return True, cache_item.get("tmdb_id")


def _set_tmdb_id_cache(cache_key: str, tmdb_id: Optional[int], ttl_seconds: Optional[int] = None) -> None:
    effective_ttl = ttl_seconds
    if effective_ttl is None:
        effective_ttl = TMDB_ID_CACHE_TTL_SECONDS if tmdb_id else TMDB_ID_NEGATIVE_CACHE_TTL_SECONDS
    _tmdb_id_cache[cache_key] = {
        "tmdb_id": tmdb_id,
        "expires_at": time.time() + effective_ttl,
    }


def _get_cached_subject_tmdb_id(cache_key: str) -> tuple[bool, Optional[int]]:
    cache_item = _douban_subject_tmdb_cache.get(cache_key)
    if not cache_item:
        return False, None

    expires_at = cache_item.get("expires_at", 0.0)
    if time.time() >= expires_at:
        _douban_subject_tmdb_cache.pop(cache_key, None)
        return False, None

    return True, cache_item.get("tmdb_id")


def _set_subject_tmdb_cache(cache_key: str, tmdb_id: Optional[int], ttl_seconds: Optional[int] = None) -> None:
    effective_ttl = ttl_seconds
    if effective_ttl is None:
        effective_ttl = TMDB_ID_CACHE_TTL_SECONDS if tmdb_id else TMDB_ID_NEGATIVE_CACHE_TTL_SECONDS
    _douban_subject_tmdb_cache[cache_key] = {
        "tmdb_id": tmdb_id,
        "expires_at": time.time() + effective_ttl,
    }


def _extract_result_year(candidate: dict[str, Any]) -> Optional[str]:
    date = candidate.get("release_date") or candidate.get("first_air_date")
    if isinstance(date, str) and len(date) >= 4:
        return date[:4]
    year = candidate.get("year")
    if isinstance(year, str) and year:
        return year[:4]
    return None


def _extract_result_tmdb_id(candidate: dict[str, Any]) -> Optional[int]:
    raw_id = candidate.get("tmdbid") or candidate.get("tmdb_id") or candidate.get("id")
    if raw_id is None:
        return None
    try:
        return int(raw_id)
    except Exception:
        return None


def _normalize_compare_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\s\-_:：·•.,，。!！?？'\"“”‘’()（）\[\]【】]", "", text)
    return text


def _extract_candidate_title(candidate: dict[str, Any]) -> str:
    raw_title = candidate.get("title") or candidate.get("name")
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    return ""


def _strip_season_suffix(title: str) -> str:
    stripped = title.strip()
    if not stripped:
        return ""

    for pattern in _season_suffix_patterns:
        stripped = pattern.sub("", stripped).strip()
    return stripped


def _build_title_variants(title: str) -> list[str]:
    normalized = str(title or "").strip()
    if not normalized:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def add_variant(value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        variants.append(text)

    add_variant(normalized)
    add_variant(_strip_season_suffix(normalized))
    folded = unicodedata.normalize("NFKD", normalized)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).strip()
    add_variant(folded)
    add_variant(_strip_season_suffix(folded))
    return variants


def _title_similarity(source_title: str, candidate_title: str) -> float:
    left = _normalize_compare_text(source_title)
    right = _normalize_compare_text(candidate_title)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _score_candidate(
    candidate: dict[str, Any],
    title_variants: list[str],
    media_type: str,
    year: Optional[str],
) -> tuple[float, dict[str, Any]]:
    tmdb_id = _extract_result_tmdb_id(candidate)
    candidate_type = str(candidate.get("media_type") or "").strip().lower()
    candidate_title = _extract_candidate_title(candidate)
    candidate_year = _extract_result_year(candidate)
    best_similarity = 0.0
    best_source_title = ""
    for source_title in title_variants:
        similarity = _title_similarity(source_title, candidate_title)
        if similarity > best_similarity:
            best_similarity = similarity
            best_source_title = source_title

    meta = {
        "tmdb_id": tmdb_id,
        "media_type": candidate_type,
        "title": candidate_title,
        "year": candidate_year,
        "vote_average": float(candidate.get("vote_average") or 0.0),
        "title_similarity": round(best_similarity, 4),
        "matched_source_title": best_source_title,
    }

    if not tmdb_id:
        meta["accepted"] = False
        meta["reject_reason"] = "missing_tmdb_id"
        return 0.0, meta

    if media_type in {"movie", "tv"} and candidate_type != media_type:
        meta["accepted"] = False
        meta["reject_reason"] = "media_type_mismatch"
        return 0.0, meta

    if best_similarity < 0.88:
        meta["accepted"] = False
        meta["reject_reason"] = "low_title_similarity"
        return 0.0, meta

    year_bonus = 0.0
    if year and candidate_year:
        try:
            delta = abs(int(year) - int(candidate_year))
        except Exception:
            delta = 99
        if delta > 1:
            meta["accepted"] = False
            meta["reject_reason"] = "year_mismatch"
            return 0.0, meta
        if delta == 0:
            year_bonus = 0.2
        elif delta == 1:
            year_bonus = 0.1

    score = min(1.0, best_similarity * 0.8 + year_bonus)
    meta["accepted"] = True
    meta["score"] = round(score, 4)
    return score, meta


def _pick_best_tmdb_match(
    title: str,
    media_type: str,
    year: Optional[str],
    items: list[dict[str, Any]],
    title_variants_override: Optional[list[str]] = None,
) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
    title_variants = title_variants_override or _build_title_variants(title)
    if not title_variants:
        return None, []

    scored: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        score, meta = _score_candidate(
            row,
            title_variants=title_variants,
            media_type=media_type,
            year=year,
        )
        meta["score"] = round(score, 4)
        scored.append(meta)

    accepted = [item for item in scored if item.get("accepted")]
    # Keep one best candidate per TMDB ID to avoid duplicate rows from multi-query aggregation.
    dedup_by_tmdb: dict[int, dict[str, Any]] = {}
    for item in accepted:
        tmdb_id = item.get("tmdb_id")
        if not isinstance(tmdb_id, int):
            continue
        existing = dedup_by_tmdb.get(tmdb_id)
        if not existing:
            dedup_by_tmdb[tmdb_id] = item
            continue
        old_score = float(existing.get("score") or 0.0)
        new_score = float(item.get("score") or 0.0)
        if new_score > old_score:
            dedup_by_tmdb[tmdb_id] = item
            continue
        if new_score == old_score and float(item.get("vote_average") or 0.0) > float(existing.get("vote_average") or 0.0):
            dedup_by_tmdb[tmdb_id] = item

    accepted = list(dedup_by_tmdb.values())
    accepted.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            float(item.get("vote_average") or 0.0),
        ),
        reverse=True,
    )
    if not accepted:
        return None, scored[:5]

    best = accepted[0]
    best_score = float(best.get("score") or 0.0)
    min_score = 0.92 if year else 0.8
    if best_score < min_score:
        return None, scored[:5]

    if len(accepted) > 1:
        second_score = float(accepted[1].get("score") or 0.0)
        if best_score - second_score < 0.03:
            best_vote = float(accepted[0].get("vote_average") or 0.0)
            second_vote = float(accepted[1].get("vote_average") or 0.0)
            if best_vote - second_vote < 0.3:
                return None, scored[:5]

    return best, scored[:5]


def _resolve_tmdb_id_by_nullbr(title: str, media_type: str, year: Optional[str]) -> Optional[int]:
    title_variants = _build_title_variants(title)
    if not title_variants:
        return None

    rows: list[dict[str, Any]] = []
    for query in title_variants:
        try:
            result = nullbr_service.search(query, 1)
        except Exception:
            continue
        items = result.get("items") or result.get("results") or []
        if not isinstance(items, list):
            continue
        rows.extend([row for row in items if isinstance(row, dict)])

    if not rows:
        return None

    expected_type = "movie" if media_type == "movie" else "tv"
    best, _ = _pick_best_tmdb_match(
        title=title,
        media_type=expected_type,
        year=year,
        items=rows,
    )
    if not best:
        return None
    tmdb_id = best.get("tmdb_id")
    return int(tmdb_id) if tmdb_id else None


async def _resolve_tmdb_id_by_tmdb(title: str, media_type: str, year: Optional[str]) -> Optional[int]:
    tmdb_id, _ = await _resolve_tmdb_id_by_tmdb_with_status(title, media_type, year)
    return tmdb_id


async def _resolve_tmdb_id_by_tmdb_with_status(
    title: str,
    media_type: str,
    year: Optional[str],
) -> tuple[Optional[int], bool]:
    title_variants = _build_title_variants(title)
    if not title_variants:
        return None, False

    normalized_rows: list[dict[str, Any]] = []
    success_count = 0
    for query in title_variants:
        try:
            result = await tmdb_service.search_multi(query, 1)
            success_count += 1
        except Exception:
            continue

        items = result.get("items") or result.get("results") or []
        if not isinstance(items, list):
            continue
        normalized_rows.extend([row for row in items if isinstance(row, dict)])

    tmdb_failed = success_count == 0
    if not normalized_rows:
        return None, tmdb_failed

    expected_type = "movie" if media_type == "movie" else "tv"
    best, _ = _pick_best_tmdb_match(
        title=title,
        media_type=expected_type,
        year=year,
        items=normalized_rows,
    )

    # Some TMDB entries expose localized re-release dates that can diverge
    # from Douban's original year; retry once without year as a safe fallback.
    if not best and year:
        best, _ = _pick_best_tmdb_match(
            title=title,
            media_type=expected_type,
            year=None,
            items=normalized_rows,
        )

    if not best:
        return None, tmdb_failed

    tmdb_id = best.get("tmdb_id")
    return (int(tmdb_id) if tmdb_id else None), tmdb_failed


async def resolve_douban_explore_item(
    *,
    douban_id: str,
    title: str,
    media_type: str,
    year: Optional[str],
    tmdb_id: Optional[int] = None,
    alternative_titles: Optional[list[str]] = None,
) -> dict[str, Any]:
    normalized_type = "tv" if media_type == "tv" else "movie"
    normalized_douban_id = str(douban_id or "").strip()
    normalized_title = str(title or "").strip()
    had_negative_subject_cache = False
    all_titles: list[str] = []
    if normalized_title:
        all_titles.append(normalized_title)
    if isinstance(alternative_titles, list):
        for item in alternative_titles:
            alt = str(item or "").strip()
            if alt:
                all_titles.append(alt)
    dedup_titles: list[str] = []
    seen_titles: set[str] = set()
    for item in all_titles:
        key = item.casefold()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        dedup_titles.append(item)

    all_title_variants: list[str] = []
    seen_variants: set[str] = set()
    for base in dedup_titles:
        for variant in _build_title_variants(base):
            key = variant.casefold()
            if key in seen_variants:
                continue
            seen_variants.add(key)
            all_title_variants.append(variant)

    if tmdb_id:
        tmdb_value = int(tmdb_id)
        if normalized_douban_id:
            subject_cache_key = _build_subject_tmdb_cache_key(normalized_douban_id, normalized_type)
            _set_subject_tmdb_cache(subject_cache_key, tmdb_value)
        return {
            "resolved": True,
            "media_type": normalized_type,
            "tmdb_id": tmdb_value,
            "confidence": 1.0,
            "reason": "provided_tmdb_id",
            "candidates": [],
        }

    if normalized_douban_id:
        subject_cache_key = _build_subject_tmdb_cache_key(normalized_douban_id, normalized_type)
        cache_hit, cached_tmdb_id = _get_cached_subject_tmdb_id(subject_cache_key)
        if cache_hit:
            if cached_tmdb_id:
                return {
                    "resolved": True,
                    "media_type": normalized_type,
                    "tmdb_id": int(cached_tmdb_id),
                    "confidence": 0.99,
                    "reason": "subject_cache_hit",
                    "candidates": [],
                }
            had_negative_subject_cache = True

    if not all_title_variants:
        return {
            "resolved": False,
            "media_type": normalized_type,
            "tmdb_id": None,
            "confidence": 0.0,
            "reason": "missing_title",
            "candidates": [],
        }

    candidates: list[dict[str, Any]] = []
    nullbr_failed = False
    nullbr_rows: list[dict[str, Any]] = []
    nullbr_success_count = 0
    for query in all_title_variants:
        try:
            nullbr_result = nullbr_service.search(query, 1)
            nullbr_success_count += 1
        except Exception:
            continue

        if not isinstance(nullbr_result, dict):
            continue
        rows = nullbr_result.get("items") or nullbr_result.get("results") or []
        if not isinstance(rows, list):
            continue
        nullbr_rows.extend([row for row in rows if isinstance(row, dict)])

    if nullbr_success_count == 0:
        nullbr_failed = True

    if nullbr_rows:
        best, candidates = _pick_best_tmdb_match(
            title=normalized_title,
            media_type=normalized_type,
            year=year,
            items=nullbr_rows,
            title_variants_override=all_title_variants,
        )
        if best:
            tmdb_value = int(best["tmdb_id"])
            title_cache_key = _build_tmdb_cache_key(normalized_title, year, normalized_type)
            _set_tmdb_id_cache(title_cache_key, tmdb_value)
            if normalized_douban_id:
                subject_cache_key = _build_subject_tmdb_cache_key(normalized_douban_id, normalized_type)
                _set_subject_tmdb_cache(subject_cache_key, tmdb_value)
            return {
                "resolved": True,
                "media_type": normalized_type,
                "tmdb_id": tmdb_value,
                "confidence": float(best.get("score") or 0.0),
                "reason": "matched_by_nullbr",
                "candidates": candidates,
            }

    tmdb_value: Optional[int] = None
    tmdb_failed = True
    for base_title in dedup_titles:
        tmdb_value, tmdb_failed = await _resolve_tmdb_id_by_tmdb_with_status(
            base_title,
            normalized_type,
            year,
        )
        if tmdb_value:
            break
    if tmdb_value:
        title_cache_key = _build_tmdb_cache_key(normalized_title, year, normalized_type)
        _set_tmdb_id_cache(title_cache_key, tmdb_value)
        if normalized_douban_id:
            subject_cache_key = _build_subject_tmdb_cache_key(normalized_douban_id, normalized_type)
            _set_subject_tmdb_cache(subject_cache_key, tmdb_value)
        return {
            "resolved": True,
            "media_type": normalized_type,
            "tmdb_id": tmdb_value,
            "confidence": 0.93,
            "reason": "matched_by_tmdb_fallback",
            "candidates": candidates,
        }

    if normalized_douban_id:
        subject_cache_key = _build_subject_tmdb_cache_key(normalized_douban_id, normalized_type)
        _set_subject_tmdb_cache(subject_cache_key, None)

    if nullbr_failed and tmdb_failed:
        reason = "search_failed"
    elif had_negative_subject_cache:
        reason = "subject_cache_unresolved_rechecked"
    else:
        reason = "low_confidence_or_ambiguous"

    return {
        "resolved": False,
        "media_type": normalized_type,
        "tmdb_id": None,
        "confidence": 0.0,
        "reason": reason,
        "candidates": candidates,
    }


def _normalize_douban_items(
    raw_items: Any,
    default_media_type: str,
    enqueue_tmdb_backfill: bool = True,
    rank_start: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(raw_items, list):
        raise ValueError("invalid douban response format")

    items = []
    backfill_candidates = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        title = title.strip()

        media_type = item.get("type")
        if media_type not in {"movie", "tv"}:
            media_type = default_media_type

        poster_url = _normalize_poster_url(item)

        subject_id = _extract_douban_subject_id(item)
        if not subject_id:
            continue

        year = _extract_year(item)
        subject_cache_key = _build_subject_tmdb_cache_key(subject_id, media_type)
        subject_cache_hit, subject_cached_tmdb_id = _get_cached_subject_tmdb_id(subject_cache_key)
        cache_key = _build_tmdb_cache_key(title=title, year=year, media_type=media_type)
        cache_hit, cached_tmdb_id = _get_cached_tmdb_id(cache_key)
        tmdb_id = subject_cached_tmdb_id if subject_cache_hit else (cached_tmdb_id if cache_hit else None)

        if enqueue_tmdb_backfill and not subject_cache_hit and not cache_hit:
            backfill_candidates.append(
                {
                    "douban_id": subject_id,
                    "cache_key": cache_key,
                    "title": title,
                    "media_type": media_type,
                    "year": year,
                }
            )

        uri = item.get("uri")
        source_url = None
        if isinstance(uri, str) and uri.startswith("douban://"):
            source_url = uri
        else:
            url = item.get("url")
            if isinstance(url, str) and url:
                source_url = url

        items.append(
            {
                "rank": rank_start + index,
                "id": subject_id,
                "douban_id": subject_id,
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "title": title,
                "year": year,
                "poster_url": poster_url,
                "intro": _extract_intro(item),
                "rating": _extract_rating(item),
                "mapping_status": "resolved" if tmdb_id else "unresolved",
                "source_url": source_url,
            }
        )

    return items, backfill_candidates


def _hydrate_tmdb_ids_from_cache(items: list[dict[str, Any]]) -> None:
    for item in items:
        if item.get("tmdb_id") is not None:
            item["mapping_status"] = "resolved"
            continue
        douban_id = str(item.get("douban_id") or item.get("id") or "").strip()
        title = item.get("title")
        media_type = item.get("media_type")
        if not isinstance(title, str) or not title:
            continue
        if media_type not in {"movie", "tv"}:
            continue
        if douban_id:
            subject_cache_key = _build_subject_tmdb_cache_key(douban_id, media_type)
            subject_cache_hit, subject_cached_tmdb_id = _get_cached_subject_tmdb_id(subject_cache_key)
            if subject_cache_hit:
                item["tmdb_id"] = subject_cached_tmdb_id
                item["mapping_status"] = "resolved" if subject_cached_tmdb_id else "unresolved"
                continue
        year = item.get("year")
        cache_key = _build_tmdb_cache_key(title=title, year=year, media_type=media_type)
        cache_hit, cached_tmdb_id = _get_cached_tmdb_id(cache_key)
        if cache_hit:
            item["tmdb_id"] = cached_tmdb_id
            item["mapping_status"] = "resolved" if cached_tmdb_id else "unresolved"


async def _backfill_tmdb_ids(candidates: list[dict[str, Any]]) -> None:
    semaphore = asyncio.Semaphore(TMDB_BACKFILL_CONCURRENCY)

    async def _worker(candidate: dict[str, Any]) -> None:
        cache_key = candidate["cache_key"]
        douban_id = str(candidate.get("douban_id") or "").strip()
        media_type = "tv" if candidate.get("media_type") == "tv" else "movie"
        candidate_title = str(candidate.get("title") or "")
        candidate_year = candidate.get("year") if isinstance(candidate.get("year"), str) else None
        try:
            async with semaphore:
                resolved_id = await asyncio.to_thread(
                    _resolve_tmdb_id_by_nullbr,
                    candidate_title,
                    media_type,
                    candidate_year,
                )
                if not resolved_id:
                    resolved_id = await _resolve_tmdb_id_by_tmdb(
                        title=candidate_title,
                        media_type=media_type,
                        year=candidate_year,
                    )
                _set_tmdb_id_cache(cache_key, resolved_id)
                if douban_id:
                    subject_cache_key = _build_subject_tmdb_cache_key(douban_id, media_type)
                    _set_subject_tmdb_cache(subject_cache_key, resolved_id)
        except Exception:
            _set_tmdb_id_cache(cache_key, None)
            if douban_id:
                subject_cache_key = _build_subject_tmdb_cache_key(douban_id, media_type)
                _set_subject_tmdb_cache(subject_cache_key, None)
        finally:
            _tmdb_backfill_inflight.discard(cache_key)

    await asyncio.gather(*[_worker(candidate) for candidate in candidates], return_exceptions=True)


def _extract_subject_year(payload: dict[str, Any], fallback_year: Optional[str]) -> Optional[str]:
    if isinstance(fallback_year, str) and re.fullmatch(r"(?:19|20)\d{2}", fallback_year):
        return fallback_year

    for key in ("year", "release_date", "pubdate", "date"):
        value = payload.get(key)
        if isinstance(value, str):
            match = re.search(r"(?:19|20)\d{2}", value)
            if match:
                return match.group(0)
        elif isinstance(value, list):
            for node in value:
                if isinstance(node, str):
                    match = re.search(r"(?:19|20)\d{2}", node)
                    if match:
                        return match.group(0)
    return None


async def fetch_douban_subject_detail(
    douban_id: str,
    media_type: str = "movie",
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    normalized_id = str(douban_id or "").strip()
    if not normalized_id:
        raise ValueError("douban_id is required")

    normalized_type = "tv" if media_type == "tv" else "movie"
    now = time.time()
    ts = datetime.now().strftime("%Y%m%d")
    path = f"/subject/{quote(normalized_id, safe='')}"
    sign_path = f"/api/v2{path}"
    sig = _douban_sign(path=sign_path, ts=ts)
    request_url = f"{DOUBAN_FRODO_BASE_URL}{path}"
    params = {
        "apiKey": DOUBAN_API_KEY,
        "os_rom": "android",
        "_ts": ts,
        "_sig": sig,
    }
    headers = _build_douban_api_headers(now)

    if client is None:
        async with httpx.AsyncClient(timeout=12.0) as local_client:
            response = await local_client.get(request_url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    else:
        response = await client.get(request_url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("invalid douban subject payload")

    title = str(payload.get("title") or payload.get("name") or "").strip()
    if not title:
        title = f"豆瓣条目 {normalized_id}"

    year = _extract_subject_year(payload, None)
    poster_url = ""
    pic = payload.get("pic")
    if isinstance(pic, dict):
        for key in ("large", "normal", "url"):
            value = pic.get(key)
            if isinstance(value, str) and value.strip():
                poster_url = value.strip()
                break

    if not poster_url:
        for key in ("cover_url", "cover"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                poster_url = value.strip()
                break
            if isinstance(value, dict):
                url = value.get("url")
                if isinstance(url, str) and url.strip():
                    poster_url = url.strip()
                    break

    if poster_url.startswith("//"):
        poster_url = f"https:{poster_url}"
    elif poster_url.startswith("http://"):
        poster_url = poster_url.replace("http://", "https://", 1)

    intro = str(payload.get("intro") or payload.get("summary") or payload.get("description") or "").strip()
    aliases: list[str] = []
    aka_value = payload.get("aka")
    if isinstance(aka_value, list):
        for item in aka_value:
            text = str(item or "").strip()
            if text:
                aliases.append(text)
    elif isinstance(aka_value, str):
        raw = aka_value.strip()
        if raw:
            aliases.extend([part.strip() for part in re.split(r"[\\/｜|；;、]", raw) if part.strip()])

    original_title = str(payload.get("original_title") or "").strip()
    if not original_title and aliases:
        original_title = aliases[0]

    rating_value: Optional[float] = None
    rating = payload.get("rating")
    if isinstance(rating, dict):
        raw_rating = rating.get("value")
        if isinstance(raw_rating, (int, float, str)):
            try:
                parsed = float(raw_rating)
                if parsed > 0:
                    rating_value = parsed
            except Exception:
                rating_value = None

    genres: list[str] = []
    for node in payload.get("genres") or []:
        if isinstance(node, str) and node.strip():
            genres.append(node.strip())
        elif isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                genres.append(name.strip())

    casts: list[str] = []
    for node in payload.get("actors") or payload.get("casts") or []:
        if isinstance(node, str) and node.strip():
            casts.append(node.strip())
        elif isinstance(node, dict):
            name = node.get("name") or node.get("title")
            if isinstance(name, str) and name.strip():
                casts.append(name.strip())

    source_url = _build_douban_web_subject_url(normalized_id, normalized_type)

    resolved = await resolve_douban_explore_item(
        douban_id=normalized_id,
        title=title,
        media_type=normalized_type,
        year=year,
        tmdb_id=None,
        alternative_titles=[original_title, *aliases],
    )
    resolved_tmdb_id = resolved.get("tmdb_id")
    tmdb_id = int(resolved_tmdb_id) if isinstance(resolved_tmdb_id, int) and resolved_tmdb_id > 0 else None

    return {
        "douban_id": normalized_id,
        "media_type": normalized_type,
        "title": title,
        "original_title": original_title,
        "aliases": aliases,
        "year": year,
        "poster_url": poster_url,
        "intro": intro,
        "rating": rating_value,
        "genres": genres,
        "casts": casts,
        "source_url": source_url,
        "tmdb_mapping": {
            "resolved": bool(tmdb_id),
            "tmdb_id": tmdb_id,
            "reason": resolved.get("reason"),
            "confidence": float(resolved.get("confidence") or 0.0),
        },
    }


def _schedule_tmdb_backfill(candidates: list[dict[str, Any]], limit: int) -> None:
    if not candidates:
        return

    scheduled = []
    for candidate in candidates:
        if len(scheduled) >= limit:
            break
        cache_key = candidate["cache_key"]
        if cache_key in _tmdb_backfill_inflight:
            continue
        _tmdb_backfill_inflight.add(cache_key)
        scheduled.append(candidate)

    if not scheduled:
        return

    try:
        asyncio.create_task(_backfill_tmdb_ids(scheduled))
    except RuntimeError:
        for candidate in scheduled:
            _tmdb_backfill_inflight.discard(candidate["cache_key"])


async def fetch_douban_section(
    source: dict[str, str],
    limit: int,
    refresh: bool,
    start: int = 0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    key = source["key"]
    now = time.time()
    count = min(max(limit, 1), DOUBAN_SECTION_MAX_COUNT)
    start = max(start, 0)
    cache_key = _build_section_cache_key(key, start, count)
    cache_item = _douban_sections_cache.setdefault(
        cache_key,
        {"expires_at": 0.0, "payload": None},
    )
    if (
        not refresh
        and cache_item["payload"] is not None
        and now < cache_item["expires_at"]
    ):
        _hydrate_tmdb_ids_from_cache(cache_item["payload"].get("items", []))
        return cache_item["payload"]

    ts = datetime.now().strftime("%Y%m%d")
    path = source["path"]
    sign_path = f"/api/v2{path}"
    sig = _douban_sign(path=sign_path, ts=ts)
    params = {
        "apiKey": DOUBAN_API_KEY,
        "os_rom": "android",
        "_ts": ts,
        "_sig": sig,
        "start": start,
        "count": count,
    }

    request_url = f"{DOUBAN_FRODO_BASE_URL}{path}"
    headers = _build_douban_api_headers(now)

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=12.0) as local_client:
                response = await local_client.get(
                    request_url,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        else:
            response = await client.get(
                request_url,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()

        raw_items = payload.get("subject_collection_items") or []
        items, backfill_candidates = _normalize_douban_items(
            raw_items=raw_items,
            default_media_type=source["media_type"],
            enqueue_tmdb_backfill=True,
            rank_start=start + 1,
        )

        _schedule_tmdb_backfill(
            candidates=backfill_candidates,
            limit=min(max(limit, 1), TMDB_BACKFILL_MAX_ITEMS_PER_SECTION),
        )
        _hydrate_tmdb_ids_from_cache(items)
        payload_total = payload.get("total")
        try:
            payload_total_int = int(payload_total)
        except Exception:
            payload_total_int = 0
        discovered_total = start + len(raw_items)
        section_total = max(payload_total_int, discovered_total)

        result = {
            "key": source["key"],
            "title": source["title"],
            "tag": source["tag"],
            "source_url": request_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "total": section_total,
            "start": start,
            "count": count,
            "items": items[:limit],
        }
        cache_item["payload"] = result
        cache_item["expires_at"] = now + DOUBAN_CACHE_TTL_SECONDS
        return result
    except Exception as exc:
        if cache_item["payload"] is not None:
            return cache_item["payload"]
        raise exc
