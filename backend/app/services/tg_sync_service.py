import asyncio
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from app.core.database import async_session_maker, ensure_tables_exist
from app.models.models import TgSyncJob, TgSyncState
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tg_index_service import tg_index_service
from app.services.tg_service import FloodWaitError, tg_service

from app.core.timezone_utils import beijing_now, BEIJING_TZ


class TgSyncService:
    def __init__(self) -> None:
        self._job_lock = asyncio.Lock()
        self._mutating_job_types = {"backfill", "backfill_rebuild", "incremental"}
        self._job_tasks: dict[str, asyncio.Task[Any]] = {}
        self._cancelled_job_ids: set[str] = set()

    async def _ensure_tables(self) -> None:
        await ensure_tables_exist("tg_message_index", "tg_sync_state", "tg_sync_jobs")

    def _is_task_active(self, job_id: str) -> bool:
        task = self._job_tasks.get(job_id)
        return bool(task is not None and not task.done())

    @staticmethod
    def _serialize_job(job: TgSyncJob) -> dict[str, Any]:
        errors: list[str] = []
        result: dict[str, Any] | None = None
        if job.errors_json:
            try:
                parsed_errors = json.loads(job.errors_json)
                if isinstance(parsed_errors, list):
                    errors = [str(item) for item in parsed_errors]
            except Exception:
                errors = [str(job.errors_json)]
        if job.result_json:
            try:
                parsed_result = json.loads(job.result_json)
                if isinstance(parsed_result, dict):
                    result = parsed_result
            except Exception:
                result = None
        return {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "status": job.status,
            "message": job.message,
            "current_channel": job.current_channel or "",
            "current_index": int(job.current_index or 0),
            "total_channels": int(job.total_channels or 0),
            "processed_messages": int(job.processed_messages or 0),
            "indexed_rows": int(job.indexed_rows or 0),
            "errors": errors,
            "result": result,
            "started_at": job.started_at.isoformat() if job.started_at else "",
            "updated_at": job.updated_at.isoformat() if job.updated_at else "",
            "finished_at": job.finished_at.isoformat() if job.finished_at else "",
        }

    async def _set_job(self, job_id: str, **fields: Any) -> None:
        async with self._job_lock:
            await self._ensure_tables()
            async with async_session_maker() as db:
                result = await db.execute(
                    select(TgSyncJob).where(TgSyncJob.job_id == job_id).limit(1)
                )
                job = result.scalar_one_or_none()
                if job is None:
                    return

                for key, value in fields.items():
                    if key == "errors":
                        job.errors_json = json.dumps(value or [], ensure_ascii=False)
                    elif key == "result":
                        job.result_json = (
                            json.dumps(value, ensure_ascii=False)
                            if isinstance(value, (dict, list))
                            else None
                        )
                    elif key == "finished_at":
                        job.finished_at = value
                    else:
                        setattr(job, key, value)
                job.updated_at = beijing_now()
                await db.commit()

    def _register_job_task(self, job_id: str, task: asyncio.Task[Any]) -> None:
        self._job_tasks[job_id] = task
        self._cancelled_job_ids.discard(job_id)

        def _cleanup(done_task: asyncio.Task[Any]) -> None:
            current = self._job_tasks.get(job_id)
            if current is done_task:
                self._job_tasks.pop(job_id, None)
            self._cancelled_job_ids.discard(job_id)

        task.add_done_callback(_cleanup)

    async def _mark_job_cancelling(self, job_id: str, message: str) -> None:
        self._cancelled_job_ids.add(job_id)
        await self._set_job(
            job_id,
            status="cancelling",
            message=message,
        )

    async def _mark_job_cancelled(self, job_id: str, message: str) -> None:
        self._cancelled_job_ids.discard(job_id)
        await self._set_job(
            job_id,
            status="cancelled",
            message=message,
            finished_at=beijing_now(),
        )

    async def _check_cancelled(self, job_id: str) -> None:
        task = asyncio.current_task()
        if job_id in self._cancelled_job_ids or (task is not None and task.cancelling()):
            raise asyncio.CancelledError("任务已停止")

    @staticmethod
    def _clear_current_task_cancellation() -> None:
        task = asyncio.current_task()
        if task is None:
            return
        while task.cancelling():
            task.uncancel()

    async def _create_job(self, *, job_type: str) -> dict[str, Any]:
        async with self._job_lock:
            await self._ensure_tables()
            async with async_session_maker() as db:
                if job_type in self._mutating_job_types:
                    running_result = await db.execute(
                        select(TgSyncJob)
                        .where(
                            TgSyncJob.status.in_(("queued", "running", "cancelling")),
                            TgSyncJob.job_type.in_(tuple(self._mutating_job_types)),
                        )
                        .order_by(TgSyncJob.started_at.desc(), TgSyncJob.id.desc())
                        .limit(1)
                    )
                else:
                    running_result = await db.execute(
                        select(TgSyncJob)
                        .where(
                            TgSyncJob.status.in_(("queued", "running", "cancelling")),
                            TgSyncJob.job_type == job_type,
                        )
                        .order_by(TgSyncJob.started_at.desc(), TgSyncJob.id.desc())
                        .limit(1)
                    )
                running_job = running_result.scalar_one_or_none()
                if running_job is not None:
                    payload = self._serialize_job(running_job)
                    payload["already_running"] = True
                    return payload

                now = beijing_now()
                job = TgSyncJob(
                    job_id=uuid4().hex,
                    job_type=job_type,
                    status="queued",
                    message="任务已排队",
                    started_at=now,
                    updated_at=now,
                )
                db.add(job)
                await db.flush()
                await self._prune_jobs(db)
                await db.commit()
                payload = self._serialize_job(job)
                payload["already_running"] = False
                return payload

    async def get_job(self, job_id: str) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session_maker() as db:
            result = await db.execute(
                select(TgSyncJob).where(TgSyncJob.job_id == job_id).limit(1)
            )
            item = result.scalar_one_or_none()
        if item is None:
            return {
                "job_id": job_id,
                "status": "not_found",
                "message": "任务不存在",
            }
        return self._serialize_job(item)

    async def _get_state(self, channel: str) -> TgSyncState:
        await self._ensure_tables()
        async with async_session_maker() as db:
            result = await db.execute(
                select(TgSyncState)
                .where(TgSyncState.channel_username == channel)
                .limit(1)
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = TgSyncState(channel_username=channel)
                db.add(state)
                await db.commit()
                await db.refresh(state)
            return state

    async def _touch_state(
        self,
        *,
        channel: str,
        last_message_id: int | None = None,
        last_message_date: datetime | None = None,
        backfill_completed: bool | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._ensure_tables()
        async with async_session_maker() as db:
            result = await db.execute(
                select(TgSyncState)
                .where(TgSyncState.channel_username == channel)
                .limit(1)
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = TgSyncState(channel_username=channel)
                db.add(state)

            if last_message_id is not None and last_message_id > int(
                state.last_message_id or 0
            ):
                state.last_message_id = last_message_id
            if last_message_date is not None:
                state.last_message_date = last_message_date
            if backfill_completed is not None:
                state.backfill_completed = bool(backfill_completed)
            if error_message is not None:
                state.last_error = error_message
            state.last_synced_at = beijing_now()
            await db.commit()

    async def _sync_channel_messages(
        self,
        *,
        job_id: str,
        channel: str,
        batch_size: int,
        min_id: int = 0,
        mark_backfill_complete: bool = False,
        channel_index: int = 0,
        total_channels: int = 0,
    ) -> dict[str, int]:
        indexed_rows = 0
        processed_messages = 0
        rows_buffer: list[dict[str, Any]] = []
        latest_message_id = int(min_id or 0)
        latest_message_date: datetime | None = None

        client = tg_service._build_client(tg_service.get_session())
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram 会话已失效，请重新登录")
            entity = await client.get_entity(channel)

            iter_kwargs: dict[str, Any] = {"limit": None}
            if min_id > 0:
                iter_kwargs["min_id"] = min_id

            async for message in client.iter_messages(entity, **iter_kwargs):
                await self._check_cancelled(job_id)
                processed_messages += 1
                msg_id = int(getattr(message, "id", 0) or 0)
                msg_date = getattr(message, "date", None)
                if msg_date and msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=BEIJING_TZ)

                if msg_id > latest_message_id:
                    latest_message_id = msg_id
                    latest_message_date = (
                        msg_date
                        if isinstance(msg_date, datetime)
                        else latest_message_date
                    )

                extracted = tg_service._build_rows_from_message(
                    channel=channel,
                    message=message,
                    normalized_media="unknown",
                    seen=None,
                )
                if extracted:
                    rows_buffer.extend(extracted)

                if len(rows_buffer) >= batch_size:
                    indexed_rows += await tg_index_service.upsert_rows(rows_buffer)
                    rows_buffer = []
                    await self._touch_state(
                        channel=channel,
                        last_message_id=latest_message_id,
                        last_message_date=latest_message_date,
                        backfill_completed=False,
                        error_message="",
                    )
                    await self._set_job(
                        job_id,
                        current_channel=channel,
                        current_index=channel_index,
                        total_channels=total_channels,
                        processed_messages=processed_messages,
                        indexed_rows=indexed_rows,
                        message=f"同步中：{channel} 已处理 {processed_messages} 条消息",
                    )
                    await self._check_cancelled(job_id)

            if rows_buffer:
                await self._check_cancelled(job_id)
                indexed_rows += await tg_index_service.upsert_rows(rows_buffer)

            await self._touch_state(
                channel=channel,
                last_message_id=latest_message_id,
                last_message_date=latest_message_date,
                backfill_completed=mark_backfill_complete,
                error_message="",
            )
        finally:
            await client.disconnect()

        return {
            "processed_messages": processed_messages,
            "indexed_rows": indexed_rows,
        }

    async def _run_refresh_status(self, job_id: str) -> None:
        try:
            channels = runtime_settings_service.get_tg_channel_usernames() or []
            await self._set_job(
                job_id,
                status="running",
                message="正在刷新 TG 索引状态",
                total_channels=len(channels),
            )
            status_payload = await tg_index_service.get_status(channels)
            await self._set_job(
                job_id,
                status="success",
                message=f"索引状态刷新完成：共 {int(status_payload.get('total_indexed') or 0)} 条资源",
                result=status_payload,
                finished_at=beijing_now(),
            )
        except Exception as exc:
            await self._set_job(
                job_id,
                status="failed",
                message=str(exc),
                errors=[str(exc)],
                finished_at=beijing_now(),
            )

    async def _run_backfill(self, job_id: str, rebuild: bool) -> None:
        try:
            tg_service._ensure_search_config()
            channels = runtime_settings_service.get_tg_channel_usernames() or []
            batch_size = runtime_settings_service.get_tg_backfill_batch_size()
            await self._set_job(
                job_id,
                status="running",
                message="开始执行 TG 全量回填",
                total_channels=len(channels),
            )
            if rebuild:
                await tg_index_service.clear_all()

            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.backfill.start",
                status="info",
                message=f"TG 全量回填开始（{'重建索引' if rebuild else '全量回填'}，{len(channels)} 个频道）",
                extra={"job_id": job_id, "rebuild": rebuild, "channels": channels},
            )
            total_processed = 0
            total_indexed = 0
            errors: list[str] = []

            for index, channel in enumerate(channels, start=1):
                await self._check_cancelled(job_id)
                await self._set_job(
                    job_id,
                    current_channel=channel,
                    current_index=index,
                    total_channels=len(channels),
                    message=f"正在回填频道 {channel} ({index}/{len(channels)})",
                )
                try:
                    result = await self._sync_channel_messages(
                        job_id=job_id,
                        channel=channel,
                        batch_size=batch_size,
                        min_id=0,
                        mark_backfill_complete=True,
                        channel_index=index,
                        total_channels=len(channels),
                    )
                    total_processed += int(result["processed_messages"])
                    total_indexed += int(result["indexed_rows"])
                except FloodWaitError as exc:
                    wait_seconds = int(getattr(exc, "seconds", 5) or 5)
                    await self._check_cancelled(job_id)
                    await asyncio.sleep(wait_seconds)
                    errors.append(
                        f"{channel}: 触发 Telegram 频控，等待 {wait_seconds} 秒后继续"
                    )
                except Exception as exc:
                    errors.append(f"{channel}: {exc}")
                    await self._touch_state(channel=channel, error_message=str(exc))

            status = "success" if not errors else "partial"
            msg = "全量回填完成" if not errors else "全量回填完成（部分频道失败）"
            await self._set_job(
                job_id,
                status=status,
                message=msg,
                finished_at=beijing_now(),
                processed_messages=total_processed,
                indexed_rows=total_indexed,
                errors=errors,
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.backfill.finish",
                status=status,
                message=f"TG 全量回填{msg}：处理 {total_processed} 条消息，索引 {total_indexed} 行",
                extra={
                    "job_id": job_id,
                    "processed": total_processed,
                    "indexed": total_indexed,
                    "errors": errors[:5],
                },
            )
        except asyncio.CancelledError as exc:
            message = str(exc) or "TG 全量回填已停止"
            self._clear_current_task_cancellation()
            await self._mark_job_cancelled(job_id, message)
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.backfill.cancel",
                status="warning",
                message=message,
                extra={"job_id": job_id},
            )
        except Exception as exc:
            await self._set_job(
                job_id,
                status="failed",
                message=str(exc),
                errors=[str(exc)],
                finished_at=beijing_now(),
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.backfill.error",
                status="failed",
                message=f"TG 全量回填失败：{str(exc)[:200]}",
                extra={"job_id": job_id, "error": str(exc)[:300]},
            )

    async def _run_incremental(self, job_id: str) -> None:
        try:
            tg_service._ensure_search_config()
            channels = runtime_settings_service.get_tg_channel_usernames() or []
            batch_size = runtime_settings_service.get_tg_backfill_batch_size()
            await self._set_job(
                job_id,
                status="running",
                message="开始执行 TG 增量同步",
                total_channels=len(channels),
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.incremental.start",
                status="info",
                message=f"TG 增量同步开始（{len(channels)} 个频道）",
                extra={"job_id": job_id, "channels": channels},
            )
            total_processed = 0
            total_indexed = 0
            errors: list[str] = []

            for index, channel in enumerate(channels, start=1):
                await self._check_cancelled(job_id)
                await self._set_job(
                    job_id,
                    current_channel=channel,
                    current_index=index,
                    total_channels=len(channels),
                    message=f"正在增量同步频道 {channel} ({index}/{len(channels)})",
                )
                try:
                    state = await self._get_state(channel)
                    min_id = int(state.last_message_id or 0)
                    result = await self._sync_channel_messages(
                        job_id=job_id,
                        channel=channel,
                        batch_size=batch_size,
                        min_id=min_id,
                        mark_backfill_complete=bool(state.backfill_completed),
                        channel_index=index,
                        total_channels=len(channels),
                    )
                    total_processed += int(result["processed_messages"])
                    total_indexed += int(result["indexed_rows"])
                except FloodWaitError as exc:
                    wait_seconds = int(getattr(exc, "seconds", 5) or 5)
                    await self._check_cancelled(job_id)
                    await asyncio.sleep(wait_seconds)
                    errors.append(
                        f"{channel}: 触发 Telegram 频控，等待 {wait_seconds} 秒后继续"
                    )
                except Exception as exc:
                    errors.append(f"{channel}: {exc}")
                    await self._touch_state(channel=channel, error_message=str(exc))

            status = "success" if not errors else "partial"
            msg = "增量同步完成" if not errors else "增量同步完成（部分频道失败）"
            await self._set_job(
                job_id,
                status=status,
                message=msg,
                finished_at=beijing_now(),
                processed_messages=total_processed,
                indexed_rows=total_indexed,
                errors=errors,
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.incremental.finish",
                status=status,
                message=f"TG 增量同步{msg}：处理 {total_processed} 条消息，索引 {total_indexed} 行",
                extra={
                    "job_id": job_id,
                    "processed": total_processed,
                    "indexed": total_indexed,
                    "errors": errors[:5],
                },
            )
        except asyncio.CancelledError as exc:
            message = str(exc) or "TG 增量同步已停止"
            self._clear_current_task_cancellation()
            await self._mark_job_cancelled(job_id, message)
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.incremental.cancel",
                status="warning",
                message=message,
                extra={"job_id": job_id},
            )
        except Exception as exc:
            await self._set_job(
                job_id,
                status="failed",
                message=str(exc),
                errors=[str(exc)],
                finished_at=beijing_now(),
            )
            await operation_log_service.log_background_event(
                source_type="background_task",
                module="tg_sync",
                action="tg.sync.incremental.error",
                status="failed",
                message=f"TG 增量同步失败：{str(exc)[:200]}",
                extra={"job_id": job_id, "error": str(exc)[:300]},
            )

    async def start_status_refresh(self) -> dict[str, Any]:
        job = await self._create_job(job_type="status_refresh")
        if not job.get("already_running"):
            task = asyncio.create_task(
                self._run_refresh_status(str(job.get("job_id") or ""))
            )
            self._register_job_task(str(job.get("job_id") or ""), task)
        return job

    async def start_backfill(self, *, rebuild: bool = False) -> dict[str, Any]:
        job = await self._create_job(
            job_type="backfill_rebuild" if rebuild else "backfill"
        )
        if not job.get("already_running"):
            task = asyncio.create_task(
                self._run_backfill(str(job.get("job_id") or ""), rebuild)
            )
            self._register_job_task(str(job.get("job_id") or ""), task)
        return job

    async def run_incremental_once(self) -> dict[str, Any]:
        job = await self._create_job(job_type="incremental")
        if not job.get("already_running"):
            task = asyncio.create_task(
                self._run_incremental(str(job.get("job_id") or ""))
            )
            self._register_job_task(str(job.get("job_id") or ""), task)
        return job

    async def stop_job(self, job_type: str) -> dict[str, Any]:
        normalized_job_type = str(job_type or "").strip().lower()
        if normalized_job_type not in {"backfill", "backfill_rebuild", "incremental"}:
            raise ValueError("仅支持停止 TG 全量回填、重建索引或增量同步任务")

        await self._ensure_tables()
        async with async_session_maker() as db:
            result = await db.execute(
                select(TgSyncJob)
                .where(
                    TgSyncJob.status.in_(("queued", "running", "cancelling")),
                    TgSyncJob.job_type == normalized_job_type,
                )
                .order_by(TgSyncJob.started_at.desc(), TgSyncJob.id.desc())
                .limit(1)
            )
            job = result.scalar_one_or_none()

        if job is None:
            return {
                "success": False,
                "message": "当前没有可停止的 TG 任务",
                "job": None,
            }

        if normalized_job_type == "backfill":
            stop_message = "TG 全量回填停止中"
        elif normalized_job_type == "backfill_rebuild":
            stop_message = "TG 索引重建停止中"
        else:
            stop_message = "TG 增量同步停止中"
        await self._mark_job_cancelling(job.job_id, stop_message)
        task = self._job_tasks.get(job.job_id)
        if task and not task.done():
            task.cancel(stop_message)
        else:
            await self._mark_job_cancelled(job.job_id, "任务已停止")

        return {
            "success": True,
            "message": stop_message,
            "job": await self.get_job(job.job_id),
        }

    async def get_status(self) -> dict[str, Any]:
        await self._ensure_tables()
        channels = runtime_settings_service.get_tg_channel_usernames() or []
        index_status = await tg_index_service.get_status(channels)
        async with async_session_maker() as db:
            running_result = await db.execute(
                select(TgSyncJob)
                .where(TgSyncJob.status.in_(("queued", "running", "cancelling")))
                .order_by(TgSyncJob.started_at.desc(), TgSyncJob.id.desc())
            )
            latest_result = await db.execute(
                select(TgSyncJob)
                .order_by(TgSyncJob.started_at.desc(), TgSyncJob.id.desc())
                .limit(20)
            )
            running_jobs = [
                self._serialize_job(item) for item in running_result.scalars().all()
            ]
            latest_jobs = [
                self._serialize_job(item) for item in latest_result.scalars().all()
            ]

        normalized_running_jobs: list[dict[str, Any]] = []
        for job in running_jobs:
            job_id = str(job.get("job_id") or "").strip()
            if (
                str(job.get("status") or "").strip() == "cancelling"
                and job_id
                and not self._is_task_active(job_id)
            ):
                await self._mark_job_cancelled(job_id, "任务已停止")
                continue
            normalized_running_jobs.append(job)

        normalized_latest_jobs: list[dict[str, Any]] = []
        for job in latest_jobs:
            job_id = str(job.get("job_id") or "").strip()
            if (
                str(job.get("status") or "").strip() == "cancelling"
                and job_id
                and not self._is_task_active(job_id)
            ):
                normalized_latest_jobs.append(
                    {
                        **job,
                        "status": "cancelled",
                        "message": "任务已停止",
                    }
                )
                continue
            normalized_latest_jobs.append(job)

        return {
            "index": index_status,
            "running_jobs": normalized_running_jobs,
            "latest_jobs": normalized_latest_jobs,
        }

    async def _prune_jobs(self, db) -> None:
        keep_result = await db.execute(
            select(TgSyncJob.id)
            .order_by(TgSyncJob.started_at.desc(), TgSyncJob.id.desc())
            .limit(50)
        )
        keep_ids = [row[0] for row in keep_result.all() if row and row[0]]
        if not keep_ids:
            return
        await db.execute(delete(TgSyncJob).where(TgSyncJob.id.notin_(keep_ids)))


tg_sync_service = TgSyncService()
