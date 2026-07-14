from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.services.emby_service import emby_service
from app.services.tmdb_service import tmdb_service

from app.core.timezone_utils import beijing_now

logger = logging.getLogger(__name__)


class TvMissingService:
    def __init__(self) -> None:
        self._cache_ttl_seconds = 300
        self._db_cache_ttl_seconds = 24 * 3600
        self._status_cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
        self._latest_sync_at_cache: datetime | None = None

    async def get_tv_missing_status(
        self,
        tmdb_id: int,
        include_specials: bool = False,
        refresh: bool = False,
        season_number: int | None = None,
        episode_start: int | None = None,
        episode_end: int | None = None,
        aired_only: bool = False,
    ) -> dict[str, Any]:
        normalized_tmdb_id = int(tmdb_id or 0)
        if normalized_tmdb_id <= 0:
            return {
                "status": "invalid_tmdb",
                "message": "无效的 TMDB ID",
                "aired_episodes": [],
                "existing_episodes": [],
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "existing": 0, "missing": 0},
            }

        cache_key = self._build_cache_key(
            normalized_tmdb_id,
            include_specials,
            season_number,
            episode_start,
            episode_end,
            aired_only,
        )
        if not refresh:
            cached = await self._get_cached_status(cache_key)
            if cached is not None:
                return cached

        from app.services.emby_sync_index_service import emby_sync_index_service
        from app.services.feiniu_sync_index_service import feiniu_sync_index_service
        from app.services.feiniu_service import feiniu_service
        from app.services.runtime_settings_service import runtime_settings_service

        existing_pairs_all: set[tuple[int, int]] = set()
        emby_ok = False
        status_messages: list[str] = []

        try:
            indexed_emby_result = await emby_sync_index_service.get_tv_existing_episodes(normalized_tmdb_id)
            emby_result = indexed_emby_result if indexed_emby_result is not None else await emby_service.get_tv_episode_status_by_tmdb(normalized_tmdb_id)
            emby_status_text = str(emby_result.get("status") or "")
            if emby_status_text == "ok":
                emby_ok = True
                emby_existing = emby_result.get("existing_episodes") or set()
                if isinstance(emby_existing, (list, set)):
                    for pair in emby_existing:
                        if isinstance(pair, (list, tuple)) and len(pair) == 2:
                            existing_pairs_all.add((int(pair[0]), int(pair[1])))
                status_messages.append("Emby 正常")
            else:
                status_messages.append(f"Emby: {emby_result.get('message') or emby_status_text or 'error'}")
        except Exception:
            status_messages.append("Emby: 查询异常")

        feiniu_url = runtime_settings_service.get_feiniu_url().strip()
        if feiniu_url:
            try:
                indexed_feiniu_result = await feiniu_sync_index_service.get_tv_existing_episodes(normalized_tmdb_id)
                feiniu_result = indexed_feiniu_result if indexed_feiniu_result is not None else await feiniu_service.get_tv_episode_status_by_tmdb(normalized_tmdb_id)
                feiniu_status_text = str(feiniu_result.get("status") or "")
                if feiniu_status_text == "ok":
                    feiniu_existing = feiniu_result.get("existing_episodes") or set()
                    if isinstance(feiniu_existing, (list, set)):
                        for pair in feiniu_existing:
                            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                                existing_pairs_all.add((int(pair[0]), int(pair[1])))
                    status_messages.append("飞牛正常")
                else:
                    status_messages.append(f"飞牛: {feiniu_result.get('message') or feiniu_status_text or 'error'}")
            except Exception:
                status_messages.append("飞牛: 查询异常")

        if not emby_ok and not existing_pairs_all:
            result = {
                "status": "emby_error",
                "message": "；".join(status_messages) if status_messages else "Emby 查询失败",
                "aired_episodes": [],
                "existing_episodes": [],
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "existing": 0, "missing": 0},
            }
            await self._set_cached_status(cache_key, result)
            return result

        try:
            tmdb_pairs = await self._collect_tmdb_episode_pairs(
                normalized_tmdb_id,
                include_specials=include_specials,
                season_number=season_number,
                episode_start=episode_start,
                episode_end=episode_end,
                aired_only=aired_only,
            )
        except Exception as exc:
            result = {
                "status": "tmdb_error",
                "message": f"TMDB 查询失败: {exc}",
                "aired_episodes": [],
                "existing_episodes": [],
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "total": 0, "existing": 0, "missing": 0},
            }
            await self._set_cached_status(cache_key, result)
            return result
        if not tmdb_pairs:
            result = {
                "status": "tmdb_error",
                "message": "TMDB 未返回有效总集信息",
                "aired_episodes": [],
                "existing_episodes": [],
                "missing_episodes": [],
                "missing_by_season": {},
                "counts": {"aired": 0, "total": 0, "existing": 0, "missing": 0},
            }
            await self._set_cached_status(cache_key, result)
            return result

        if not include_specials:
            existing_pairs_all = {pair for pair in existing_pairs_all if pair[0] > 0}
        existing_pairs = existing_pairs_all & tmdb_pairs
        missing_pairs = tmdb_pairs - existing_pairs

        result = {
            "status": "ok",
            "message": "缺集状态计算完成",
            "aired_episodes": self._sorted_pairs(tmdb_pairs),
            "existing_episodes": self._sorted_pairs(existing_pairs),
            "missing_episodes": self._sorted_pairs(missing_pairs),
            "missing_by_season": self._to_season_map(missing_pairs),
            "counts": {
                "aired": len(tmdb_pairs),
                "total": len(tmdb_pairs),
                "existing": len(existing_pairs),
                "missing": len(missing_pairs),
            },
        }
        await self._set_cached_status(cache_key, result)
        return result

    async def get_tv_missing_statuses(
        self,
        tmdb_ids: list[int],
        include_specials: bool = False,
        refresh: bool = False,
        concurrency: int = 12,
        options_by_tmdb: dict[int, dict[str, Any]] | None = None,
        subscription_id_by_tmdb: dict[int, int] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """批量计算剧集缺集状态，避免订阅列表逐条查询媒体库。"""
        normalized_ids = [int(item or 0) for item in tmdb_ids]
        unique_ids = list(dict.fromkeys(item for item in normalized_ids if item > 0))
        output: dict[int, dict[str, Any]] = {}
        pending_ids: list[int] = []
        subscription_map = {
            int(tmdb_id): int(subscription_id)
            for tmdb_id, subscription_id in (subscription_id_by_tmdb or {}).items()
            if int(tmdb_id or 0) > 0 and int(subscription_id or 0) > 0
        }

        for tmdb_id in unique_ids:
            per_sub_opts = dict((options_by_tmdb or {}).get(tmdb_id) or {})
            if "include_specials" not in per_sub_opts:
                per_sub_opts["include_specials"] = include_specials
            options = self._normalize_status_options(**per_sub_opts)
            cache_key = self._build_cache_key(tmdb_id, **options)
            if not refresh:
                cached = await self._get_cached_status(cache_key)
                if cached is not None:
                    output[tmdb_id] = cached
                    continue
                subscription_id = subscription_map.get(tmdb_id)
                if subscription_id is not None:
                    db_cached = await self._get_db_cached_status(subscription_id)
                    if db_cached is not None:
                        output[tmdb_id] = db_cached
                        await self._set_cached_status(cache_key, db_cached)
                        continue
            pending_ids.append(tmdb_id)

        if not pending_ids:
            return output

        existing_by_tmdb, source_available = await self._collect_indexed_existing_pairs(
            pending_ids
        )
        if not source_available:
            for tmdb_id in pending_ids:
                result = {
                    "status": "cache_unavailable",
                    "message": "Emby/飞牛索引尚不可用，请先执行媒体库索引同步",
                    "aired_episodes": [],
                    "existing_episodes": [],
                    "missing_episodes": [],
                    "missing_by_season": {},
                    "counts": {"aired": 0, "existing": 0, "missing": 0},
                }
                output[tmdb_id] = result
                subscription_id = subscription_map.get(tmdb_id)
                if subscription_id is not None:
                    await self._persist_db_cached_status(subscription_id, result)
            return output

        semaphore = asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def build_one(tmdb_id: int) -> tuple[int, dict[str, Any]]:
            per_sub_opts = dict((options_by_tmdb or {}).get(tmdb_id) or {})
            if "include_specials" not in per_sub_opts:
                per_sub_opts["include_specials"] = include_specials
            options = self._normalize_status_options(**per_sub_opts)
            try:
                async with semaphore:
                    tmdb_pairs = await self._collect_tmdb_episode_pairs(
                        tmdb_id,
                        include_specials=bool(options.get("include_specials")),
                        season_number=options.get("season_number"),
                        episode_start=options.get("episode_start"),
                        episode_end=options.get("episode_end"),
                        aired_only=bool(options.get("aired_only")),
                    )
            except Exception as exc:
                result = {
                    "status": "tmdb_error",
                    "message": f"TMDB 查询失败: {exc}",
                    "aired_episodes": [],
                    "existing_episodes": [],
                    "missing_episodes": [],
                    "missing_by_season": {},
                    "counts": {
                        "aired": 0,
                        "total": 0,
                        "existing": 0,
                        "missing": 0,
                    },
                }
                return tmdb_id, result
            if not tmdb_pairs:
                result = {
                    "status": "tmdb_error",
                    "message": "TMDB 未返回有效总集信息",
                    "aired_episodes": [],
                    "existing_episodes": [],
                    "missing_episodes": [],
                    "missing_by_season": {},
                    "counts": {
                        "aired": 0,
                        "total": 0,
                        "existing": 0,
                        "missing": 0,
                    },
                }
                return tmdb_id, result

            existing_pairs_all = set(existing_by_tmdb.get(tmdb_id) or set())
            if not bool(options.get("include_specials")):
                existing_pairs_all = {pair for pair in existing_pairs_all if pair[0] > 0}
            existing_pairs = existing_pairs_all & tmdb_pairs
            missing_pairs = tmdb_pairs - existing_pairs
            return tmdb_id, {
                "status": "ok",
                "message": "缺集状态计算完成",
                "aired_episodes": self._sorted_pairs(tmdb_pairs),
                "existing_episodes": self._sorted_pairs(existing_pairs),
                "missing_episodes": self._sorted_pairs(missing_pairs),
                "missing_by_season": self._to_season_map(missing_pairs),
                "counts": {
                    "aired": len(tmdb_pairs),
                    "total": len(tmdb_pairs),
                    "existing": len(existing_pairs),
                    "missing": len(missing_pairs),
                },
            }

        for tmdb_id, result in await asyncio.gather(
            *(build_one(tmdb_id) for tmdb_id in pending_ids)
        ):
            output[tmdb_id] = result
            per_sub_opts = dict((options_by_tmdb or {}).get(tmdb_id) or {})
            if "include_specials" not in per_sub_opts:
                per_sub_opts["include_specials"] = include_specials
            options = self._normalize_status_options(**per_sub_opts)
            await self._set_cached_status(self._build_cache_key(tmdb_id, **options), result)
            subscription_id = subscription_map.get(tmdb_id)
            if subscription_id is not None:
                await self._persist_db_cached_status(subscription_id, result)

        return output

    async def precompute_all_active_tv_missing_cache(self) -> None:
        """媒体库同步完成后后台预计算所有活跃电视剧订阅的缺集缓存。"""
        from sqlalchemy import or_

        from app.core.database import async_session_maker
        from app.models.models import DownloadRecord, MediaStatus, MediaType, Subscription

        try:
            async with async_session_maker() as db:
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
                    select(Subscription).where(
                        Subscription.media_type == MediaType.TV,
                        Subscription.is_active == True,  # noqa: E712
                        ~has_successful_transfer,
                    )
                )
                rows = result.scalars().all()
                if not rows:
                    return

                tmdb_ids = [int(sub.tmdb_id) for sub in rows if sub.tmdb_id is not None]
                if not tmdb_ids:
                    return

                subscription_id_by_tmdb = {
                    int(sub.tmdb_id): int(sub.id)
                    for sub in rows
                    if sub.tmdb_id is not None
                }
                options_by_tmdb = {
                    int(sub.tmdb_id): {
                        "include_specials": bool(sub.tv_include_specials),
                        "season_number": sub.tv_season_number
                        if sub.tv_scope in {"season", "episode_range"}
                        else None,
                        "episode_start": sub.tv_episode_start
                        if sub.tv_scope == "episode_range"
                        else None,
                        "episode_end": sub.tv_episode_end
                        if sub.tv_scope == "episode_range"
                        else None,
                        "aired_only": sub.tv_follow_mode == "new",
                    }
                    for sub in rows
                    if sub.tmdb_id is not None
                }
                await self.get_tv_missing_statuses(
                    tmdb_ids,
                    include_specials=False,
                    refresh=True,
                    options_by_tmdb=options_by_tmdb,
                    subscription_id_by_tmdb=subscription_id_by_tmdb,
                )
        except Exception:
            logger.exception("后台预计算电视剧缺集缓存失败")

    async def _collect_indexed_existing_pairs(
        self, tmdb_ids: list[int]
    ) -> tuple[dict[int, set[tuple[int, int]]], bool]:
        from sqlalchemy import select

        from app.core.database import async_session_maker
        from app.models.emby_sync_index import EmbySyncState, EmbyTvEpisodeIndex
        from app.models.feiniu_sync_index import FeiniuSyncState, FeiniuTvEpisodeIndex
        from app.services.runtime_settings_service import runtime_settings_service

        existing_by_tmdb: dict[int, set[tuple[int, int]]] = {
            int(tmdb_id): set() for tmdb_id in tmdb_ids
        }
        source_available = False
        async with async_session_maker() as db:
            emby_state = (
                await db.execute(select(EmbySyncState).where(EmbySyncState.id == 1))
            ).scalar_one_or_none()
            if emby_state and emby_state.last_successful_sync_at is not None:
                source_available = True
                rows = (
                    await db.execute(
                        select(EmbyTvEpisodeIndex).where(
                            EmbyTvEpisodeIndex.tmdb_id.in_(tmdb_ids)
                        )
                    )
                ).scalars().all()
                for row in rows:
                    existing_by_tmdb.setdefault(int(row.tmdb_id), set()).add(
                        (int(row.season_number), int(row.episode_number))
                    )

            if runtime_settings_service.get_feiniu_url().strip():
                feiniu_state = (
                    await db.execute(
                        select(FeiniuSyncState).where(FeiniuSyncState.id == 1)
                    )
                ).scalar_one_or_none()
                if feiniu_state and feiniu_state.last_successful_sync_at is not None:
                    source_available = True
                    rows = (
                        await db.execute(
                            select(FeiniuTvEpisodeIndex).where(
                                FeiniuTvEpisodeIndex.tmdb_id.in_(tmdb_ids)
                            )
                        )
                    ).scalars().all()
                    for row in rows:
                        existing_by_tmdb.setdefault(int(row.tmdb_id), set()).add(
                            (int(row.season_number), int(row.episode_number))
                        )

        return existing_by_tmdb, source_available

    def clear_cache(self) -> None:
        self._status_cache.clear()

    async def _get_latest_media_sync_at(self) -> datetime | None:
        from app.core.database import async_session_maker
        from app.models.emby_sync_index import EmbySyncState
        from app.models.feiniu_sync_index import FeiniuSyncState
        from app.services.runtime_settings_service import runtime_settings_service

        latest: datetime | None = None
        async with async_session_maker() as db:
            emby_state = (
                await db.execute(select(EmbySyncState).where(EmbySyncState.id == 1))
            ).scalar_one_or_none()
            if emby_state and emby_state.last_successful_sync_at is not None:
                latest = emby_state.last_successful_sync_at

            if runtime_settings_service.get_feiniu_url().strip():
                feiniu_state = (
                    await db.execute(
                        select(FeiniuSyncState).where(FeiniuSyncState.id == 1)
                    )
                ).scalar_one_or_none()
                if feiniu_state and feiniu_state.last_successful_sync_at is not None:
                    if latest is None or feiniu_state.last_successful_sync_at > latest:
                        latest = feiniu_state.last_successful_sync_at
        return latest

    def _is_db_cache_valid(self, computed_at: datetime | None) -> bool:
        if computed_at is None:
            return False
        now = beijing_now()
        if now - computed_at <= timedelta(seconds=self._db_cache_ttl_seconds):
            return True
        latest_sync_at = getattr(self, "_latest_sync_at_cache", None)
        if latest_sync_at is None:
            return False
        return computed_at >= latest_sync_at

    async def _ensure_latest_sync_at_cache(self) -> None:
        self._latest_sync_at_cache = await self._get_latest_media_sync_at()

    @staticmethod
    def _db_cache_row_to_status(row: Any) -> dict[str, Any]:
        missing_by_season: dict[str, list[int]] = {}
        raw_missing = row.missing_by_season
        if raw_missing:
            try:
                parsed = json.loads(raw_missing)
                if isinstance(parsed, dict):
                    missing_by_season = parsed
            except Exception:
                missing_by_season = {}
        total_count = int(row.total_count or 0)
        existing_count = int(row.existing_count or 0)
        missing_count = int(row.missing_count or 0)
        return {
            "status": str(row.status or "unknown"),
            "message": str(row.message or ""),
            "aired_episodes": [],
            "existing_episodes": [],
            "missing_episodes": [],
            "missing_by_season": missing_by_season,
            "counts": {
                "total": total_count,
                "aired": total_count,
                "existing": existing_count,
                "missing": missing_count,
            },
        }

    async def _get_db_cached_status(self, subscription_id: int) -> dict[str, Any] | None:
        from app.core.database import async_session_maker
        from app.models.models import SubscriptionTvMissingCache

        await self._ensure_latest_sync_at_cache()
        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(SubscriptionTvMissingCache).where(
                        SubscriptionTvMissingCache.subscription_id == int(subscription_id)
                    )
                )
            ).scalar_one_or_none()
            if row is None or not self._is_db_cache_valid(row.computed_at):
                return None
            return self._db_cache_row_to_status(row)

    async def _persist_db_cached_status(
        self, subscription_id: int, payload: dict[str, Any]
    ) -> None:
        from app.core.database import async_session_maker
        from app.models.models import SubscriptionTvMissingCache

        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        total_count = int(counts.get("total") or counts.get("aired") or 0)
        existing_count = int(counts.get("existing") or 0)
        missing_count = int(counts.get("missing") or 0)
        missing_by_season = payload.get("missing_by_season") or {}
        try:
            missing_by_season_json = json.dumps(missing_by_season, ensure_ascii=False)
        except Exception:
            missing_by_season_json = "{}"

        async with async_session_maker() as db:
            row = (
                await db.execute(
                    select(SubscriptionTvMissingCache).where(
                        SubscriptionTvMissingCache.subscription_id == int(subscription_id)
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = SubscriptionTvMissingCache(subscription_id=int(subscription_id))
                db.add(row)
            row.status = str(payload.get("status") or "unknown")
            row.total_count = total_count
            row.existing_count = existing_count
            row.missing_count = missing_count
            row.missing_by_season = missing_by_season_json
            row.message = str(payload.get("message") or "")
            row.computed_at = beijing_now()
            await db.commit()

    async def _collect_tmdb_episode_pairs(
        self,
        tmdb_id: int,
        include_specials: bool = False,
        season_number: int | None = None,
        episode_start: int | None = None,
        episode_end: int | None = None,
        aired_only: bool = False,
    ) -> set[tuple[int, int]]:
        detail = await tmdb_service.get_tv_episode_counts(tmdb_id)
        seasons = detail.get("seasons") if isinstance(detail, dict) else []
        if not isinstance(seasons, list):
            seasons = []

        pairs: set[tuple[int, int]] = set()
        selected_season = int(season_number) if season_number is not None else None
        season_targets: list[int] = []
        for season in seasons:
            if not isinstance(season, dict):
                continue
            current_season = self._to_non_negative_int(season.get("season_number"))
            if current_season is None:
                continue
            if current_season == 0 and not include_specials:
                continue
            if selected_season is not None and current_season != selected_season:
                continue
            season_targets.append(current_season)

        if aired_only:
            if not season_targets:
                return set()
            semaphore = asyncio.Semaphore(6)

            async def _fetch_aired_pairs(target_season: int) -> set[tuple[int, int]]:
                async with semaphore:
                    return await self._collect_tmdb_aired_season_pairs(
                        tmdb_id,
                        target_season,
                        episode_start=episode_start,
                        episode_end=episode_end,
                    )

            season_results = await asyncio.gather(
                *(_fetch_aired_pairs(target) for target in season_targets)
            )
            for season_pairs in season_results:
                pairs.update(season_pairs)
            return pairs

        for season in seasons:
            if not isinstance(season, dict):
                continue
            current_season = self._to_non_negative_int(season.get("season_number"))
            if current_season is None:
                continue
            if current_season == 0 and not include_specials:
                continue
            if selected_season is not None and current_season != selected_season:
                continue

            episode_count = self._to_non_negative_int(season.get("episode_count")) or 0
            if episode_count <= 0:
                continue
            for episode_number in range(1, episode_count + 1):
                if episode_start is not None and episode_number < int(episode_start):
                    continue
                if episode_end is not None and episode_number > int(episode_end):
                    continue
                pairs.add((current_season, episode_number))
        return pairs

    async def _collect_tmdb_aired_season_pairs(
        self,
        tmdb_id: int,
        season_number: int,
        episode_start: int | None = None,
        episode_end: int | None = None,
    ) -> set[tuple[int, int]]:
        detail = await tmdb_service.get_tv_season_detail(tmdb_id, season_number)
        episodes = detail.get("episodes") if isinstance(detail, dict) else []
        if not isinstance(episodes, list):
            return set()
        today = date.today()
        pairs: set[tuple[int, int]] = set()
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            episode_number = self._to_non_negative_int(episode.get("episode_number"))
            if episode_number is None or episode_number <= 0:
                continue
            if episode_start is not None and episode_number < int(episode_start):
                continue
            if episode_end is not None and episode_number > int(episode_end):
                continue
            air_date = str(episode.get("air_date") or "").strip()
            if not air_date:
                continue
            try:
                if date.fromisoformat(air_date) > today:
                    continue
            except Exception:
                continue
            pairs.add((season_number, episode_number))
        return pairs

    @staticmethod
    def _normalize_status_options(
        include_specials: bool = False,
        season_number: int | None = None,
        episode_start: int | None = None,
        episode_end: int | None = None,
        aired_only: bool = False,
        **_: Any,
    ) -> dict[str, Any]:
        return {
            "include_specials": bool(include_specials),
            "season_number": int(season_number) if season_number is not None else None,
            "episode_start": int(episode_start) if episode_start is not None else None,
            "episode_end": int(episode_end) if episode_end is not None else None,
            "aired_only": bool(aired_only),
        }

    @classmethod
    def _build_cache_key(
        cls,
        tmdb_id: int,
        include_specials: bool = False,
        season_number: int | None = None,
        episode_start: int | None = None,
        episode_end: int | None = None,
        aired_only: bool = False,
    ) -> str:
        options = cls._normalize_status_options(
            include_specials=include_specials,
            season_number=season_number,
            episode_start=episode_start,
            episode_end=episode_end,
            aired_only=aired_only,
        )
        return (
            f"{int(tmdb_id)}:{1 if options['include_specials'] else 0}:"
            f"{options['season_number'] or ''}:"
            f"{options['episode_start'] or ''}:"
            f"{options['episode_end'] or ''}:"
            f"{1 if options['aired_only'] else 0}"
        )

    async def _get_cached_status(self, key: str) -> dict[str, Any] | None:
        now_ts = beijing_now().timestamp()
        async with self._cache_lock:
            cached = self._status_cache.get(key)
            if not cached:
                return None
            ts = float(cached.get("ts") or 0)
            if now_ts - ts > self._cache_ttl_seconds:
                self._status_cache.pop(key, None)
                return None
            payload = cached.get("payload")
            return dict(payload) if isinstance(payload, dict) else None

    async def _set_cached_status(self, key: str, payload: dict[str, Any]) -> None:
        async with self._cache_lock:
            self._status_cache[key] = {
                "ts": beijing_now().timestamp(),
                "payload": dict(payload),
            }
            if len(self._status_cache) > 500:
                oldest_key = min(self._status_cache.items(), key=lambda item: float(item[1].get("ts") or 0))[0]
                self._status_cache.pop(oldest_key, None)

    @staticmethod
    def _sorted_pairs(pairs: set[tuple[int, int]]) -> list[tuple[int, int]]:
        return sorted(pairs, key=lambda item: (item[0], item[1]))

    @staticmethod
    def _to_season_map(pairs: set[tuple[int, int]]) -> dict[str, list[int]]:
        output: dict[str, list[int]] = {}
        for season, episode in sorted(pairs, key=lambda item: (item[0], item[1])):
            key = str(season)
            output.setdefault(key, [])
            output[key].append(episode)
        return output

    @staticmethod
    def _to_non_negative_int(value: Any) -> int | None:
        try:
            number = int(value)
        except Exception:
            return None
        if number < 0:
            return None
        return number


tv_missing_service = TvMissingService()
