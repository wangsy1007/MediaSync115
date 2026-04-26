import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_maker
from app.models.models import MediaType, Subscription
from app.services.douban_explore_service import resolve_douban_explore_item
from app.services.hdhive_service import hdhive_service
from app.services.media_postprocess_service import media_postprocess_service
from app.services.operation_log_service import operation_log_service
from app.services.pan115_service import pan115_service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tg_service import tg_service
from app.utils.resource_tags import sort_by_preference


_PAN115_SHARE_URL_PATTERN = re.compile(
    r"(https?://(?:115(?:cdn)?\.com/s/[A-Za-z0-9]+(?:[^\s\"'<>]*)?|share\.115\.com/[A-Za-z0-9]+(?:[^\s\"'<>]*)?))",
    re.IGNORECASE,
)
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

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

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
    def _sort_by_pref(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pref_res = runtime_settings_service.get_resource_preferred_resolutions()
        pref_fmt = runtime_settings_service.get_resource_preferred_formats()
        if pref_res or pref_fmt:
            return sort_by_preference(rows, pref_res, pref_fmt)
        return rows

    @staticmethod
    def _extract_share_link(row: Any) -> str:
        if not isinstance(row, dict):
            return ""
        for key in (
            "share_link",
            "share_url",
            "pan115_share_link",
            "url",
            "link",
            "resource_url",
        ):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                raw = value.strip()
                url_match = _PAN115_SHARE_URL_PATTERN.search(raw)
                if url_match:
                    return url_match.group(1).strip()
                if re.fullmatch(r"[A-Za-z0-9]{6,32}(?:-[A-Za-z0-9]{4})?", raw):
                    return raw
        return ""

    @staticmethod
    def _extract_pansou_rows(node: Any, depth: int = 0) -> list[dict[str, Any]]:
        if depth > 5:
            return []
        rows: list[dict[str, Any]] = []
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    rows.append(item)
                rows.extend(
                    ExploreActionQueueService._extract_pansou_rows(item, depth + 1)
                )
        elif isinstance(node, dict):
            for value in node.values():
                rows.extend(
                    ExploreActionQueueService._extract_pansou_rows(value, depth + 1)
                )
        return rows

    @staticmethod
    def _extract_share_link_from_pansou_payload(payload: Any) -> str:
        rows = ExploreActionQueueService._extract_pansou_rows(payload)
        for row in rows:
            link = ExploreActionQueueService._extract_share_link(row)
            if link:
                return link
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
                        await self._log_task_event(
                            finished_task,
                            stage="finish",
                            status="success",
                            message=str(
                                finished_task.get("message") or "转存任务执行完成"
                            ),
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

        if source == "tmdb":
            if not tmdb_id:
                raise ValueError("缺少有效的 TMDB ID")
            return {"media_type": media_type, "tmdb_id": tmdb_id, "douban_id": ""}

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
            tmdb_id=tmdb_id,
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
    def _resolve_save_source_order() -> list[str]:
        priority = runtime_settings_service.get_subscription_resource_priority()
        allowed = {"hdhive", "pansou", "tg"}
        source_order: list[str] = []
        seen: set[str] = set()
        for item in priority:
            source = str(item or "").strip().lower()
            if source in allowed and source not in seen:
                source_order.append(source)
                seen.add(source)

        tg_ready = bool(
            runtime_settings_service.get_tg_api_id().strip()
            and runtime_settings_service.get_tg_api_hash().strip()
            and runtime_settings_service.get_tg_session().strip()
            and runtime_settings_service.get_tg_channel_usernames()
        )
        if not tg_ready:
            source_order = [item for item in source_order if item != "tg"]
        return source_order

    @staticmethod
    def _build_keyword_candidates(payload: dict[str, Any], tmdb_id: int) -> list[str]:
        title = str(payload.get("title") or payload.get("name") or "").strip()
        original_title = str(
            payload.get("original_title") or payload.get("original_name") or ""
        ).strip()
        year = ExploreActionQueueService._normalize_year(payload.get("year"))
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

        candidates: list[str] = []
        if title and year:
            candidates.append(f"{title} {year}")
        if title:
            candidates.append(title)
        if original_title and year:
            candidates.append(f"{original_title} {year}")
        if original_title:
            candidates.append(original_title)
        for alias in aliases:
            if year:
                candidates.append(f"{alias} {year}")
            candidates.append(alias)
        candidates.append(f"TMDB {tmdb_id}")

        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            normalized = str(item or "").strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _build_attempt_error_summary(attempts: list[dict[str, Any]]) -> str:
        if not attempts:
            return "暂未找到可转存资源"
        parts: list[str] = []
        for row in attempts:
            source = str(row.get("source") or "unknown")
            status = str(row.get("status") or "unknown").strip().lower() or "unknown"
            if status in {"failed", "transfer_failed"}:
                error = str(row.get("error") or "").strip()
                parts.append(f"{source}: {error[:60] or 'failed'}")
            elif status == "empty":
                parts.append(f"{source}: empty")
            elif status == "success":
                parts.append(f"{source}: success")
            if len(parts) >= 4:
                break
        if not parts:
            return "暂未找到可转存资源"
        return f"暂未找到可转存资源（{'; '.join(parts)}）"

    async def _find_pan115_share_link(
        self,
        route_info: dict[str, Any],
        payload: dict[str, Any],
        source_order: list[str] | None = None,
    ) -> dict[str, Any]:
        media_type = route_info["media_type"]
        tmdb_id = int(route_info["tmdb_id"])
        source_order = list(source_order or self._resolve_save_source_order())
        keyword_candidates = self._build_keyword_candidates(payload, tmdb_id)
        attempts: list[dict[str, Any]] = []

        for source in source_order:
            if source == "hdhive":
                source_has_result = False
                if tmdb_id > 0:
                    try:
                        if media_type == "tv":
                            rows = await hdhive_service.get_tv_pan115(tmdb_id)
                        else:
                            rows = await hdhive_service.get_movie_pan115(tmdb_id)
                        rows = rows if isinstance(rows, list) else []
                        if runtime_settings_service.get_subscription_hdhive_prefer_free():
                            rows = hdhive_service.sort_free_first(rows)
                        rows = self._sort_by_pref(rows)
                        for row in rows:
                            link = self._extract_share_link(row)
                            if link:
                                attempts.append(
                                    {
                                        "source": "hdhive",
                                        "status": "success",
                                        "via": "tmdb",
                                        "count": len(rows),
                                    }
                                )
                                return {
                                    "share_link": link,
                                    "selected_source": "hdhive",
                                    "source_order": source_order,
                                    "attempts": attempts,
                                }
                        attempts.append(
                            {
                                "source": "hdhive",
                                "status": "empty",
                                "via": "tmdb",
                                "count": len(rows),
                            }
                        )
                    except Exception as exc:
                        attempts.append(
                            {
                                "source": "hdhive",
                                "status": "failed",
                                "via": "tmdb",
                                "error": str(exc)[:300],
                            }
                        )

                for keyword in keyword_candidates:
                    try:
                        rows = await hdhive_service.get_pan115_by_keyword(
                            keyword, media_type=media_type
                        )
                        rows = rows if isinstance(rows, list) else []
                        if runtime_settings_service.get_subscription_hdhive_prefer_free():
                            rows = hdhive_service.sort_free_first(rows)
                        rows = self._sort_by_pref(rows)
                        for row in rows:
                            link = self._extract_share_link(row)
                            if link:
                                attempts.append(
                                    {
                                        "source": "hdhive",
                                        "status": "success",
                                        "via": "keyword",
                                        "keyword": keyword,
                                        "count": len(rows),
                                    }
                                )
                                return {
                                    "share_link": link,
                                    "selected_source": "hdhive",
                                    "source_order": source_order,
                                    "attempts": attempts,
                                }
                        attempts.append(
                            {
                                "source": "hdhive",
                                "status": "empty",
                                "via": "keyword",
                                "keyword": keyword,
                                "count": len(rows),
                            }
                        )
                    except Exception as exc:
                        attempts.append(
                            {
                                "source": "hdhive",
                                "status": "failed",
                                "via": "keyword",
                                "keyword": keyword,
                                "error": str(exc)[:300],
                            }
                        )
                    source_has_result = True
                if not source_has_result:
                    attempts.append(
                        {
                            "source": "hdhive",
                            "status": "empty",
                            "via": "keyword",
                            "count": 0,
                        }
                    )
                continue

            if source == "pansou":
                pansou_service.set_base_url(
                    runtime_settings_service.get_pansou_base_url()
                )
                for keyword in keyword_candidates:
                    try:
                        pansou_payload = await pansou_service.search_115(
                            keyword, res="results"
                        )
                        link = self._extract_share_link_from_pansou_payload(
                            pansou_payload
                        )
                        if link:
                            attempts.append(
                                {
                                    "source": "pansou",
                                    "status": "success",
                                    "via": "keyword",
                                    "keyword": keyword,
                                }
                            )
                            return {
                                "share_link": link,
                                "selected_source": "pansou",
                                "source_order": source_order,
                                "attempts": attempts,
                            }
                        attempts.append(
                            {
                                "source": "pansou",
                                "status": "empty",
                                "via": "keyword",
                                "keyword": keyword,
                            }
                        )
                    except Exception as exc:
                        attempts.append(
                            {
                                "source": "pansou",
                                "status": "failed",
                                "via": "keyword",
                                "keyword": keyword,
                                "error": str(exc)[:300],
                            }
                        )
                continue

            if source == "tg":
                for keyword in keyword_candidates:
                    try:
                        rows = await tg_service.search_115_by_keyword(
                            keyword, media_type=media_type
                        )
                        rows = rows if isinstance(rows, list) else []
                        for row in rows:
                            link = self._extract_share_link(row)
                            if link:
                                attempts.append(
                                    {
                                        "source": "tg",
                                        "status": "success",
                                        "via": "keyword",
                                        "keyword": keyword,
                                        "count": len(rows),
                                    }
                                )
                                return {
                                    "share_link": link,
                                    "selected_source": "tg",
                                    "source_order": source_order,
                                    "attempts": attempts,
                                }
                        attempts.append(
                            {
                                "source": "tg",
                                "status": "empty",
                                "via": "keyword",
                                "keyword": keyword,
                                "count": len(rows),
                            }
                        )
                    except Exception as exc:
                        attempts.append(
                            {
                                "source": "tg",
                                "status": "failed",
                                "via": "keyword",
                                "keyword": keyword,
                                "error": str(exc)[:300],
                            }
                        )
                continue

        return {
            "share_link": "",
            "selected_source": "",
            "source_order": source_order,
            "attempts": attempts,
        }

    async def _execute_save(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task.get("payload") or {})
        route_info = await self._resolve_route(payload)
        media_type = route_info["media_type"]
        tmdb_id = int(route_info["tmdb_id"])
        source_order = self._resolve_save_source_order()
        folder = runtime_settings_service.get_pan115_default_folder()
        folder_id = str(folder.get("folder_id") or "0").strip() or "0"
        attempts: list[dict[str, Any]] = []

        for source in source_order:
            search_result = await self._find_pan115_share_link(
                route_info, payload, source_order=[source]
            )
            attempts.extend(list(search_result.get("attempts") or []))
            share_link = str(search_result.get("share_link") or "").strip()
            if not share_link:
                continue

            receive_code = self._extract_receive_code(share_link)
            try:
                result = await pan115_service.save_share_directly(
                    share_link,
                    folder_id,
                    receive_code,
                )
            except Exception as exc:
                attempts.append(
                    {
                        "source": source,
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
                attempts.append(
                    {
                        "source": source,
                        "status": "transfer_failed",
                        "error": (error_text or "转存失败")[:300],
                    }
                )
                continue

            await media_postprocess_service.trigger_archive_after_transfer(
                trigger="explore_transfer"
            )
            return {
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "share_link": share_link,
                "selected_source": source,
                "source_order": source_order,
                "attempts": attempts,
                "save_mode": "direct",
                "target_parent_id": folder_id,
                "message": str(result.get("message") or "已提交转存任务")
                if isinstance(result, dict)
                else "已提交转存任务",
            }

        raise ValueError(self._build_attempt_error_summary(attempts))


explore_action_queue_service = ExploreActionQueueService()
