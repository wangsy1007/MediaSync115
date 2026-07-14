from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.scheduler import scheduler_manager
from app.services.runtime_settings_service import runtime_settings_service


class StrmSchedulerService:
    """维护 STRM 增量生成和每周全量校准任务。"""

    async def ensure_tasks(self) -> None:
        await self._ensure_task(
            job_key="system.generate_strm_incremental",
            display_name="STRM 增量生成",
            trigger_type="interval",
            interval_seconds=(
                runtime_settings_service.get_strm_incremental_interval_minutes() * 60
            ),
            cron_expr=None,
            enabled=runtime_settings_service.get_strm_schedule_enabled(),
        )

        run_time = runtime_settings_service.get_strm_full_schedule_time()
        hour, minute = (int(part) for part in run_time.split(":", 1))
        await self._ensure_task(
            job_key="system.generate_strm_full",
            display_name="STRM 每周全量生成",
            trigger_type="cron",
            interval_seconds=None,
            cron_expr=(
                f"{minute} {hour} * * "
                f"{runtime_settings_service.get_strm_full_schedule_day()}"
            ),
            enabled=runtime_settings_service.get_strm_full_schedule_enabled(),
        )

    async def _ensure_task(
        self,
        *,
        job_key: str,
        display_name: str,
        trigger_type: str,
        interval_seconds: int | None,
        cron_expr: str | None,
        enabled: bool,
    ) -> None:
        async with async_session_maker() as db:
            result = await db.execute(
                select(SchedulerTask).where(SchedulerTask.job_key == job_key).limit(1)
            )
            task = result.scalar_one_or_none()
            if task is None:
                task = SchedulerTask(
                    name=display_name,
                    job_key=job_key,
                    trigger_type=trigger_type,
                    cron_expr=cron_expr,
                    interval_seconds=interval_seconds,
                    kwargs_json="{}",
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
                task.name = display_name
                task.trigger_type = trigger_type
                task.cron_expr = cron_expr
                task.interval_seconds = interval_seconds
                task.kwargs_json = "{}"
                task.enabled = enabled
                task.state = "W" if enabled else "P"

            await db.flush()
            await scheduler_manager.update_dynamic_job(task)
            if not enabled:
                await scheduler_manager.remove_dynamic_job(task.id)
            await db.commit()


strm_scheduler_service = StrmSchedulerService()
