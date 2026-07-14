import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_maker
from app.models.models import MediaType, Subscription
from app.services.douban_explore_service import resolve_douban_explore_item
from app.services.media_postprocess_service import media_postprocess_service
from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import pan115_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.transfer_intent_service import transfer_intent_service
from app.core.timezone_utils import beijing_now

logger = logging.getLogger(__name__)


class ExploreActionQueueService:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._subscribe_queue: list[str] = []
        self._save_queue: list[str] = []
        self._subscribe_active_by_key: dict[str, str] = {}
        self._save_active_by_key: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._subscribe_worker_task: asyncio.Task | None = None
        self._save_worker_task: asyncio.Task | None = None
        self._task_ttl_seconds = 60 * 60 * 3
        self._save_archive_deferred = False
        self._deferred_idle_actions: dict[str, Callable[[], Awaitable[Any]]] = {}

    @staticmethod
    def _now_iso() -> str:
        return beijing_now().isoformat()

    @staticmethod
    def _normalize_media_type(raw: str) -> str:
        return "tv" if str(raw or "").strip().lower() == "tv" else "movie"

    @staticmethod
    def _normalize_year(raw: Any) -> str:
        text = str(raw or "").strip()[:4]
        return text if text.isdigit() else ""

    @staticmethod
    def _normalize_rating(raw: Any) -> float | None:
        try:
            value = float(raw)
        except Exception:
            return None
        return value if value >= 0 else None

    @staticmethod
    def _extract_receive_code(share_link: str) -> str:
        value = str(share_link or "").strip()
        if not value:
            return ""

        short_match = re.match(r"^[A-Za-z0-9]+-([A-Za-z0-9]{4})$", value)
        if short_match:
            return short_match.group(1)

        query_match = re.search(
            r"[?&](?:password|pwd|receive_code|pickcode|code)=([^&#]+)",
            value,
            re.IGNORECASE,
        )
        if query_match:
            return query_match.group(1).strip()

        text_match = re.search(
            r"(?:提取码|提取碼|访问码|訪問碼|密码|密碼)\s*[:：=]?\s*([A-Za-z0-9]{4})",
            value,
            re.IGNORECASE,
        )
        if text_match:
            return text_match.group(1).strip()

        return ""

    @staticmethod
    def _build_item_key_from_payload(payload: dict[str, Any]) -> str:
        media_type = ExploreActionQueueService._normalize_media_type(
            payload.get("media_type")
        )
        tmdb_id = payload.get("tmdb_id")
        try:
            parsed_tmdb_id = int(tmdb_id)
        except Exception:
            parsed_tmdb_id = 0
        if parsed_tmdb_id > 0:
            return f"tmdb:{media_type}:{parsed_tmdb_id}"

        douban_id = str(payload.get("douban_id") or payload.get("id") or "").strip()
        if douban_id:
            return f"douban:{media_type}:{douban_id}"
        return f"unknown:{media_type}:{uuid4().hex[:8]}"

    @staticmethod
    def _build_item_key(
        media_type: str, tmdb_id: int | None, douban_id: str = ""
    ) -> str:
        normalized_type = ExploreActionQueueService._normalize_media_type(media_type)
        if tmdb_id and int(tmdb_id) > 0:
            return f"tmdb:{normalized_type}:{int(tmdb_id)}"
        if douban_id:
            return f"douban:{normalized_type}:{douban_id}"
        return f"unknown:{normalized_type}:{uuid4().hex[:8]}"

    @staticmethod
    def _serialize_task(task: dict[str, Any]) -> dict[str, Any]:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        return {
            "task_id": str(task.get("task_id") or ""),
            "queue_type": str(task.get("queue_type") or ""),
            "item_key": str(task.get("item_key") or ""),
            "status": str(task.get("status") or "queued"),
            "intent": str(task.get("intent") or ""),
            "message": str(task.get("message") or ""),
            "error": str(task.get("error") or ""),
            "item_title": str(payload.get("title") or payload.get("name") or ""),
            "media_type": ExploreActionQueueService._normalize_media_type(
                payload.get("media_type")
            ),
            "tmdb_id": result.get("tmdb_id") or payload.get("tmdb_id"),
            "douban_id": str(payload.get("douban_id") or payload.get("id") or ""),
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "updated_at": task.get("updated_at"),
            "finished_at": task.get("finished_at"),
        }

    @staticmethod
    def _build_task_log_extra(
        task: dict[str, Any], extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        merged: dict[str, Any] = {
            "task_id": str(task.get("task_id") or ""),
            "queue_type": str(task.get("queue_type") or ""),
            "task_status": str(task.get("status") or ""),
            "intent": str(task.get("intent") or ""),
            "item_key": str(task.get("item_key") or ""),
            "item_title": str(payload.get("title") or payload.get("name") or ""),
            "media_type": ExploreActionQueueService._normalize_media_type(
                payload.get("media_type")
            ),
            "tmdb_id": result.get("tmdb_id") or payload.get("tmdb_id"),
            "douban_id": str(payload.get("douban_id") or payload.get("id") or ""),
            "error": str(task.get("error") or ""),
        }
        if (
            isinstance(result.get("selected_source"), str)
            and str(result.get("selected_source")).strip()
        ):
            merged["selected_source"] = str(result.get("selected_source")).strip()
        if isinstance(result.get("source_order"), list):
            merged["source_order"] = [
                str(item) for item in result.get("source_order")[:10]
            ]
        if isinstance(result.get("attempts"), list):
            merged["attempts"] = result.get("attempts")[:20]
        save_mode = str(result.get("save_mode") or "").strip()
        if not save_mode and str(task.get("queue_type") or "") == "save":
            save_mode = "direct"
        if save_mode:
            merged["save_mode"] = save_mode
        target_parent_id = result.get("target_parent_id")
        if target_parent_id is None and str(task.get("queue_type") or "") == "save":
            folder = runtime_settings_service.get_pan115_default_folder()
            target_parent_id = folder.get("folder_id")
        if target_parent_id is not None:
            merged["target_parent_id"] = str(target_parent_id or "")
        if extra:
            merged.update(extra)
        return merged

    async def _log_task_event(
        self,
        task: dict[str, Any],
        *,
        stage: str,
        status: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        queue_type = str(task.get("queue_type") or "unknown").strip() or "unknown"
        task_id = str(task.get("task_id") or "background")
        try:
            await operation_log_service.log_background_event(
                source_type="explore_queue",
                module="explore_queue",
                action=f"explore.queue.{queue_type}.{stage}",
                status=status,
                message=message,
                trace_id=task_id,
                extra=self._build_task_log_extra(task, extra),
            )
        except Exception as exc:
            logger.exception("failed to write explore queue operation log: %s", exc)

    async def _ensure_workers(self) -> None:
        async with self._lock:
            if (
                self._subscribe_worker_task is None
                or self._subscribe_worker_task.done()
            ):
                self._subscribe_worker_task = asyncio.create_task(
                    self._subscribe_worker()
                )
            if self._save_worker_task is None or self._save_worker_task.done():
                self._save_worker_task = asyncio.create_task(self._save_worker())

    async def _prune_locked(self) -> None:
        now = time.time()
        expired_ids = [
            task_id
            for task_id, task in self._tasks.items()
            if float(task.get("expires_at") or 0) <= now
        ]
        if not expired_ids:
            return

        for task_id in expired_ids:
            self._tasks.pop(task_id, None)

        self._subscribe_queue = [
            task_id for task_id in self._subscribe_queue if task_id in self._tasks
        ]
        self._save_queue = [
            task_id for task_id in self._save_queue if task_id in self._tasks
        ]

        self._subscribe_active_by_key = {
            key: task_id
            for key, task_id in self._subscribe_active_by_key.items()
            if task_id in self._tasks
        }
        self._save_active_by_key = {
            key: task_id
            for key, task_id in self._save_active_by_key.items()
            if task_id in self._tasks
        }

    async def enqueue_subscribe(
        self, payload: dict[str, Any], intent: str
    ) -> dict[str, Any]:
        await self._ensure_workers()
        normalized_intent = (
            "unsubscribe"
            if str(intent or "").strip().lower() == "unsubscribe"
            else "subscribe"
        )
        item_key = self._build_item_key_from_payload(payload)
        now = self._now_iso()
        queue_size = 0
        task: dict[str, Any] | None = None
        duplicate_task: dict[str, Any] | None = None

        async with self._lock:
            await self._prune_locked()
            existing_id = self._subscribe_active_by_key.get(item_key)
            if existing_id and existing_id in self._tasks:
                existing_task = self._tasks[existing_id]
                if existing_task.get("status") in {"queued", "running"}:
                    existing_task["payload"] = dict(payload)
                    existing_task["intent"] = normalized_intent
                    existing_task["updated_at"] = now
                    existing_task["message"] = "已更新为最后一次操作意图"
                    existing_task["expires_at"] = time.time() + self._task_ttl_seconds
                    duplicate_task = dict(existing_task)
                    queue_size = len(self._subscribe_queue)

            if duplicate_task is None:
                task_id = uuid4().hex
                task = {
                    "task_id": task_id,
                    "queue_type": "subscribe",
                    "status": "queued",
                    "item_key": item_key,
                    "intent": normalized_intent,
                    "message": "已加入订阅队列",
                    "payload": dict(payload),
                    "result": {},
                    "error": "",
                    "created_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "finished_at": None,
                    "expires_at": time.time() + self._task_ttl_seconds,
                }
                self._tasks[task_id] = task
                self._subscribe_queue.append(task_id)
                self._subscribe_active_by_key[item_key] = task_id
                queue_size = len(self._subscribe_queue)

        if duplicate_task is not None:
            await self._log_task_event(
                duplicate_task,
                stage="enqueue",
                status="queued",
                message="订阅任务已在队列中，已更新为最后一次操作意图",
                extra={"queue_size": queue_size},
            )
            return self._serialize_task(duplicate_task)

        if task is None:
            raise RuntimeError("subscribe queue enqueue failed")

        await self._log_task_event(
            task,
            stage="enqueue",
            status="queued",
            message="订阅任务已加入队列",
            extra={"queue_size": queue_size},
        )
        return self._serialize_task(task)

    async def enqueue_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_workers()
        item_key = self._build_item_key_from_payload(payload)
        now = self._now_iso()
        queue_size = 0
        task: dict[str, Any] | None = None
        duplicate_task: dict[str, Any] | None = None

        async with self._lock:
            await self._prune_locked()
            existing_id = self._save_active_by_key.get(item_key)
            if existing_id and existing_id in self._tasks:
                existing_task = self._tasks[existing_id]
                if existing_task.get("status") in {"queued", "running"}:
                    existing_task["updated_at"] = now
                    existing_task["message"] = "该条目已在转存队列中"
                    existing_task["expires_at"] = time.time() + self._task_ttl_seconds
                    duplicate_task = dict(existing_task)
                    queue_size = len(self._save_queue)

            if duplicate_task is None:
                task_id = uuid4().hex
                task = {
                    "task_id": task_id,
                    "queue_type": "save",
                    "status": "queued",
                    "item_key": item_key,
                    "intent": "save",
                    "message": "已加入转存队列",
                    "payload": dict(payload),
                    "result": {},
                    "error": "",
                    "created_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "finished_at": None,
                    "expires_at": time.time() + self._task_ttl_seconds,
                }
                self._tasks[task_id] = task
                self._save_queue.append(task_id)
                self._save_active_by_key[item_key] = task_id
                queue_size = len(self._save_queue)

        if duplicate_task is not None:
            await self._log_task_event(
                duplicate_task,
                stage="enqueue",
                status="queued",
                message="转存任务已在队列中，忽略重复入队",
                extra={"queue_size": queue_size},
            )
            return self._serialize_task(duplicate_task)

        if task is None:
            raise RuntimeError("save queue enqueue failed")

        await self._log_task_event(
            task,
            stage="enqueue",
            status="queued",
            message="转存任务已加入队列",
            extra={"queue_size": queue_size},
        )
        return self._serialize_task(task)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            await self._prune_locked()
            task = self._tasks.get(task_id)
            return self._serialize_task(task) if task else None

    async def list_active(self, queue_type: str = "all") -> dict[str, Any]:
        normalized_type = str(queue_type or "all").strip().lower()
        if normalized_type not in {"all", "subscribe", "save"}:
            normalized_type = "all"

        async with self._lock:
            await self._prune_locked()
            rows: list[dict[str, Any]] = []
            for task in self._tasks.values():
                if task.get("status") not in {"queued", "running"}:
                    continue
                if (
                    normalized_type != "all"
                    and task.get("queue_type") != normalized_type
                ):
                    continue
                rows.append(self._serialize_task(task))
            rows.sort(key=lambda item: str(item.get("created_at") or ""))
            return {"tasks": rows}

    async def _mark_running(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            now = self._now_iso()
            task["status"] = "running"
            task["message"] = "任务执行中"
            task["started_at"] = now
            task["updated_at"] = now
            task["expires_at"] = time.time() + self._task_ttl_seconds
            return dict(task)

    async def _mark_finished(
        self,
        task_id: str,
        *,
        success: bool,
        message: str,
        error: str = "",
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            now = self._now_iso()
            task["status"] = "success" if success else "failed"
            task["message"] = message
            task["error"] = str(error or "")
            task["result"] = dict(result or {})
            task["updated_at"] = now
            task["finished_at"] = now
            task["expires_at"] = time.time() + self._task_ttl_seconds

            item_key = str(task.get("item_key") or "")
            if (
                task.get("queue_type") == "subscribe"
                and self._subscribe_active_by_key.get(item_key) == task_id
            ):
                self._subscribe_active_by_key.pop(item_key, None)
            if (
                task.get("queue_type") == "save"
                and self._save_active_by_key.get(item_key) == task_id
            ):
                self._save_active_by_key.pop(item_key, None)
            return dict(task)

    async def _pop_subscribe_task(self) -> str | None:
        async with self._lock:
            await self._prune_locked()
            if not self._subscribe_queue:
                return None
            return self._subscribe_queue.pop(0)

    async def _pop_save_task(self) -> str | None:
        async with self._lock:
            await self._prune_locked()
            if not self._save_queue:
                return None
            return self._save_queue.pop(0)

    def _is_save_queue_busy_locked(self) -> bool:
        if self._save_queue:
            return True
        return any(
            task.get("queue_type") == "save" and task.get("status") == "running"
            for task in self._tasks.values()
        )

    async def is_save_queue_busy(self) -> bool:
        async with self._lock:
            await self._prune_locked()
            return self._is_save_queue_busy_locked()

    async def defer_until_save_queue_idle(
        self,
        action_key: str,
        action: Callable[[], Awaitable[Any]],
    ) -> bool:
        """转存队列繁忙时将 action 延迟到队列空闲后执行。"""
        normalized_key = str(action_key or "").strip()
        if not normalized_key:
            normalized_key = f"deferred:{uuid4().hex[:8]}"

        async with self._lock:
            await self._prune_locked()
            if not self._is_save_queue_busy_locked():
                return False
            self._deferred_idle_actions[normalized_key] = action
            self._save_archive_deferred = True
            return True

    async def _mark_save_archive_needed(self) -> None:
        async with self._lock:
            self._save_archive_deferred = True

    async def _flush_deferred_when_idle(self) -> None:
        should_flush_archive = False
        deferred_actions: dict[str, Callable[[], Awaitable[Any]]] = {}
        async with self._lock:
            if not self._save_archive_deferred and not self._deferred_idle_actions:
                return
            if self._is_save_queue_busy_locked():
                return

            deferred_actions = dict(self._deferred_idle_actions)
            self._deferred_idle_actions.clear()
            should_flush_archive = self._save_archive_deferred
            self._save_archive_deferred = False

        for action_key, action in deferred_actions.items():
            try:
                await action()
            except Exception:
                logger.exception(
                    "转存队列空闲后执行延迟任务失败: %s", action_key
                )

        if not should_flush_archive:
            return

        try:
            await media_postprocess_service.trigger_archive_after_transfer(
                trigger="explore_transfer",
                respect_save_queue=False,
            )
        except Exception:
            logger.exception("探索转存队列空闲后触发归档失败")

    async def _subscribe_worker(self) -> None:
        while True:
            try:
                task_id = await self._pop_subscribe_task()
                if not task_id:
                    await asyncio.sleep(0.25)
                    continue

                task = await self._mark_running(task_id)
                if not task:
                    continue
                await self._log_task_event(
                    task,
                    stage="start",
                    status="running",
                    message="订阅任务开始执行",
                )

                try:
                    result = await self._execute_subscribe(task)
                    finished_task = await self._mark_finished(
                        task_id,
                        success=True,
                        message=str(result.get("message") or "订阅队列任务执行完成"),
                        result=result,
                    )
                    if finished_task:
                        await self._log_task_event(
                            finished_task,
                            stage="finish",
                            status="success",
                            message=str(
                                finished_task.get("message") or "订阅任务执行完成"
                            ),
                        )
                except Exception as exc:
                    finished_task = await self._mark_finished(
                        task_id,
                        success=False,
                        message="订阅队列任务执行失败",
                        error=str(exc),
                    )
                    if finished_task:
                        await self._log_task_event(
                            finished_task,
                            stage="finish",
                            status="failed",
                            message=f"订阅任务执行失败: {str(exc)}",
                            extra={"error": str(exc)},
                        )
            except Exception as exc:
                logger.exception("subscribe worker loop error: %s", exc)
                await asyncio.sleep(0.5)

    async def _save_worker(self) -> None:
        while True:
            try:
                task_id = await self._pop_save_task()
                if not task_id:
                    await asyncio.sleep(0.25)
                    continue

                task = await self._mark_running(task_id)
                if not task:
                    continue
                await self._log_task_event(
                    task,
                    stage="start",
                    status="running",
                    message="转存任务开始执行",
                )

                try:
                    result = await self._execute_save(task)
                    finished_task = await self._mark_finished(
                        task_id,
                        success=True,
                        message=str(result.get("message") or "转存队列任务执行完成"),
                        result=result,
                    )
                    if finished_task:
                        log_extra = {
                            "share_link": str(result.get("share_link") or ""),
                            "file_count": result.get("file_count"),
                            "original_file_count": result.get("original_file_count"),
                        }
                        await self._log_task_event(
                            finished_task,
                            stage="finish",
                            status="success",
                            message=str(
                                finished_task.get("message") or "转存任务执行完成"
                            ),
                            extra=log_extra,
                        )
                except Exception as exc:
                    finished_task = await self._mark_finished(
                        task_id,
                        success=False,
                        message="转存队列任务执行失败",
                        error=str(exc),
                    )
                    if finished_task:
                        await self._log_task_event(
                            finished_task,
                            stage="finish",
                            status="failed",
                            message=f"转存任务执行失败: {str(exc)}",
                            extra={"error": str(exc)},
                        )
                finally:
                    await self._flush_deferred_when_idle()
            except Exception as exc:
                logger.exception("save worker loop error: %s", exc)
                await asyncio.sleep(0.5)

    async def _resolve_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = str(payload.get("source") or "douban").strip().lower()
        media_type = self._normalize_media_type(payload.get("media_type"))
        raw_tmdb_id = payload.get("tmdb_id")
        tmdb_id: int | None = None
        try:
            parsed_tmdb_id = int(raw_tmdb_id)
            if parsed_tmdb_id > 0:
                tmdb_id = parsed_tmdb_id
        except Exception:
            tmdb_id = None

        douban_id = str(payload.get("douban_id") or "").strip()
        if not douban_id and source == "douban":
            raw_id = str(payload.get("id") or "").strip()
            if raw_id.isdigit():
                douban_id = raw_id

        if source == "tmdb":
            if not tmdb_id:
                raise ValueError("缺少有效的 TMDB ID")
            return {
                "media_type": media_type,
                "tmdb_id": tmdb_id,
                "douban_id": douban_id,
            }

        title = str(payload.get("title") or payload.get("name") or "").strip()
        original_title = str(
            payload.get("original_title") or payload.get("original_name") or ""
        ).strip()
        aliases_payload = payload.get("aliases")
        aliases: list[str] = []
        if isinstance(aliases_payload, list):
            aliases = [
                str(item or "").strip()
                for item in aliases_payload
                if str(item or "").strip()
            ]
        elif isinstance(aliases_payload, str) and aliases_payload.strip():
            aliases = [aliases_payload.strip()]

        douban_id = str(payload.get("douban_id") or payload.get("id") or "").strip()
        year = self._normalize_year(payload.get("year")) or None

        resolve_result = await resolve_douban_explore_item(
            douban_id=douban_id,
            title=title,
            media_type=media_type,
            year=year,
            tmdb_id=None,
            alternative_titles=[original_title, *aliases],
        )
        resolved_tmdb_id = resolve_result.get("tmdb_id")
        try:
            resolved_tmdb_id = int(resolved_tmdb_id)
        except Exception:
            resolved_tmdb_id = 0
        if not resolve_result.get("resolved") or resolved_tmdb_id <= 0:
            reason = str(resolve_result.get("reason") or "resolve_failed")
            if reason == "low_confidence_or_ambiguous":
                raise ValueError("TMDB 匹配冲突，请稍后重试")
            if reason.startswith("subject_cache_unresolved"):
                raise ValueError("未匹配到 TMDB 条目，请稍后重试")
            raise ValueError("未能匹配到有效 TMDB 条目")

        return {
            "media_type": self._normalize_media_type(resolve_result.get("media_type")),
            "tmdb_id": resolved_tmdb_id,
            "douban_id": douban_id,
        }

    async def _execute_subscribe(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task.get("payload") or {})
        intent = (
            "unsubscribe"
            if str(task.get("intent") or "").strip().lower() == "unsubscribe"
            else "subscribe"
        )
        route_info = await self._resolve_route(payload)
        media_type = route_info["media_type"]
        tmdb_id = int(route_info["tmdb_id"])
        douban_id = str(
            route_info.get("douban_id")
            or payload.get("douban_id")
            or payload.get("id")
            or ""
        ).strip()

        media_enum = MediaType.TV if media_type == "tv" else MediaType.MOVIE
        async with async_session_maker() as db:
            conditions = [
                and_(
                    Subscription.tmdb_id == tmdb_id,
                    Subscription.media_type == media_enum,
                )
            ]
            if douban_id:
                conditions.append(Subscription.douban_id == douban_id)
            query = select(Subscription).where(or_(*conditions)).limit(1)
            existing = (await db.execute(query)).scalar_one_or_none()

            if intent == "subscribe":
                if existing:
                    return {
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "subscription_id": existing.id,
                        "subscribed": True,
                        "message": "该影视已在订阅列表中",
                    }

                title = (
                    str(payload.get("title") or payload.get("name") or "").strip()
                    or f"TMDB {tmdb_id}"
                )
                overview = str(
                    payload.get("overview") or payload.get("intro") or ""
                ).strip()
                poster_path = (
                    str(
                        payload.get("poster_path") or payload.get("poster_url") or ""
                    ).strip()
                    or None
                )
                year = self._normalize_year(payload.get("year")) or None
                rating = self._normalize_rating(
                    payload.get("rating") or payload.get("vote_average")
                )

                created = Subscription(
                    douban_id=douban_id or None,
                    tmdb_id=tmdb_id,
                    title=title,
                    media_type=media_enum,
                    poster_path=poster_path,
                    overview=overview,
                    year=year,
                    rating=rating,
                    is_active=True,
                    auto_download=True,
                )
                db.add(created)
                try:
                    await db.commit()
                    await db.refresh(created)
                except IntegrityError:
                    await db.rollback()
                    latest = (await db.execute(query)).scalar_one_or_none()
                    return {
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "subscription_id": int(latest.id) if latest else None,
                        "subscribed": True,
                        "message": "该影视已在订阅列表中",
                    }

                return {
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "subscription_id": created.id,
                    "subscribed": True,
                    "message": "订阅成功",
                }

            if not existing:
                return {
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "subscription_id": None,
                    "subscribed": False,
                    "message": "该影视尚未订阅",
                }

            await db.delete(existing)
            await db.commit()
            return {
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "subscription_id": existing.id,
                "subscribed": False,
                "message": "已取消订阅",
            }

    @staticmethod
    def _build_attempt_error_summary(attempts: list[dict[str, Any]]) -> str:
        if not attempts:
            return "暂未找到可转存资源"
        parts: list[str] = []
        transfer_failures: list[str] = []
        for row in attempts:
            source = str(row.get("source") or "unknown")
            status = str(row.get("status") or "unknown").strip().lower() or "unknown"
            if status in {"failed", "transfer_failed"}:
                error = str(row.get("error") or "").strip()
                transfer_failures.append(f"{source}: {error[:60] or 'failed'}")
            elif status == "empty":
                parts.append(f"{source}: empty")
            elif status == "success":
                count = int(row.get("count") or 0)
                parts.append(f"{source}: success" + (f"({count})" if count else ""))
            if len(parts) >= 4:
                break
        if transfer_failures:
            return f"转存失败（{'; '.join(transfer_failures[:4])}）"
        if not parts:
            return "暂未找到可转存资源"
        return f"暂未找到可转存资源（{'; '.join(parts)}）"

    async def _execute_save(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task.get("payload") or {})
        route_info = await self._resolve_route(payload)
        media_type = route_info["media_type"]
        tmdb_id = int(route_info["tmdb_id"])
        douban_id = str(route_info.get("douban_id") or "").strip()

        from app.services.subscription_service import (
            SubscriptionSnapshot,
            subscription_service,
        )

        title = (
            str(payload.get("title") or payload.get("name") or "").strip()
            or f"TMDB {tmdb_id}"
        )
        year = self._normalize_year(payload.get("year")) or None
        mt = MediaType.TV if media_type == "tv" else MediaType.MOVIE

        snapshot = SubscriptionSnapshot(
            id=0,
            tmdb_id=tmdb_id,
            douban_id=douban_id,
            title=title,
            media_type=mt,
            year=year,
            auto_download=False,
            tv_scope="all",
            tv_season_number=None,
            tv_episode_start=None,
            tv_episode_end=None,
            tv_follow_mode="missing",
            tv_include_specials=False,
            has_successful_transfer=False,
        )

        source_order = subscription_service._resolve_source_order("all")
        source_attempts: list[dict[str, Any]] = []
        transfer_attempts: list[dict[str, Any]] = []

        folder = runtime_settings_service.get_pan115_default_folder()
        folder_id = str(folder.get("folder_id") or "0").strip() or "0"

        for source in source_order:
            primary_resources, _traces, meta = await subscription_service._fetch_resources(
                channel="all",
                sub=snapshot,
                source_order=[source],
            )
            source_attempts.extend(list(meta.get("attempts") or []))
            if not primary_resources:
                continue

            for resource in primary_resources:
                share_link = subscription_service._extract_resource_url(resource)
                if not share_link and not subscription_service._extract_offline_url(resource):
                    transfer_attempts.append(
                        {
                            "source": resource.get("source_service", source),
                            "status": "transfer_failed",
                            "error": "资源缺少可转存链接（HDHive 可能需解锁）",
                        }
                    )
                    continue

                if share_link:
                    receive_code = self._extract_receive_code(share_link)
                    try:
                        from app.utils.resource_tags import (
                            build_quality_filter_from_settings,
                        )

                        quality_filter = build_quality_filter_from_settings()
                        result = await pan115_service.save_share_directly(
                            share_link,
                            folder_id,
                            receive_code,
                            quality_filter,
                            media_type,
                        )
                    except Exception as exc:
                        transfer_attempts.append(
                            {
                                "source": resource.get("source_service", source),
                                "status": "transfer_failed",
                                "error": str(exc)[:300],
                            }
                        )
                        continue

                    transfer_success = True
                    if isinstance(result, dict):
                        if "success" in result:
                            transfer_success = bool(result.get("success"))
                        elif "state" in result:
                            transfer_success = bool(result.get("state"))

                    if not transfer_success:
                        if isinstance(result, dict):
                            error_text = (
                                str(result.get("error") or "")
                                or str(result.get("message") or "")
                                or str(result.get("error_msg") or "")
                            )
                        else:
                            error_text = str(result)
                        transfer_attempts.append(
                            {
                                "source": resource.get("source_service", source),
                                "status": "transfer_failed",
                                "error": (error_text or "转存失败")[:300],
                            }
                        )
                        continue

                    await self._mark_save_archive_needed()
                    resource_label = str(
                        resource.get("name")
                        or resource.get("title")
                        or resource.get("resource_name")
                        or ""
                    ).strip()
                    await transfer_intent_service.register_intent(
                        display_title=title,
                        tmdb_id=tmdb_id,
                        douban_id=douban_id or None,
                        media_type=media_type,
                        target_parent_id=folder_id,
                        resource_name=resource_label or None,
                        source="explore_save",
                    )
                    file_count = (
                        result.get("file_count") if isinstance(result, dict) else None
                    )
                    original_file_count = (
                        result.get("original_file_count")
                        if isinstance(result, dict)
                        else None
                    )
                    return {
                        "tmdb_id": tmdb_id,
                        "media_type": media_type,
                        "share_link": share_link,
                        "selected_source": resource.get("source_service", source),
                        "source_order": source_order,
                        "attempts": source_attempts + transfer_attempts,
                        "save_mode": "direct",
                        "target_parent_id": folder_id,
                        "file_count": file_count,
                        "original_file_count": original_file_count,
                        "message": str(result.get("message") or "已提交转存任务")
                        if isinstance(result, dict)
                        else "已提交转存任务",
                    }

                offline_url = subscription_service._extract_offline_url(resource)
                if offline_url:
                    try:
                        offline_folder_id = str(
                            runtime_settings_service.get_pan115_offline_folder()
                            .get("folder_id", "0")
                            .strip()
                            or "0"
                        )
                        await pan115_service.offline_task_add(
                            url=offline_url,
                            wp_path_id=offline_folder_id,
                        )
                        await self._mark_save_archive_needed()
                        await transfer_intent_service.register_intent(
                            display_title=title,
                            tmdb_id=tmdb_id,
                            douban_id=douban_id or None,
                            media_type=media_type,
                            target_parent_id=offline_folder_id,
                            resource_name=str(offline_url or "").strip() or None,
                            source="explore_save_offline",
                        )
                        return {
                            "tmdb_id": tmdb_id,
                            "media_type": media_type,
                            "share_link": offline_url,
                            "selected_source": resource.get("source_service", "offline"),
                            "source_order": source_order,
                            "attempts": source_attempts + transfer_attempts,
                            "save_mode": "offline",
                            "target_parent_id": offline_folder_id,
                            "message": "已提交离线下载任务",
                        }
                    except Exception as exc:
                        transfer_attempts.append(
                            {
                                "source": resource.get("source_service", "offline"),
                                "status": "transfer_failed",
                                "error": str(exc)[:300],
                            }
                        )
                        continue

        all_attempts = source_attempts + transfer_attempts
        raise ValueError(self._build_attempt_error_summary(all_attempts))


explore_action_queue_service = ExploreActionQueueService()
