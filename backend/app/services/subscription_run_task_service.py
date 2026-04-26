import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.core.database import async_session_maker
from app.services.operation_log_service import operation_log_service
from app.services.subscription_service import subscription_service

ALL_CHANNELS = ["hdhive", "pansou", "tg"]


class SubscriptionRunTaskService:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._running_by_channel: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

    async def start(
        self, channel: str, force_auto_download: bool = False
    ) -> dict[str, Any]:
        normalized_channel = self._normalize_channel(channel)
        async with self._lock:
            # 当执行全部渠道时，检查是否有任何渠道正在运行
            if normalized_channel == "all":
                running_channels = [
                    ch
                    for ch in ALL_CHANNELS
                    if self._running_by_channel.get(ch)
                    and self._running_by_channel[ch] in self._tasks
                ]
                if running_channels:
                    existing = {
                        "task_id": "",
                        "channel": "all",
                        "status": "queued",
                        "message": f"以下渠道正在运行中: {', '.join(running_channels)}",
                        "already_running": True,
                        "running_channels": running_channels,
                    }
                    return existing
            else:
                all_task_id = self._running_by_channel.get("all")
                if all_task_id and all_task_id in self._tasks:
                    existing = dict(self._tasks[all_task_id])
                    existing["already_running"] = True
                    existing["message"] = str(
                        existing.get("message") or "全部渠道任务正在运行中"
                    )
                    return existing
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
            # 对于 "all" 渠道，使用特殊的 key
            self._running_by_channel[normalized_channel] = task_id
            self._prune_locked()
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="subscriptions",
            action="subscription.run.background.start",
            status="info",
            message=f"订阅后台任务已入队: {normalized_channel}",
            trace_id=task_id,
            extra={
                "channel": normalized_channel,
                "force_auto_download": bool(force_auto_download),
            },
        )

        task = asyncio.create_task(
            self._run_task(task_id, normalized_channel, bool(force_auto_download))
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return dict(task)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return dict(task)

    async def get_running_channel(self, channel: str) -> dict[str, Any] | None:
        async with self._lock:
            for ch in (["all"] if channel != "all" else []) + [channel]:
                task_id = self._running_by_channel.get(ch)
                if task_id and task_id in self._tasks:
                    task = dict(self._tasks[task_id])
                    task["already_running"] = True
                    task["running_via"] = "background_task"
                    return task
            return None

    async def _run_task(
        self, task_id: str, channel: str, force_auto_download: bool
    ) -> None:
        if channel == "all":
            await self._run_all_channels(task_id, force_auto_download)
            return

        await self._update_task(
            task_id,
            {
                "status": "running",
                "message": "任务执行中",
            },
        )
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="subscriptions",
            action="subscription.run.background.running",
            status="info",
            message=f"订阅后台任务开始执行: {channel}",
            trace_id=task_id,
            extra={"channel": channel, "force_auto_download": force_auto_download},
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
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="subscriptions",
                action="subscription.run.background.finish",
                status="success",
                message=result.get("message") or "订阅后台任务执行完成",
                trace_id=task_id,
                extra={"channel": channel},
            )
            await self._notify_result(channel, result)
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
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="subscriptions",
                action="subscription.run.background.finish",
                status="failed",
                message=f"订阅后台任务执行失败: {channel}",
                trace_id=task_id,
                extra={"channel": channel, "error": str(exc)},
            )
            await self._notify_error(channel, str(exc))
        finally:
            async with self._lock:
                current = self._running_by_channel.get(channel)
                if current == task_id:
                    self._running_by_channel.pop(channel, None)

    async def _run_all_channels(self, task_id: str, force_auto_download: bool) -> None:
        """按单个影视顺序统一执行一次订阅检查。"""
        await self._update_task(
            task_id,
            {
                "status": "running",
                "message": "开始按资源优先级执行订阅检查",
            },
        )
        await operation_log_service.log_background_event(
            source_type="background_task",
            module="subscriptions",
            action="subscription.run.background.running",
            status="info",
            message="订阅后台任务开始执行：按资源优先级逐个影视检查",
            trace_id=task_id,
            extra={"channel": "all", "force_auto_download": force_auto_download},
        )
        try:
            async with async_session_maker() as db:
                result = await subscription_service.run_channel_check(
                    db,
                    "all",
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

            final_status = str(result.get("status") or "success")
            final_message = str(result.get("message") or "任务执行完成")
            await self._update_task(
                task_id,
                {
                    "status": final_status,
                    "message": final_message,
                    "result": result,
                    "finished_at": datetime.utcnow().isoformat(),
                },
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="subscriptions",
                action="subscription.run.background.finish",
                status="success" if final_status == "success" else "warning",
                message=final_message,
                trace_id=task_id,
                extra={"channel": "all"},
            )
            await self._notify_result("all", result)
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
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="subscriptions",
                action="subscription.run.background.finish",
                status="failed",
                message="订阅后台任务执行失败：全部渠道",
                trace_id=task_id,
                extra={"channel": "all", "error": str(exc)},
            )
            await self._notify_error("all", str(exc))
        finally:
            async with self._lock:
                current = self._running_by_channel.get("all")
                if current == task_id:
                    self._running_by_channel.pop("all", None)

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
            if item.get("status") in {"success", "failed", "partial"}
        ]
        for task_id in removable[: len(self._tasks) - 200]:
            self._tasks.pop(task_id, None)

    @staticmethod
    async def _notify_result(channel: str, result: dict[str, Any]) -> None:
        try:
            from app.services.tg_bot.notifications import tg_bot_notify
            from html import escape

            checked = result.get("checked_count", 0)
            new_res = result.get("new_resource_count", 0)
            auto_saved = result.get("auto_saved_count", 0)
            status = result.get("status", "unknown")
            lines = [
                f"<b>订阅检查完成</b> [{escape(channel)}]",
                f"状态: {status}  检查: {checked}  新资源: {new_res}",
            ]
            if auto_saved:
                lines.append(f"自动转存: {auto_saved}")
            await tg_bot_notify("\n".join(lines))
        except Exception:
            pass

    @staticmethod
    async def _notify_error(channel: str, error: str) -> None:
        try:
            from app.services.tg_bot.notifications import tg_bot_notify
            from html import escape

            await tg_bot_notify(
                f"<b>订阅检查失败</b> [{escape(channel)}]\n{escape(error[:200])}"
            )
        except Exception:
            pass

    @staticmethod
    async def _notify_all_channels_result(
        results: dict,
        success_count: int,
        failed_count: int,
    ) -> None:
        try:
            from app.services.tg_bot.notifications import tg_bot_notify
            from html import escape

            lines = [
                f"<b>全渠道订阅检查完成</b>  成功: {success_count}  失败: {failed_count}"
            ]
            for ch, info in results.items():
                status = info.get("status", "?")
                checked = info.get("checked_count", "")
                new_res = info.get("new_resource_count", "")
                detail = f"  检查:{checked} 新资源:{new_res}" if checked != "" else ""
                lines.append(f"  {escape(ch)}: {status}{detail}")
            await tg_bot_notify("\n".join(lines))
        except Exception:
            pass

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        normalized = str(channel or "").strip().lower()
        if normalized not in {"pansou", "hdhive", "tg", "priority", "all"}:
            raise ValueError("unsupported channel")
        return normalized


subscription_run_task_service = SubscriptionRunTaskService()
