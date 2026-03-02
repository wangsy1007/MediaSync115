import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.core.database import async_session_maker
from app.services.subscription_service import subscription_service


class SubscriptionRunTaskService:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._running_by_channel: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def start(self, channel: str, force_auto_download: bool = False) -> dict[str, Any]:
        normalized_channel = self._normalize_channel(channel)
        async with self._lock:
            existing_task_id = self._running_by_channel.get(normalized_channel)
            if existing_task_id and existing_task_id in self._tasks:
                existing = dict(self._tasks[existing_task_id])
                existing["already_running"] = True
                return existing

            task_id = uuid4().hex
            now = datetime.utcnow().isoformat()
            task = {
                "task_id": task_id,
                "channel": normalized_channel,
                "force_auto_download": bool(force_auto_download),
                "status": "queued",
                "message": "任务已排队",
                "progress": None,
                "result": None,
                "error": None,
                "started_at": now,
                "finished_at": None,
            }
            self._tasks[task_id] = task
            self._running_by_channel[normalized_channel] = task_id
            self._prune_locked()

        asyncio.create_task(self._run_task(task_id, normalized_channel, bool(force_auto_download)))
        return dict(task)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return dict(task)

    async def _run_task(self, task_id: str, channel: str, force_auto_download: bool) -> None:
        await self._update_task(
            task_id,
            {
                "status": "running",
                "message": "任务执行中",
            },
        )

        try:
            async with async_session_maker() as db:
                result = await subscription_service.run_channel_check(
                    db,
                    channel,
                    force_auto_download=force_auto_download,
                    progress_callback=lambda payload: self._update_task(
                        task_id,
                        {
                            "status": "running",
                            "message": payload.get("message") or "任务执行中",
                            "progress": payload,
                        },
                    ),
                )

            await self._update_task(
                task_id,
                {
                    "status": "success",
                    "message": result.get("message") or "任务执行完成",
                    "result": result,
                    "finished_at": datetime.utcnow().isoformat(),
                },
            )
        except Exception as exc:
            await self._update_task(
                task_id,
                {
                    "status": "failed",
                    "message": "任务执行失败",
                    "error": str(exc),
                    "finished_at": datetime.utcnow().isoformat(),
                },
            )
        finally:
            async with self._lock:
                current = self._running_by_channel.get(channel)
                if current == task_id:
                    self._running_by_channel.pop(channel, None)

    async def _update_task(self, task_id: str, patch: dict[str, Any]) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(patch)

    def _prune_locked(self) -> None:
        # Keep recent task records in memory to avoid unbounded growth.
        if len(self._tasks) <= 200:
            return
        removable = [
            task_id
            for task_id, item in self._tasks.items()
            if item.get("status") in {"success", "failed"}
        ]
        for task_id in removable[: len(self._tasks) - 200]:
            self._tasks.pop(task_id, None)

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        normalized = str(channel or "").strip().lower()
        if normalized not in {"nullbr", "pansou", "hdhive", "tg", "priority"}:
            raise ValueError("unsupported channel")
        return normalized


subscription_run_task_service = SubscriptionRunTaskService()
