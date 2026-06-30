"""「猜你想看」推荐刷新定时任务注册。"""

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.scheduler import scheduler_manager
from app.services.runtime_settings_service import runtime_settings_service


class RecommendSchedulerService:
    async def ensure_sync_task(self) -> None:
        enabled = runtime_settings_service.get_recommend_enabled()
        cron_expr = runtime_settings_service.get_recommend_cron()
        job_key = "system.recommend_refresh"
        display_name = "AI 推荐刷新（猜你想看）"

        async with async_session_maker() as db:
            result = await db.execute(
                select(SchedulerTask).where(SchedulerTask.job_key == job_key).limit(1)
            )
            task = result.scalar_one_or_none()
            if not task:
                task = SchedulerTask(
                    name=display_name,
                    job_key=job_key,
                    trigger_type="cron",
                    cron_expr=cron_expr,
                    interval_seconds=None,
                    kwargs_json="{}",
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
                task.name = display_name
                task.trigger_type = "cron"
                task.cron_expr = cron_expr
                task.interval_seconds = None
                task.enabled = enabled
                task.state = "W" if enabled else "P"

            await db.flush()
            await scheduler_manager.update_dynamic_job(task)
            if not enabled:
                await scheduler_manager.remove_dynamic_job(task.id)
            await db.commit()


recommend_scheduler_service = RecommendSchedulerService()
