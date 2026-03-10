from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import delete, select

from app.core.database import async_session_maker
from app.models.emby_sync_index import EmbyMediaIndex, EmbySyncState, EmbyTvEpisodeIndex
from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)

EMBY_SYNC_STATE_ROW_ID = 1
EMBY_SYNC_EPISODE_FETCH_CONCURRENCY = 8


class EmbySyncIndexService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._background_task: asyncio.Task | None = None

    async def get_status(self) -> dict[str, Any]:
        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            await db.commit()
            return self._serialize_state(state, running=self._is_running())

    async def has_successful_snapshot(self) -> bool:
        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            await db.commit()
            return state.last_successful_sync_at is not None

    async def get_movie_status(self, tmdb_id: int) -> dict[str, Any] | None:
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
                select(EmbyMediaIndex).where(
                    EmbyMediaIndex.media_type == "movie",
                    EmbyMediaIndex.tmdb_id == normalized_tmdb_id,
                )
            )
            row = result.scalar_one_or_none()
            await db.commit()

        item_ids = self._parse_json_list(row.emby_item_ids_json) if row else []
        exists = bool(item_ids)
        return {
            "status": "ok",
            "message": "查询成功" if exists else "索引中未匹配到该 TMDB 电影",
            "exists": exists,
            "item_ids": item_ids,
            "source": "emby_sync_index",
        }

    async def get_tv_existing_episodes(self, tmdb_id: int) -> dict[str, Any] | None:
        normalized_tmdb_id = int(tmdb_id or 0)
        if normalized_tmdb_id <= 0:
            return {
                "status": "invalid_tmdb",
                "message": "无效的 TMDB ID",
                "existing_episodes": set(),
                "source": "emby_sync_index",
            }

        async with async_session_maker() as db:
            state = await self._get_or_create_state(db)
            if state.last_successful_sync_at is None:
                await db.commit()
                return None
            result = await db.execute(
                select(EmbyTvEpisodeIndex).where(EmbyTvEpisodeIndex.tmdb_id == normalized_tmdb_id)
            )
            rows = result.scalars().all()
            await db.commit()

        existing_episodes = {
            (int(row.season_number), int(row.episode_number))
            for row in rows
        }
        return {
            "status": "ok",
            "message": "查询成功" if existing_episodes else "索引中未匹配到该 TMDB 剧集",
            "existing_episodes": existing_episodes,
            "source": "emby_sync_index",
        }

    async def sync_index(self, trigger: str = "manual") -> dict[str, Any]:
        async with self._lock:
            started_ts = time.perf_counter()
            started_at = datetime.utcnow()
            async with async_session_maker() as db:
                state = await self._get_or_create_state(db)
                state.status = "running"
                state.enabled = runtime_settings_service.get_emby_sync_enabled()
                state.interval_hours = runtime_settings_service.get_emby_sync_interval_hours()
                state.last_trigger = str(trigger or "manual")
                state.last_sync_started_at = started_at
                state.last_sync_finished_at = None
                state.last_sync_error = None
                await db.commit()

            try:
                sync_payload = await self._collect_emby_snapshot()
                await self._replace_snapshot(sync_payload, started_at, trigger, started_ts)
                await self._clear_runtime_caches()
                return {
                    "success": True,
                    "message": "Emby 全量同步完成",
                    "movie_count": len(sync_payload["movie_rows"]),
                    "tv_count": len(sync_payload["tv_rows"]),
                    "episode_count": len(sync_payload["episode_rows"]),
                }
            except Exception as exc:
                logger.exception("emby sync index failed")
                elapsed_ms = int((time.perf_counter() - started_ts) * 1000)
                async with async_session_maker() as db:
                    state = await self._get_or_create_state(db)
                    state.status = "failed"
                    state.enabled = runtime_settings_service.get_emby_sync_enabled()
                    state.interval_hours = runtime_settings_service.get_emby_sync_interval_hours()
                    state.last_trigger = str(trigger or "manual")
                    state.last_sync_finished_at = datetime.utcnow()
                    state.last_sync_duration_ms = elapsed_ms
                    state.last_sync_error = str(exc)[:2000]
                    await db.commit()
                return {
                    "success": False,
                    "message": str(exc),
                    "elapsed_ms": elapsed_ms,
                }

    async def start_background_sync(self, trigger: str = "manual") -> dict[str, Any]:
        if not runtime_settings_service.get_emby_url() or not runtime_settings_service.get_emby_api_key():
            return {
                "success": False,
                "started": False,
                "message": "Emby 未配置，无法启动同步",
                "status": await self.get_status(),
            }
        if self._is_running():
            status = await self.get_status()
            return {
                "success": True,
                "started": False,
                "message": "Emby 同步任务已在运行",
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
            "message": "Emby 同步任务已启动",
            "status": await self.get_status(),
        }

    def _is_running(self) -> bool:
        return self._background_task is not None and not self._background_task.done()

    async def _collect_emby_snapshot(self) -> dict[str, Any]:
        from app.services.emby_service import emby_service

        if not runtime_settings_service.get_emby_url() or not runtime_settings_service.get_emby_api_key():
            raise ValueError("Emby 未配置，无法执行全量同步")

        async with httpx.AsyncClient() as client:
            movies = await emby_service.list_all_movies_with_client(client)
            series = await emby_service.list_all_series_with_client(client)

            movie_index: dict[int, set[str]] = {}
            tv_index: dict[int, set[str]] = {}
            tv_episode_index: dict[int, set[tuple[int, int]]] = {}

            for item in movies:
                tmdb_id = self._extract_tmdb_id(item)
                item_id = str(item.get("Id") or "").strip()
                if not tmdb_id or not item_id:
                    continue
                movie_index.setdefault(tmdb_id, set()).add(item_id)

            series_targets: list[tuple[int, str]] = []
            for item in series:
                tmdb_id = self._extract_tmdb_id(item)
                item_id = str(item.get("Id") or "").strip()
                if not tmdb_id or not item_id:
                    continue
                tv_index.setdefault(tmdb_id, set()).add(item_id)
                series_targets.append((tmdb_id, item_id))

            semaphore = asyncio.Semaphore(EMBY_SYNC_EPISODE_FETCH_CONCURRENCY)

            async def _fetch_series_episodes(tmdb_id: int, series_id: str) -> tuple[int, set[tuple[int, int]]]:
                async with semaphore:
                    episodes = await emby_service.list_series_episodes_with_client(client, series_id)
                return tmdb_id, emby_service.extract_episode_pairs(episodes)

            episode_results = await asyncio.gather(
                *[
                    _fetch_series_episodes(tmdb_id, series_id)
                    for tmdb_id, series_id in series_targets
                ]
            )
            for tmdb_id, extracted in episode_results:
                if not extracted:
                    continue
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
                for season_number, episode_number in sorted(pairs, key=lambda item: (item[0], item[1]))
            ],
        }

    async def _replace_snapshot(
        self,
        payload: dict[str, Any],
        started_at: datetime,
        trigger: str,
        started_ts: float,
    ) -> None:
        finished_at = datetime.utcnow()
        elapsed_ms = int((time.perf_counter() - started_ts) * 1000)
        movie_rows = payload.get("movie_rows") or []
        tv_rows = payload.get("tv_rows") or []
        episode_rows = payload.get("episode_rows") or []
        now = datetime.utcnow()

        async with async_session_maker() as db:
            await db.execute(delete(EmbyTvEpisodeIndex))
            await db.execute(delete(EmbyMediaIndex))

            for row in movie_rows:
                item_ids = [str(item_id).strip() for item_id in row.get("item_ids") or [] if str(item_id).strip()]
                db.add(
                    EmbyMediaIndex(
                        media_type="movie",
                        tmdb_id=int(row["tmdb_id"]),
                        emby_item_ids_json=json.dumps(item_ids, ensure_ascii=False),
                        item_count=len(item_ids),
                        last_seen_at=now,
                    )
                )
            for row in tv_rows:
                item_ids = [str(item_id).strip() for item_id in row.get("item_ids") or [] if str(item_id).strip()]
                db.add(
                    EmbyMediaIndex(
                        media_type="tv",
                        tmdb_id=int(row["tmdb_id"]),
                        emby_item_ids_json=json.dumps(item_ids, ensure_ascii=False),
                        item_count=len(item_ids),
                        last_seen_at=now,
                    )
                )
            for row in episode_rows:
                db.add(
                    EmbyTvEpisodeIndex(
                        tmdb_id=int(row["tmdb_id"]),
                        season_number=int(row["season_number"]),
                        episode_number=int(row["episode_number"]),
                        last_seen_at=now,
                    )
                )

            state = await self._get_or_create_state(db)
            state.status = "success"
            state.enabled = runtime_settings_service.get_emby_sync_enabled()
            state.interval_hours = runtime_settings_service.get_emby_sync_interval_hours()
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

    async def _get_or_create_state(self, db) -> EmbySyncState:
        state = await db.get(EmbySyncState, EMBY_SYNC_STATE_ROW_ID)
        if state is not None:
            return state
        state = EmbySyncState(
            id=EMBY_SYNC_STATE_ROW_ID,
            status="idle",
            enabled=runtime_settings_service.get_emby_sync_enabled(),
            interval_hours=runtime_settings_service.get_emby_sync_interval_hours(),
        )
        db.add(state)
        await db.flush()
        return state

    @staticmethod
    def _extract_tmdb_id(item: dict[str, Any]) -> int | None:
        if not isinstance(item, dict):
            return None
        provider_ids = item.get("ProviderIds")
        if not isinstance(provider_ids, dict):
            provider_ids = {}
        raw_tmdb = (
            provider_ids.get("Tmdb")
            or provider_ids.get("TMDB")
            or provider_ids.get("tmdb")
            or ""
        )
        try:
            normalized = int(str(raw_tmdb).strip())
        except Exception:
            return None
        return normalized if normalized > 0 else None

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
    def _serialize_state(state: EmbySyncState, running: bool) -> dict[str, Any]:
        return {
            "status": state.status,
            "running": running or state.status == "running",
            "enabled": runtime_settings_service.get_emby_sync_enabled(),
            "interval_hours": runtime_settings_service.get_emby_sync_interval_hours(),
            "last_trigger": state.last_trigger,
            "last_sync_started_at": state.last_sync_started_at.isoformat() if state.last_sync_started_at else None,
            "last_sync_finished_at": state.last_sync_finished_at.isoformat() if state.last_sync_finished_at else None,
            "last_successful_sync_at": state.last_successful_sync_at.isoformat() if state.last_successful_sync_at else None,
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

        search_api._emby_badge_cache.clear()
        tv_missing_service.clear_cache()


emby_sync_index_service = EmbySyncIndexService()
