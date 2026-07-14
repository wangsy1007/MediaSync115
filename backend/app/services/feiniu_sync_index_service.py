from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.core.timezone_utils import beijing_now
from app.core.database import (
    async_session_maker,
    ensure_tables_exist,
    is_missing_table_error,
)
from app.models.feiniu_sync_index import (
    FeiniuMediaIndex,
    FeiniuSyncState,
    FeiniuTvEpisodeIndex,
)
from app.services.feiniu_service import feiniu_service
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)

FEINIU_SYNC_STATE_ROW_ID = 1
FEINIU_SYNC_EPISODE_FETCH_CONCURRENCY = 8


class FeiniuSyncIndexService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._background_task: asyncio.Task | None = None

    async def _ensure_tables(self) -> None:
        await ensure_tables_exist(
            "feiniu_media_index",
            "feiniu_tv_episode_index",
            "feiniu_sync_state",
        )

    async def get_status(self) -> dict[str, Any]:
        try:
            return await self._get_status()
        except OperationalError as exc:
            if not is_missing_table_error(
                exc,
                "feiniu_media_index",
                "feiniu_tv_episode_index",
                "feiniu_sync_state",
            ):
                raise
            await self._ensure_tables()
            return await self._get_status()

    async def _get_status(self) -> dict[str, Any]:
        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            await db.commit()
            return self._serialize_state(state, running=self._is_running())

    async def has_successful_snapshot(self) -> bool:
        try:
            return await self._has_successful_snapshot()
        except OperationalError as exc:
            if not is_missing_table_error(
                exc,
                "feiniu_media_index",
                "feiniu_tv_episode_index",
                "feiniu_sync_state",
            ):
                raise
            await self._ensure_tables()
            return await self._has_successful_snapshot()

    async def _has_successful_snapshot(self) -> bool:
        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            await db.commit()
            return state.last_successful_sync_at is not None

    async def get_movie_status(self, tmdb_id: int) -> dict[str, Any] | None:
        try:
            return await self._get_movie_status(tmdb_id)
        except OperationalError as exc:
            if not is_missing_table_error(
                exc,
                "feiniu_media_index",
                "feiniu_tv_episode_index",
                "feiniu_sync_state",
            ):
                raise
            await self._ensure_tables()
            return await self._get_movie_status(tmdb_id)

    async def batch_check_status(
        self, candidates: list[tuple[str, str, int]]
    ) -> dict[str, dict[str, Any]]:
        """批量查询飞牛在库状态，避免逐条开 session 的 N+1 问题。"""
        if not candidates:
            return {}

        try:
            has_snapshot = await self.has_successful_snapshot()
        except Exception:
            has_snapshot = False

        if not has_snapshot:
            return {
                key: {"exists_in_feiniu": False, "status": "cache_unavailable", "matched_type": ""}
                for key, _, _ in candidates
            }

        movie_candidates = [(key, tmdb_id) for key, mt, tmdb_id in candidates if mt == "movie" and tmdb_id > 0]
        tv_candidates = [(key, tmdb_id) for key, mt, tmdb_id in candidates if mt == "tv" and tmdb_id > 0]

        result_map: dict[str, dict[str, Any]] = {}

        try:
            async with async_session_maker() as db:
                if movie_candidates:
                    movie_tmdb_ids = [tmdb_id for _, tmdb_id in movie_candidates]
                    rows = await db.execute(
                        select(FeiniuMediaIndex).where(
                            FeiniuMediaIndex.media_type == "movie",
                            FeiniuMediaIndex.tmdb_id.in_(movie_tmdb_ids),
                        )
                    )
                    found_movies = {row.tmdb_id: row for row in rows.scalars().all()}
                    for key, tmdb_id in movie_candidates:
                        row = found_movies.get(tmdb_id)
                        item_ids = self._parse_json_list(row.feiniu_item_ids_json) if row else []
                        exists = bool(item_ids)
                        result_map[key] = {
                            "exists_in_feiniu": exists,
                            "status": "ok",
                            "matched_type": "movie" if exists else "",
                        }

                if tv_candidates:
                    tv_tmdb_ids = [tmdb_id for _, tmdb_id in tv_candidates]
                    rows = await db.execute(
                        select(FeiniuTvEpisodeIndex.tmdb_id).where(
                            FeiniuTvEpisodeIndex.tmdb_id.in_(tv_tmdb_ids),
                        ).distinct()
                    )
                    found_tv_ids = {row[0] for row in rows.all()}
                    for key, tmdb_id in tv_candidates:
                        exists = tmdb_id in found_tv_ids
                        result_map[key] = {
                            "exists_in_feiniu": exists,
                            "status": "ok",
                            "matched_type": "tv" if exists else "",
                        }

                await db.commit()
        except Exception as exc:
            logger.warning("feiniu batch_check_status failed: %s", exc)
            for key, _, _ in candidates:
                if key not in result_map:
                    result_map[key] = {"exists_in_feiniu": False, "status": "request_failed", "matched_type": ""}

        for key, _, _ in candidates:
            if key not in result_map:
                result_map[key] = {"exists_in_feiniu": False, "status": "ok", "matched_type": ""}

        return result_map

    async def _get_movie_status(self, tmdb_id: int) -> dict[str, Any] | None:
        normalized_tmdb_id = int(tmdb_id or 0)
        if normalized_tmdb_id <= 0:
            return {
                "status": "invalid_tmdb",
                "message": "无效的 TMDB ID",
                "exists": False,
                "item_ids": [],
            }

        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            if state.last_successful_sync_at is None:
                await db.commit()
                return None
            result = await db.execute(
                select(FeiniuMediaIndex).where(
                    FeiniuMediaIndex.media_type == "movie",
                    FeiniuMediaIndex.tmdb_id == normalized_tmdb_id,
                )
            )
            row = result.scalar_one_or_none()
            await db.commit()

        item_ids = self._parse_json_list(row.feiniu_item_ids_json) if row else []
        exists = bool(item_ids)
        return {
            "status": "ok",
            "message": "查询成功" if exists else "索引中未匹配到该 TMDB 电影",
            "exists": exists,
            "item_ids": item_ids,
            "source": "feiniu_sync_index",
        }

    async def get_tv_existing_episodes(self, tmdb_id: int) -> dict[str, Any] | None:
        try:
            return await self._get_tv_existing_episodes(tmdb_id)
        except OperationalError as exc:
            if not is_missing_table_error(
                exc,
                "feiniu_media_index",
                "feiniu_tv_episode_index",
                "feiniu_sync_state",
            ):
                raise
            await self._ensure_tables()
            return await self._get_tv_existing_episodes(tmdb_id)

    async def _get_tv_existing_episodes(self, tmdb_id: int) -> dict[str, Any] | None:
        normalized_tmdb_id = int(tmdb_id or 0)
        if normalized_tmdb_id <= 0:
            return {
                "status": "invalid_tmdb",
                "message": "无效的 TMDB ID",
                "existing_episodes": set(),
                "source": "feiniu_sync_index",
            }

        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            if state.last_successful_sync_at is None:
                await db.commit()
                return None
            result = await db.execute(
                select(FeiniuTvEpisodeIndex).where(
                    FeiniuTvEpisodeIndex.tmdb_id == normalized_tmdb_id
                )
            )
            rows = result.scalars().all()
            await db.commit()

        existing_episodes = {
            (int(row.season_number), int(row.episode_number)) for row in rows
        }
        return {
            "status": "ok",
            "message": "查询成功"
            if existing_episodes
            else "索引中未匹配到该 TMDB 剧集",
            "existing_episodes": existing_episodes,
            "source": "feiniu_sync_index",
        }

    async def sync_index(self, trigger: str = "manual") -> dict[str, Any]:
        try:
            return await self._sync_index(trigger=trigger)
        except OperationalError as exc:
            if not is_missing_table_error(
                exc,
                "feiniu_media_index",
                "feiniu_tv_episode_index",
                "feiniu_sync_state",
            ):
                raise
            await self._ensure_tables()
            return await self._sync_index(trigger=trigger)

    async def _sync_index(self, trigger: str = "manual") -> dict[str, Any]:
        async with self._lock:
            started_ts = time.perf_counter()
            started_at = beijing_now()
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="feiniu_sync",
                action="feiniu.index.sync.start",
                status="info",
                message=f"飞牛全量索引同步开始（触发方式：{trigger}）",
                extra={"trigger": trigger},
            )
            async with async_session_maker() as db:
                state = await self._get_or_create_state(db)
                state.status = "running"
                state.enabled = runtime_settings_service.get_feiniu_sync_enabled()
                state.interval_hours = (
                    runtime_settings_service.get_feiniu_sync_interval_hours()
                )
                state.last_trigger = str(trigger or "manual")
                state.last_sync_started_at = started_at
                state.last_sync_finished_at = None
                state.last_sync_error = None
                await db.commit()

            try:
                sync_payload = await self._collect_feiniu_snapshot()

                # 带重试写入快照，应对"database is locked"
                for retry in range(3):
                    try:
                        await self._replace_snapshot(
                            sync_payload, started_at, trigger, started_ts
                        )
                        break
                    except OperationalError as exc:
                        if "database is locked" not in str(exc).lower() or retry >= 2:
                            raise
                        delay = 1.0 * (2 ** retry)
                        logger.warning(
                            "飞牛同步写入时数据库锁定，%0.1f秒后重试（%d/3）", delay, retry + 1
                        )
                        await asyncio.sleep(delay)
                await self._clear_runtime_caches()
                from app.services.tv_missing_service import tv_missing_service

                asyncio.create_task(
                    tv_missing_service.precompute_all_active_tv_missing_cache()
                )
                # 同步完成后清理已在影视库中的订阅
                # 给 SQLite WAL checkpoint 一点时间释放写锁，避免 cleanup commit 时 "database is locked"
                await asyncio.sleep(2.0)
                try:
                    from app.services.subscription_service import subscription_service
                    async with async_session_maker() as cleanup_db:
                        cleanup_result = await subscription_service.cleanup_completed_subscriptions(cleanup_db)
                        if cleanup_result.get("deleted_count"):
                            logger.info(
                                "飞牛同步后清理订阅：删除 %d 项", cleanup_result["deleted_count"]
                            )
                except Exception:
                    logger.exception("飞牛同步后清理订阅失败")
                movie_count = len(sync_payload["movie_rows"])
                tv_count = len(sync_payload["tv_rows"])
                episode_count = len(sync_payload["episode_rows"])
                elapsed_ms = int((time.perf_counter() - started_ts) * 1000)
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="feiniu_sync",
                    action="feiniu.index.sync.success",
                    status="success",
                    message=f"飞牛全量索引同步完成：电影 {movie_count}，剧集 {tv_count}，单集 {episode_count}，耗时 {elapsed_ms}ms",
                    extra={
                        "trigger": trigger,
                        "movie_count": movie_count,
                        "tv_count": tv_count,
                        "episode_count": episode_count,
                        "elapsed_ms": elapsed_ms,
                    },
                )
                return {
                    "success": True,
                    "message": "飞牛全量同步完成",
                    "movie_count": movie_count,
                    "tv_count": tv_count,
                    "episode_count": episode_count,
                }
            except Exception as exc:
                logger.exception("feiniu sync index failed")
                elapsed_ms = int((time.perf_counter() - started_ts) * 1000)
                async with async_session_maker() as db:
                    state = await self._get_or_create_state(db)
                    state.status = "failed"
                    state.enabled = runtime_settings_service.get_feiniu_sync_enabled()
                    state.interval_hours = (
                        runtime_settings_service.get_feiniu_sync_interval_hours()
                    )
                    state.last_trigger = str(trigger or "manual")
                    state.last_sync_finished_at = beijing_now()
                    state.last_sync_duration_ms = elapsed_ms
                    state.last_sync_error = str(exc)[:2000]
                    await db.commit()
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="feiniu_sync",
                    action="feiniu.index.sync.failed",
                    status="failed",
                    message=f"飞牛全量索引同步失败：{str(exc)[:200]}",
                    extra={
                        "trigger": trigger,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc)[:300],
                    },
                )
                return {
                    "success": False,
                    "message": str(exc),
                    "elapsed_ms": elapsed_ms,
                }

    async def start_background_sync(self, trigger: str = "manual") -> dict[str, Any]:
        if not runtime_settings_service.has_feiniu_sync_credentials():
            return {
                "success": False,
                "started": False,
                "message": "飞牛未配置或未登录，无法启动同步",
                "status": await self.get_status(),
            }
        if self._is_running():
            status = await self.get_status()
            return {
                "success": True,
                "started": False,
                "message": "飞牛同步任务已在运行",
                "status": status,
            }

        async def _runner() -> None:
            try:
                await self.sync_index(trigger=trigger)
            finally:
                self._background_task = None

        self._background_task = asyncio.create_task(_runner())
        return {
            "success": True,
            "started": True,
            "message": "飞牛同步任务已启动",
            "status": await self.get_status(),
        }

    def _is_running(self) -> bool:
        return self._background_task is not None and not self._background_task.done()

    async def _collect_feiniu_snapshot(self) -> dict[str, Any]:
        if not runtime_settings_service.get_feiniu_url():
            raise ValueError("飞牛未配置，无法执行全量同步")
        if not await feiniu_service.ensure_authenticated():
            raise ValueError("飞牛尚未登录或自动换票失败，无法执行全量同步")

        items = await feiniu_service.fetch_all_items()

        movie_index: dict[int, set[str]] = {}
        tv_index: dict[int, set[str]] = {}
        tv_targets: list[tuple[int, str]] = []
        for item in items:
            media_type = self._normalize_media_type(item.get("type"))
            tmdb_id = self._extract_tmdb_id(item)
            item_guid = str(item.get("guid") or "").strip()
            if not media_type or not tmdb_id or not item_guid:
                continue
            if media_type == "movie":
                movie_index.setdefault(tmdb_id, set()).add(item_guid)
                continue
            tv_index.setdefault(tmdb_id, set()).add(item_guid)
            tv_targets.append((tmdb_id, item_guid))

        semaphore = asyncio.Semaphore(FEINIU_SYNC_EPISODE_FETCH_CONCURRENCY)

        async def _fetch_tv_episodes(
            tmdb_id: int, tv_guid: str
        ) -> tuple[int, set[tuple[int, int]]]:
            async with semaphore:
                seasons_payload = await feiniu_service.list_seasons(tv_guid)
                if not seasons_payload.get("success"):
                    return tmdb_id, set()
                seasons = seasons_payload.get("data") or []
                episodes: set[tuple[int, int]] = set()
                for season in seasons:
                    season_guid = str((season or {}).get("guid") or "").strip()
                    if not season_guid:
                        continue
                    episode_payload = await feiniu_service.list_episodes(season_guid)
                    if not episode_payload.get("success"):
                        continue
                    for episode in episode_payload.get("data") or []:
                        season_number = int(
                            (episode or {}).get("season_number")
                            or (episode or {}).get("seasonNumber")
                            or 0
                        )
                        episode_number = int(
                            (episode or {}).get("episode_number")
                            or (episode or {}).get("episodeNumber")
                            or 0
                        )
                        if season_number > 0 and episode_number > 0:
                            episodes.add((season_number, episode_number))
                return tmdb_id, episodes

        tv_episode_index: dict[int, set[tuple[int, int]]] = {}
        episode_results = await asyncio.gather(
            *[_fetch_tv_episodes(tmdb_id, tv_guid) for tmdb_id, tv_guid in tv_targets]
        )
        for tmdb_id, extracted in episode_results:
            if extracted:
                tv_episode_index.setdefault(tmdb_id, set()).update(extracted)

        return {
            "movie_rows": [
                {
                    "media_type": "movie",
                    "tmdb_id": tmdb_id,
                    "item_ids": sorted(item_ids),
                }
                for tmdb_id, item_ids in movie_index.items()
            ],
            "tv_rows": [
                {
                    "media_type": "tv",
                    "tmdb_id": tmdb_id,
                    "item_ids": sorted(item_ids),
                }
                for tmdb_id, item_ids in tv_index.items()
            ],
            "episode_rows": [
                {
                    "tmdb_id": tmdb_id,
                    "season_number": int(season_number),
                    "episode_number": int(episode_number),
                }
                for tmdb_id, pairs in tv_episode_index.items()
                for season_number, episode_number in sorted(
                    pairs, key=lambda item: (item[0], item[1])
                )
            ],
        }

    async def _replace_snapshot(
        self,
        payload: dict[str, Any],
        started_at: datetime,
        trigger: str,
        started_ts: float,
    ) -> None:
        finished_at = beijing_now()
        elapsed_ms = int((time.perf_counter() - started_ts) * 1000)
        movie_rows = payload.get("movie_rows") or []
        tv_rows = payload.get("tv_rows") or []
        episode_rows = payload.get("episode_rows") or []
        now = beijing_now()

        # 第一步：在单独事务中快速完成删除，尽早释放写锁
        async with async_session_maker() as db:
            await db.execute(delete(FeiniuTvEpisodeIndex))
            await db.execute(delete(FeiniuMediaIndex))
            await db.commit()

        # 第二步：在新事务中批量插入，穿插定期提交减少单次事务持锁时间
        BATCH_SIZE = 200
        async with async_session_maker() as db:
            for i, row in enumerate(movie_rows):
                item_ids = [
                    str(item_id).strip()
                    for item_id in row.get("item_ids") or []
                    if str(item_id).strip()
                ]
                db.add(
                    FeiniuMediaIndex(
                        media_type="movie",
                        tmdb_id=int(row["tmdb_id"]),
                        feiniu_item_ids_json=json.dumps(item_ids, ensure_ascii=False),
                        item_count=len(item_ids),
                        last_seen_at=now,
                    )
                )
                if (i + 1) % BATCH_SIZE == 0:
                    await db.commit()

            for i, row in enumerate(tv_rows):
                item_ids = [
                    str(item_id).strip()
                    for item_id in row.get("item_ids") or []
                    if str(item_id).strip()
                ]
                db.add(
                    FeiniuMediaIndex(
                        media_type="tv",
                        tmdb_id=int(row["tmdb_id"]),
                        feiniu_item_ids_json=json.dumps(item_ids, ensure_ascii=False),
                        item_count=len(item_ids),
                        last_seen_at=now,
                    )
                )
                if (i + 1) % BATCH_SIZE == 0:
                    await db.commit()

            for i, row in enumerate(episode_rows):
                db.add(
                    FeiniuTvEpisodeIndex(
                        tmdb_id=int(row["tmdb_id"]),
                        season_number=int(row["season_number"]),
                        episode_number=int(row["episode_number"]),
                        last_seen_at=now,
                    )
                )
                if (i + 1) % BATCH_SIZE == 0:
                    await db.commit()

            state = await self._get_or_create_state(db)
            state.status = "success"
            state.enabled = runtime_settings_service.get_feiniu_sync_enabled()
            state.interval_hours = (
                runtime_settings_service.get_feiniu_sync_interval_hours()
            )
            state.last_trigger = str(trigger or "manual")
            state.last_sync_started_at = started_at
            state.last_sync_finished_at = finished_at
            state.last_successful_sync_at = finished_at
            state.last_sync_duration_ms = elapsed_ms
            state.last_sync_error = None
            state.movie_count = len(movie_rows)
            state.tv_count = len(tv_rows)
            state.episode_count = len(episode_rows)
            await db.commit()

    async def _get_or_create_state(self, db) -> FeiniuSyncState:
        state = await db.get(FeiniuSyncState, FEINIU_SYNC_STATE_ROW_ID)
        if state is not None:
            return state
        state = FeiniuSyncState(
            id=FEINIU_SYNC_STATE_ROW_ID,
            status="idle",
            enabled=runtime_settings_service.get_feiniu_sync_enabled(),
            interval_hours=runtime_settings_service.get_feiniu_sync_interval_hours(),
        )
        db.add(state)
        await db.flush()
        return state

    @staticmethod
    def _normalize_media_type(raw_media_type: Any) -> str:
        value = str(raw_media_type or "").strip().lower()
        if value == "movie":
            return "movie"
        if value == "tv":
            return "tv"
        return ""

    @staticmethod
    def _extract_tmdb_id(item: dict[str, Any]) -> int | None:
        trim_id = str((item or {}).get("trim_id") or "").strip().lower()
        if not trim_id:
            return None
        matched = re.search(r"(\d+)$", trim_id)
        if not matched:
            return None
        try:
            tmdb_id = int(matched.group(1))
        except Exception:
            return None
        return tmdb_id if tmdb_id > 0 else None

    @staticmethod
    def _parse_json_list(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            value = json.loads(raw_value)
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _serialize_state(state: FeiniuSyncState, running: bool) -> dict[str, Any]:
        return {
            "status": state.status,
            "running": running or state.status == "running",
            "enabled": runtime_settings_service.get_feiniu_sync_enabled(),
            "interval_hours": runtime_settings_service.get_feiniu_sync_interval_hours(),
            "last_trigger": state.last_trigger,
            "last_sync_started_at": state.last_sync_started_at.isoformat()
            if state.last_sync_started_at
            else None,
            "last_sync_finished_at": state.last_sync_finished_at.isoformat()
            if state.last_sync_finished_at
            else None,
            "last_successful_sync_at": state.last_successful_sync_at.isoformat()
            if state.last_successful_sync_at
            else None,
            "last_sync_duration_ms": state.last_sync_duration_ms,
            "last_sync_error": state.last_sync_error,
            "movie_count": int(state.movie_count or 0),
            "tv_count": int(state.tv_count or 0),
            "episode_count": int(state.episode_count or 0),
            "has_snapshot": state.last_successful_sync_at is not None,
        }

    async def _clear_runtime_caches(self) -> None:
        from app.api import search as search_api
        from app.services.tv_missing_service import tv_missing_service

        search_api._feiniu_badge_cache.clear()
        tv_missing_service.clear_cache()


feiniu_sync_index_service = FeiniuSyncIndexService()
