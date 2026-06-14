"""订阅自动清理策略。

应在以下情况删除（或自动清理）订阅记录：

- **电影**：已有成功转存记录；或 Emby/飞牛索引确认该片已入库。
- **电视剧**：在订阅范围内（全剧/某季/集区间）缺集数为 0；
  若选「只追新集」，还须确认订阅范围内没有待播集需要继续跟进。
- **用户意图**：手动取消订阅（由 API 处理，不在此模块内）。
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Protocol

from app.models.models import MediaType


class SubscriptionCleanupSubject(Protocol):
    """清理判定所需的最小订阅字段。"""

    media_type: MediaType
    tmdb_id: int | None
    tv_scope: str | None
    tv_season_number: int | None
    tv_episode_start: int | None
    tv_episode_end: int | None
    tv_follow_mode: str | None
    tv_include_specials: bool | None


def normalize_tv_follow_mode(raw: Any) -> str:
    value = str(raw or "missing").strip().lower()
    return value if value in {"missing", "new"} else "missing"


def normalize_tv_scope(raw: Any) -> str:
    value = str(raw or "all").strip().lower()
    return value if value in {"all", "season", "episode_range"} else "all"


def build_tv_missing_status_kwargs(sub: SubscriptionCleanupSubject) -> dict[str, Any]:
    """构造 tv_missing_service.get_tv_missing_status 的查询参数。"""
    scope = normalize_tv_scope(sub.tv_scope)
    follow_mode = normalize_tv_follow_mode(sub.tv_follow_mode)
    return {
        "include_specials": bool(sub.tv_include_specials),
        "season_number": sub.tv_season_number
        if scope in {"season", "episode_range"}
        else None,
        "episode_start": sub.tv_episode_start if scope == "episode_range" else None,
        "episode_end": sub.tv_episode_end if scope == "episode_range" else None,
        "aired_only": follow_mode == "new",
    }


def evaluate_movie_cleanup(
    *,
    has_successful_transfer: bool,
    emby_exists: bool,
    feiniu_exists: bool,
) -> tuple[bool, str]:
    if has_successful_transfer:
        return True, "电影已有成功转存记录"
    if emby_exists:
        return True, "电影已存在于 Emby"
    if feiniu_exists:
        return True, "电影已存在于飞牛"
    return False, ""


def evaluate_tv_cleanup(
    tv_missing_result: dict[str, Any] | None,
    *,
    follow_mode: str,
    has_upcoming_episodes: bool,
) -> tuple[bool, str]:
    """根据缺集快照判断是否可清理电视剧订阅。"""
    payload = tv_missing_result if isinstance(tv_missing_result, dict) else {}
    if str(payload.get("status") or "") != "ok":
        return False, ""

    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    missing_count = int(counts.get("missing") or 0)
    if missing_count > 0:
        return False, ""

    mode = normalize_tv_follow_mode(follow_mode)
    if mode == "new" and has_upcoming_episodes:
        return False, ""

    if mode == "new":
        return True, "剧集已播集均已入库，且无待播集需跟进"
    return True, "剧集订阅范围内已不缺集"


async def has_upcoming_episodes_in_subscription_scope(
    tmdb_id: int,
    sub: SubscriptionCleanupSubject,
) -> bool:
    """只追新集：订阅范围内是否存在尚未播出的集（含未定播出日）。"""
    normalized_tmdb_id = int(tmdb_id or 0)
    if normalized_tmdb_id <= 0:
        return False

    from app.services.tmdb_service import tmdb_service

    scope = normalize_tv_scope(sub.tv_scope)
    selected_season = (
        int(sub.tv_season_number)
        if scope in {"season", "episode_range"} and sub.tv_season_number is not None
        else None
    )
    episode_start = (
        int(sub.tv_episode_start)
        if scope == "episode_range" and sub.tv_episode_start is not None
        else None
    )
    episode_end = (
        int(sub.tv_episode_end)
        if scope == "episode_range" and sub.tv_episode_end is not None
        else None
    )
    include_specials = bool(sub.tv_include_specials)

    detail = await tmdb_service.get_tv_detail(normalized_tmdb_id)
    seasons = detail.get("seasons") if isinstance(detail, dict) else []
    if not isinstance(seasons, list):
        return False

    today = date.today()
    season_targets: list[int] = []
    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_number = _to_positive_int(season.get("season_number"))
        if season_number is None:
            continue
        if season_number == 0 and not include_specials:
            continue
        if selected_season is not None and season_number != selected_season:
            continue
        season_targets.append(season_number)

    if not season_targets:
        return False

    semaphore = asyncio.Semaphore(6)

    async def _fetch_season_detail(target_season: int) -> dict[str, Any]:
        async with semaphore:
            payload = await tmdb_service.get_tv_season_detail(
                normalized_tmdb_id, target_season
            )
            return payload if isinstance(payload, dict) else {}

    season_details = await asyncio.gather(
        *(_fetch_season_detail(season_number) for season_number in season_targets)
    )

    for season_detail in season_details:
        episodes = season_detail.get("episodes") if isinstance(season_detail, dict) else []
        if not isinstance(episodes, list):
            continue

        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            episode_number = _to_positive_int(episode.get("episode_number"))
            if episode_number is None:
                continue
            if episode_start is not None and episode_number < episode_start:
                continue
            if episode_end is not None and episode_number > episode_end:
                continue

            air_date_raw = str(episode.get("air_date") or "").strip()
            if not air_date_raw:
                return True
            try:
                if date.fromisoformat(air_date_raw) > today:
                    return True
            except ValueError:
                return True

    return False


def _to_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
