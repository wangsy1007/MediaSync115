from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from app.services.emby_service import emby_service
from app.services.tmdb_service import tmdb_service


class TvMissingService:
    def __init__(self) -> None:
        self._cache_ttl_seconds = 300
        self._status_cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()

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
    ) -> dict[int, dict[str, Any]]:
        """批量计算剧集缺集状态，避免订阅列表逐条查询媒体库。"""
        normalized_ids = [int(item or 0) for item in tmdb_ids]
        unique_ids = list(dict.fromkeys(item for item in normalized_ids if item > 0))
        output: dict[int, dict[str, Any]] = {}
        pending_ids: list[int] = []

        for tmdb_id in unique_ids:
            options = self._normalize_status_options(
                include_specials=include_specials,
                **((options_by_tmdb or {}).get(tmdb_id) or {}),
            )
            cache_key = self._build_cache_key(tmdb_id, **options)
            if not refresh:
                cached = await self._get_cached_status(cache_key)
                if cached is not None:
                    output[tmdb_id] = cached
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
            return output

        semaphore = asyncio.Semaphore(max(1, int(concurrency or 1)))

        async def build_one(tmdb_id: int) -> tuple[int, dict[str, Any]]:
            options = self._normalize_status_options(
                include_specials=include_specials,
                **((options_by_tmdb or {}).get(tmdb_id) or {}),
            )
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
            options = self._normalize_status_options(
                include_specials=include_specials,
                **((options_by_tmdb or {}).get(tmdb_id) or {}),
            )
            await self._set_cached_status(self._build_cache_key(tmdb_id, **options), result)

        return output

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

    async def _collect_tmdb_episode_pairs(
        self,
        tmdb_id: int,
        include_specials: bool = False,
        season_number: int | None = None,
        episode_start: int | None = None,
        episode_end: int | None = None,
        aired_only: bool = False,
    ) -> set[tuple[int, int]]:
        detail = await tmdb_service.get_tv_detail(tmdb_id)
        seasons = detail.get("seasons") if isinstance(detail, dict) else []
        if not isinstance(seasons, list):
            seasons = []

        pairs: set[tuple[int, int]] = set()
        selected_season = int(season_number) if season_number is not None else None
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
            if aired_only:
                season_pairs = await self._collect_tmdb_aired_season_pairs(
                    tmdb_id,
                    current_season,
                    episode_start=episode_start,
                    episode_end=episode_end,
                )
                pairs.update(season_pairs)
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
        now_ts = datetime.utcnow().timestamp()
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
                "ts": datetime.utcnow().timestamp(),
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
