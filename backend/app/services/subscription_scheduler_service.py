import json

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.scheduler import scheduler_manager
from app.services.runtime_settings_service import runtime_settings_service


class SubscriptionSchedulerService:
    async def ensure_subscription_tasks(self) -> None:
        settings_data = runtime_settings_service.get_all()
        channels = (
            ("hdhive", "HDHive 订阅检查"),
            ("pansou", "Pansou 订阅检查"),
            ("tg", "Telegram 订阅检查"),
        )

        async with async_session_maker() as db:
            for channel, display_name in channels:
                enabled = bool(
                    settings_data.get(f"subscription_{channel}_enabled", False)
                )
                interval_hours = int(
                    settings_data.get(f"subscription_{channel}_interval_hours", 24)
                    or 24
                )
                run_time = str(
                    settings_data.get(f"subscription_{channel}_run_time", "03:00")
                    or "03:00"
                )
                cron_expr = self._build_cron_expr(interval_hours, run_time)
                job_key = f"subscription.check_{channel}"

                result = await db.execute(
                    select(SchedulerTask)
                    .where(SchedulerTask.job_key == job_key)
                    .limit(1)
                )
                task = result.scalar_one_or_none()
                if not task:
                    task = SchedulerTask(
                        name=display_name,
                        job_key=job_key,
                        trigger_type="cron",
                        cron_expr=cron_expr,
                        interval_seconds=None,
                        kwargs_json=json.dumps({}, ensure_ascii=False),
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

    async def ensure_chart_subscription_task(self) -> None:
        """确保榜单订阅定时任务存在。"""
        settings_data = runtime_settings_service.get_all()
        enabled = bool(settings_data.get("chart_subscription_enabled", False))
        interval_hours = int(
            settings_data.get("chart_subscription_interval_hours", 24) or 24
        )
        run_time = str(
            settings_data.get("chart_subscription_run_time", "02:00") or "02:00"
        )
        cron_expr = self._build_cron_expr(interval_hours, run_time)
        job_key = "chart_subscription.sync"

        async with async_session_maker() as db:
            result = await db.execute(
                select(SchedulerTask).where(SchedulerTask.job_key == job_key).limit(1)
            )
            task = result.scalar_one_or_none()
            if not task:
                task = SchedulerTask(
                    name="榜单订阅同步",
                    job_key=job_key,
                    trigger_type="cron",
                    cron_expr=cron_expr,
                    interval_seconds=None,
                    kwargs_json=json.dumps({}, ensure_ascii=False),
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
                task.name = "榜单订阅同步"
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

    @staticmethod
    def _build_cron_expr(interval_hours: int, run_time: str) -> str:
        hours = max(1, min(24, int(interval_hours or 24)))
        parts = str(run_time or "03:00").split(":", 1)
        try:
            hour = max(0, min(23, int(parts[0])))
        except Exception:
            hour = 3
        try:
            minute = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
        except Exception:
            minute = 0

        if hours >= 24:
            hour_expr = str(hour)
        else:
            hour_expr = f"{hour}-23/{hours}"
        return f"{minute} {hour_expr} * * *"


subscription_scheduler_service = SubscriptionSchedulerService()
