from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.scheduler import scheduler_manager
from app.services.runtime_settings_service import runtime_settings_service


class HDHiveCheckinSchedulerService:
    async def ensure_checkin_task(self) -> None:
        await self.ensure_cookie_renew_task()
        enabled = runtime_settings_service.get_hdhive_auto_checkin_enabled()
        mode = runtime_settings_service.get_hdhive_auto_checkin_mode()
        run_time = runtime_settings_service.get_hdhive_auto_checkin_run_time()
        display_name = f"HDHive 自动签到({'赌狗' if mode == 'gamble' else '普通'})"
        job_key = "hdhive.checkin"
        cron_expr = self._build_daily_cron_expr(run_time)

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

    async def ensure_cookie_renew_task(self) -> None:
        """有 Cookie 时每日保活，避免长时间无业务请求错过刷新窗口。"""
        enabled = runtime_settings_service.has_hdhive_credentials()
        job_key = "hdhive.cookie_renew"

        async with async_session_maker() as db:
            result = await db.execute(
                select(SchedulerTask).where(SchedulerTask.job_key == job_key).limit(1)
            )
            task = result.scalar_one_or_none()
            if not task:
                task = SchedulerTask(
                    name="HDHive Cookie 自动续期",
                    job_key=job_key,
                    trigger_type="cron",
                    cron_expr="17 4 * * *",
                    interval_seconds=None,
                    kwargs_json="{}",
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
                task.name = "HDHive Cookie 自动续期"
                task.trigger_type = "cron"
                task.cron_expr = "17 4 * * *"
                task.interval_seconds = None
                task.enabled = enabled
                task.state = "W" if enabled else "P"

            await db.flush()
            await scheduler_manager.update_dynamic_job(task)
            if not enabled:
                await scheduler_manager.remove_dynamic_job(task.id)
            await db.commit()

    @staticmethod
    def _build_daily_cron_expr(run_time: str) -> str:
        parts = str(run_time or "09:00").split(":", 1)
        try:
            hour = max(0, min(23, int(parts[0])))
        except Exception:
            hour = 9
        try:
            minute = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
        except Exception:
            minute = 0
        return f"{minute} {hour} * * *"


hdhive_checkin_scheduler_service = HDHiveCheckinSchedulerService()
