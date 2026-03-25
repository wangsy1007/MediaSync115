import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.models import TgSyncState
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.tg_index_service import tg_index_service
from app.services.tg_service import FloodWaitError, tg_service


class TgSyncService:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._job_lock = asyncio.Lock()

    async def _set_job(self, job_id: str, **fields: Any) -> None:
        async with self._job_lock:
            current = self._jobs.get(job_id, {})
            current.update(fields)
            current["job_id"] = job_id
            self._jobs[job_id] = current

    async def _create_job(self, *, job_type: str) -> dict[str, Any]:
        job_id = uuid4().hex
        payload = {
            "job_id": job_id,
            "job_type": job_type,
            "status": "running",
            "message": "任务已启动",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": "",
            "processed_messages": 0,
            "indexed_rows": 0,
            "errors": [],
        }
        async with self._job_lock:
            self._jobs[job_id] = payload
        return payload

    async def get_job(self, job_id: str) -> dict[str, Any]:
        async with self._job_lock:
            item = dict(self._jobs.get(job_id) or {})
        if not item:
            return {
                "job_id": job_id,
                "status": "not_found",
                "message": "任务不存在",
            }
        return item

    async def _get_state(self, channel: str) -> TgSyncState:
        async with async_session_maker() as db:
            result = await db.execute(select(TgSyncState).where(TgSyncState.channel_username == channel).limit(1))
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
        async with async_session_maker() as db:
            result = await db.execute(select(TgSyncState).where(TgSyncState.channel_username == channel).limit(1))
            state = result.scalar_one_or_none()
            if state is None:
                state = TgSyncState(channel_username=channel)
                db.add(state)

            if last_message_id is not None and last_message_id > int(state.last_message_id or 0):
                state.last_message_id = last_message_id
            if last_message_date is not None:
                state.last_message_date = last_message_date
            if backfill_completed is not None:
                state.backfill_completed = bool(backfill_completed)
            if error_message is not None:
                state.last_error = error_message
            state.last_synced_at = datetime.now(timezone.utc)
            await db.commit()

    async def _sync_channel_messages(
        self,
        *,
        job_id: str,
        channel: str,
        batch_size: int,
        min_id: int = 0,
        mark_backfill_complete: bool = False,
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
                processed_messages += 1
                msg_id = int(getattr(message, "id", 0) or 0)
                msg_date = getattr(message, "date", None)
                if msg_date and msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)

                if msg_id > latest_message_id:
                    latest_message_id = msg_id
                    latest_message_date = msg_date if isinstance(msg_date, datetime) else latest_message_date

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
                        processed_messages=processed_messages,
                        indexed_rows=indexed_rows,
                        message=f"同步中: {channel} 已处理 {processed_messages} 条消息",
                    )

            if rows_buffer:
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

    async def _run_backfill(self, job_id: str, rebuild: bool) -> None:
        try:
            tg_service._ensure_search_config()
            if rebuild:
                await tg_index_service.clear_all()

            channels = runtime_settings_service.get_tg_channel_usernames() or []
            batch_size = runtime_settings_service.get_tg_backfill_batch_size()
            await operation_log_service.log_background_event(
                source_type="background_task", module="tg_sync",
                action="tg.sync.backfill.start", status="info",
                message=f"TG 全量回填开始（{'重建索引' if rebuild else '增量回填'}，{len(channels)} 个频道）",
                extra={"job_id": job_id, "rebuild": rebuild, "channels": channels},
            )
            total_processed = 0
            total_indexed = 0
            errors: list[str] = []

            for channel in channels:
                try:
                    result = await self._sync_channel_messages(
                        job_id=job_id,
                        channel=channel,
                        batch_size=batch_size,
                        min_id=0,
                        mark_backfill_complete=True,
                    )
                    total_processed += int(result["processed_messages"])
                    total_indexed += int(result["indexed_rows"])
                except FloodWaitError as exc:
                    wait_seconds = int(getattr(exc, "seconds", 5) or 5)
                    await asyncio.sleep(wait_seconds)
                    errors.append(f"{channel}: 触发 Telegram 频控，等待 {wait_seconds} 秒后继续")
                except Exception as exc:
                    errors.append(f"{channel}: {exc}")
                    await self._touch_state(channel=channel, error_message=str(exc))

            status = "success" if not errors else "partial"
            msg = "全量回填完成" if not errors else "全量回填完成（部分频道失败）"
            await self._set_job(
                job_id,
                status=status,
                message=msg,
                finished_at=datetime.now(timezone.utc).isoformat(),
                processed_messages=total_processed,
                indexed_rows=total_indexed,
                errors=errors,
            )
            await operation_log_service.log_background_event(
                source_type="background_task", module="tg_sync",
                action="tg.sync.backfill.finish", status=status,
                message=f"TG 全量回填{msg}：处理 {total_processed} 条消息，索引 {total_indexed} 行",
                extra={"job_id": job_id, "processed": total_processed, "indexed": total_indexed, "errors": errors[:5]},
            )
        except Exception as exc:
            await self._set_job(
                job_id,
                status="failed",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await operation_log_service.log_background_event(
                source_type="background_task", module="tg_sync",
                action="tg.sync.backfill.error", status="failed",
                message=f"TG 全量回填失败：{str(exc)[:200]}",
                extra={"job_id": job_id, "error": str(exc)[:300]},
            )

    async def _run_incremental(self, job_id: str) -> None:
        try:
            tg_service._ensure_search_config()
            channels = runtime_settings_service.get_tg_channel_usernames() or []
            batch_size = runtime_settings_service.get_tg_backfill_batch_size()
            await operation_log_service.log_background_event(
                source_type="background_task", module="tg_sync",
                action="tg.sync.incremental.start", status="info",
                message=f"TG 增量同步开始（{len(channels)} 个频道）",
                extra={"job_id": job_id, "channels": channels},
            )
            total_processed = 0
            total_indexed = 0
            errors: list[str] = []

            for channel in channels:
                try:
                    state = await self._get_state(channel)
                    min_id = int(state.last_message_id or 0)
                    result = await self._sync_channel_messages(
                        job_id=job_id,
                        channel=channel,
                        batch_size=batch_size,
                        min_id=min_id,
                        mark_backfill_complete=bool(state.backfill_completed),
                    )
                    total_processed += int(result["processed_messages"])
                    total_indexed += int(result["indexed_rows"])
                except FloodWaitError as exc:
                    wait_seconds = int(getattr(exc, "seconds", 5) or 5)
                    await asyncio.sleep(wait_seconds)
                    errors.append(f"{channel}: 触发 Telegram 频控，等待 {wait_seconds} 秒后继续")
                except Exception as exc:
                    errors.append(f"{channel}: {exc}")
                    await self._touch_state(channel=channel, error_message=str(exc))

            status = "success" if not errors else "partial"
            msg = "增量同步完成" if not errors else "增量同步完成（部分频道失败）"
            await self._set_job(
                job_id,
                status=status,
                message=msg,
                finished_at=datetime.now(timezone.utc).isoformat(),
                processed_messages=total_processed,
                indexed_rows=total_indexed,
                errors=errors,
            )
            await operation_log_service.log_background_event(
                source_type="background_task", module="tg_sync",
                action="tg.sync.incremental.finish", status=status,
                message=f"TG 增量同步{msg}：处理 {total_processed} 条消息，索引 {total_indexed} 行",
                extra={"job_id": job_id, "processed": total_processed, "indexed": total_indexed, "errors": errors[:5]},
            )
        except Exception as exc:
            await self._set_job(
                job_id,
                status="failed",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            await operation_log_service.log_background_event(
                source_type="background_task", module="tg_sync",
                action="tg.sync.incremental.error", status="failed",
                message=f"TG 增量同步失败：{str(exc)[:200]}",
                extra={"job_id": job_id, "error": str(exc)[:300]},
            )

    async def start_backfill(self, *, rebuild: bool = False) -> dict[str, Any]:
        job = await self._create_job(job_type="backfill_rebuild" if rebuild else "backfill")
        asyncio.create_task(self._run_backfill(job["job_id"], rebuild))
        return job

    async def run_incremental_once(self) -> dict[str, Any]:
        job = await self._create_job(job_type="incremental")
        asyncio.create_task(self._run_incremental(job["job_id"]))
        return job

    async def get_status(self) -> dict[str, Any]:
        channels = runtime_settings_service.get_tg_channel_usernames() or []
        index_status = await tg_index_service.get_status(channels)
        async with self._job_lock:
            jobs = list(self._jobs.values())

        jobs_sorted = sorted(jobs, key=lambda item: str(item.get("started_at") or ""), reverse=True)
        running_jobs = [item for item in jobs_sorted if str(item.get("status")) == "running"]

        return {
            "index": index_status,
            "running_jobs": running_jobs,
            "latest_jobs": jobs_sorted[:10],
        }



tg_sync_service = TgSyncService()
