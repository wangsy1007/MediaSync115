import asyncio
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.services.seedhub_service import seedhub_service


class SeedhubTaskService:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._running_by_query: dict[str, str] = {}
        self._result_cache: dict[str, dict[str, Any]] = {}
        self._magnet_cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._global_semaphore = asyncio.Semaphore(20)
        self._task_ttl_seconds = 60 * 60
        self._result_cache_ttl_seconds = 60 * 15
        self._magnet_cache_ttl_seconds = 60 * 60 * 12

    async def start(
        self,
        media_type: str,
        tmdb_id: int,
        keyword_candidates: list[str],
        expected_context: dict[str, Any] | None = None,
        limit: int = 40,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized_media_type = str(media_type or "").strip().lower()
        if normalized_media_type not in {"movie", "tv"}:
            raise ValueError("unsupported media type")

        normalized_limit = max(1, min(int(limit or 40), 80))
        candidates = [
            str(item or "").strip()
            for item in keyword_candidates
            if str(item or "").strip()
        ]
        if not candidates:
            candidates = [f"TMDB {tmdb_id}"]
        else:
            candidates = candidates[:1]
        query_key = self._build_query_key(
            normalized_media_type, tmdb_id, candidates, normalized_limit
        )

        async with self._lock:
            self._prune_locked()

            if not force_refresh:
                cached_result = self._result_cache.get(query_key)
                if cached_result and cached_result.get("expires_at", 0) > time.time():
                    task_id = uuid4().hex
                    now_iso = datetime.utcnow().isoformat()
                    task = {
                        "task_id": task_id,
                        "query_key": query_key,
                        "media_type": normalized_media_type,
                        "tmdb_id": tmdb_id,
                        "keyword": cached_result.get("keyword") or candidates[0],
                        "keyword_candidates": candidates,
                        "expected_context": dict(expected_context or {}),
                        "status": "success",
                        "message": "命中缓存",
                        "items": list(cached_result.get("items") or []),
                        "limit": normalized_limit,
                        "total_candidates": len(cached_result.get("items") or []),
                        "resolved_count": len(cached_result.get("items") or []),
                        "success_count": len(cached_result.get("items") or []),
                        "failed_count": 0,
                        "started_at": now_iso,
                        "finished_at": now_iso,
                        "updated_at": now_iso,
                        "expires_at": time.time() + self._task_ttl_seconds,
                        "error": None,
                        "already_running": False,
                    }
                    self._tasks[task_id] = task
                    return dict(task)

            existing_task_id = self._running_by_query.get(query_key)
            if existing_task_id and existing_task_id in self._tasks:
                existing = dict(self._tasks[existing_task_id])
                existing["already_running"] = True
                return existing

            task_id = uuid4().hex
            now_iso = datetime.utcnow().isoformat()
            task = {
                "task_id": task_id,
                "query_key": query_key,
                "media_type": normalized_media_type,
                "tmdb_id": tmdb_id,
                "keyword": candidates[0],
                "keyword_candidates": candidates,
                "expected_context": dict(expected_context or {}),
                "status": "queued",
                "message": "任务已排队",
                "items": [],
                "limit": normalized_limit,
                "total_candidates": 0,
                "resolved_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "started_at": now_iso,
                "finished_at": None,
                "updated_at": now_iso,
                "expires_at": time.time() + self._task_ttl_seconds,
                "error": None,
                "already_running": False,
            }
            self._tasks[task_id] = task
            self._running_by_query[query_key] = task_id

        asyncio.create_task(self._run_task(task_id))
        return dict(task)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return dict(task)

    async def cancel(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task.get("status") in {
                "success",
                "failed",
                "partial_success",
                "cancelled",
            }:
                return dict(task)

            now_iso = datetime.utcnow().isoformat()
            task["status"] = "cancelled"
            task["message"] = "任务已取消"
            task["finished_at"] = now_iso
            task["updated_at"] = now_iso
            query_key = str(task.get("query_key") or "")
            if query_key and self._running_by_query.get(query_key) == task_id:
                self._running_by_query.pop(query_key, None)
            return dict(task)

    async def _run_task(self, task_id: str) -> None:
        task = await self.get(task_id)
        if not task:
            return

        query_key = str(task.get("query_key") or "")
        keyword_candidates = list(task.get("keyword_candidates") or [])
        expected_context = dict(task.get("expected_context") or {})
        limit = int(task.get("limit") or 40)
        seen_magnets: set[str] = set()

        await self._update_task(
            task_id,
            {
                "status": "running",
                "message": "正在抓取 SeedHub 资源",
            },
        )

        try:
            for keyword in keyword_candidates:
                current = await self.get(task_id)
                if not current or current.get("status") == "cancelled":
                    return

                await self._update_task(
                    task_id, {"keyword": keyword, "message": f"正在搜索: {keyword}"}
                )

                movie_ids = await seedhub_service._search_movie_ids(
                    keyword, limit=1, expected_context=expected_context
                )
                if not movie_ids:
                    continue

                for movie_id in movie_ids:
                    current = await self.get(task_id)
                    if not current or current.get("status") == "cancelled":
                        return
                    if len(current.get("items") or []) >= limit:
                        break

                    entries = await seedhub_service._fetch_seed_entries(movie_id)
                    if not entries:
                        continue

                    await self._increment(task_id, {"total_candidates": len(entries)})

                    per_task_semaphore = asyncio.Semaphore(4)

                    async def resolve_entry(entry: dict[str, Any]) -> None:
                        current_inner = await self.get(task_id)
                        if (
                            not current_inner
                            or current_inner.get("status") == "cancelled"
                        ):
                            return
                        if len(current_inner.get("items") or []) >= limit:
                            return

                        async with self._global_semaphore:
                            async with per_task_semaphore:
                                magnet = await self._resolve_magnet_cached(
                                    str(entry.get("seed_id") or "")
                                )

                        await self._increment(task_id, {"resolved_count": 1})
                        if not magnet:
                            await self._increment(task_id, {"failed_count": 1})
                            return

                        magnet_key = magnet.lower()
                        if magnet_key in seen_magnets:
                            return
                        seen_magnets.add(magnet_key)

                        item = {
                            "id": f"seedhub-{entry.get('seed_id')}",
                            "name": entry.get("title")
                            or f"SeedHub 资源 #{entry.get('seed_id')}",
                            "title": entry.get("title")
                            or f"SeedHub 资源 #{entry.get('seed_id')}",
                            "size": entry.get("size") or "",
                            "magnet": magnet,
                            "source_service": "seedhub",
                            "seed_id": str(entry.get("seed_id") or ""),
                            "updated_at": entry.get("updated_at") or "",
                            "movie_id": str(movie_id),
                        }
                        await self._append_item(task_id, item, limit)

                    await asyncio.gather(
                        *(resolve_entry(entry) for entry in entries),
                        return_exceptions=True,
                    )

                    current = await self.get(task_id)
                    if current and len(current.get("items") or []) >= limit:
                        break

                current = await self.get(task_id)
                if current and len(current.get("items") or []) >= limit:
                    break

            latest = await self.get(task_id)
            if not latest:
                return
            if latest.get("status") == "cancelled":
                return

            items = list(latest.get("items") or [])
            now_iso = datetime.utcnow().isoformat()
            final_status = "success" if items else "partial_success"
            final_message = "资源获取完成" if items else "未找到可用磁链"
            await self._update_task(
                task_id,
                {
                    "status": final_status,
                    "message": final_message,
                    "finished_at": now_iso,
                    "updated_at": now_iso,
                },
            )

            async with self._lock:
                if items:
                    self._result_cache[query_key] = {
                        "items": items,
                        "keyword": str(latest.get("keyword") or ""),
                        "expires_at": time.time() + self._result_cache_ttl_seconds,
                    }
                current_task_id = self._running_by_query.get(query_key)
                if current_task_id == task_id:
                    self._running_by_query.pop(query_key, None)
        except Exception as exc:
            now_iso = datetime.utcnow().isoformat()
            await self._update_task(
                task_id,
                {
                    "status": "failed",
                    "message": "SeedHub 检索失败",
                    "error": str(exc),
                    "finished_at": now_iso,
                    "updated_at": now_iso,
                },
            )
            async with self._lock:
                current_task_id = self._running_by_query.get(query_key)
                if current_task_id == task_id:
                    self._running_by_query.pop(query_key, None)

    async def _resolve_magnet_cached(self, seed_id: str) -> str:
        normalized_seed_id = str(seed_id or "").strip()
        if not normalized_seed_id:
            return ""

        async with self._lock:
            cached = self._magnet_cache.get(normalized_seed_id)
            if cached and cached.get("expires_at", 0) > time.time():
                return str(cached.get("magnet") or "")

        magnet = await seedhub_service._resolve_magnet(normalized_seed_id)
        if not magnet:
            return ""

        async with self._lock:
            self._magnet_cache[normalized_seed_id] = {
                "magnet": magnet,
                "expires_at": time.time() + self._magnet_cache_ttl_seconds,
            }
        return magnet

    async def _append_item(
        self, task_id: str, item: dict[str, Any], limit: int
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            items = list(task.get("items") or [])
            if len(items) >= limit:
                return
            items.append(item)
            task["items"] = items
            task["success_count"] = len(items)
            task["updated_at"] = datetime.utcnow().isoformat()

    async def _increment(self, task_id: str, fields: dict[str, int]) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            for key, delta in fields.items():
                current = int(task.get(key) or 0)
                task[key] = current + int(delta or 0)
            task["updated_at"] = datetime.utcnow().isoformat()

    async def _update_task(self, task_id: str, patch: dict[str, Any]) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(patch)
            task["updated_at"] = datetime.utcnow().isoformat()

    def _prune_locked(self) -> None:
        now = time.time()
        for task_id in list(self._tasks.keys()):
            task = self._tasks.get(task_id)
            if not task:
                continue
            if float(task.get("expires_at") or 0) <= now:
                self._tasks.pop(task_id, None)

        for key in list(self._result_cache.keys()):
            cached = self._result_cache.get(key)
            if not cached:
                continue
            if float(cached.get("expires_at") or 0) <= now:
                self._result_cache.pop(key, None)

        for key in list(self._magnet_cache.keys()):
            cached = self._magnet_cache.get(key)
            if not cached:
                continue
            if float(cached.get("expires_at") or 0) <= now:
                self._magnet_cache.pop(key, None)

        if len(self._tasks) <= 500:
            return
        finished_ids = [
            task_id
            for task_id, item in self._tasks.items()
            if item.get("status")
            in {"success", "failed", "partial_success", "cancelled"}
        ]
        for task_id in finished_ids[: len(self._tasks) - 500]:
            self._tasks.pop(task_id, None)

    @staticmethod
    def _build_query_key(
        media_type: str, tmdb_id: int, keyword_candidates: list[str], limit: int
    ) -> str:
        head_keyword = (
            keyword_candidates[0] if keyword_candidates else f"TMDB {tmdb_id}"
        )
        return f"{media_type}:{tmdb_id}:{head_keyword}:{limit}"


seedhub_task_service = SeedhubTaskService()
