from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.scheduler import scheduler_manager
from app.services.runtime_settings_service import runtime_settings_service


class EmbySyncSchedulerService:
    async def ensure_sync_task(self) -> None:
        enabled = runtime_settings_service.get_emby_sync_enabled()
        interval_hours = runtime_settings_service.get_emby_sync_interval_hours()
        interval_seconds = max(1, int(interval_hours)) * 3600
        job_key = "system.sync_emby_index"
        display_name = "Emby 全量索引同步"

        async with async_session_maker() as db:
            result = await db.execute(
                select(SchedulerTask).where(SchedulerTask.job_key == job_key).limit(1)
            )
            task = result.scalar_one_or_none()
            if not task:
                task = SchedulerTask(
                    name=display_name,
                    job_key=job_key,
                    trigger_type="interval",
                    cron_expr=None,
                    interval_seconds=interval_seconds,
                    kwargs_json="{}",
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
                task.name = display_name
                task.trigger_type = "interval"
                task.cron_expr = None
                task.interval_seconds = interval_seconds
                task.enabled = enabled
                task.state = "W" if enabled else "P"

            await db.flush()
            await scheduler_manager.update_dynamic_job(task)
            if not enabled:
                await scheduler_manager.remove_dynamic_job(task.id)
            await db.commit()


emby_sync_scheduler_service = EmbySyncSchedulerService()
