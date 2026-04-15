from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.scheduler import scheduler_manager
from app.services.runtime_settings_service import runtime_settings_service


class ArchiveSchedulerService:
    """归档扫描和离线监控定时任务管理"""

    async def ensure_scan_task(self) -> None:
        enabled = runtime_settings_service.get_archive_enabled()
        interval_minutes = runtime_settings_service.get_archive_interval_minutes()
        interval_seconds = max(1, int(interval_minutes)) * 60
        job_key = "system.archive_scan"
        display_name = "归档刮削扫描"

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

        await self.ensure_offline_monitor_task()

    async def ensure_offline_monitor_task(self) -> None:
        archive_enabled = runtime_settings_service.get_archive_enabled()
        auto_offline = runtime_settings_service.get_archive_auto_on_offline()
        enabled = archive_enabled and auto_offline
        interval_minutes = (
            runtime_settings_service.get_offline_monitor_interval_minutes()
        )
        interval_seconds = max(1, int(interval_minutes)) * 60
        job_key = "system.offline_monitor"
        display_name = "离线下载完成监控"

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


archive_scheduler_service = ArchiveSchedulerService()
