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
                interval_hours = max(
                    1,
                    int(
                        settings_data.get(f"subscription_{channel}_interval_hours", 24)
                        or 24
                    ),
                )
                interval_seconds = interval_hours * 3600
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
                        trigger_type="interval",
                        cron_expr=None,
                        interval_seconds=interval_seconds,
                        kwargs_json=json.dumps({}, ensure_ascii=False),
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

    async def ensure_chart_subscription_task(self) -> None:
        """确保榜单订阅定时任务存在。"""
        settings_data = runtime_settings_service.get_all()
        enabled = bool(settings_data.get("chart_subscription_enabled", False))
        interval_hours = max(
            1,
            int(
                settings_data.get("chart_subscription_interval_hours", 24) or 24
            ),
        )
        interval_seconds = interval_hours * 3600
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
                    trigger_type="interval",
                    cron_expr=None,
                    interval_seconds=interval_seconds,
                    kwargs_json=json.dumps({}, ensure_ascii=False),
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
                task.name = "榜单订阅同步"
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

    async def ensure_tg_index_incremental_task(self) -> None:
        """确保 TG 索引自动增量同步定时任务存在（interval 触发器，最小间隔 15 分钟）。"""
        settings_data = runtime_settings_service.get_all()
        enabled = bool(settings_data.get("tg_index_enabled", False))
        raw_minutes = int(settings_data.get("tg_incremental_interval_minutes", 30) or 30)
        minutes = max(15, raw_minutes)
        interval_seconds = minutes * 60
        job_key = "tg.index.incremental"

        async with async_session_maker() as db:
            result = await db.execute(
                select(SchedulerTask)
                .where(SchedulerTask.job_key == job_key)
                .limit(1)
            )
            task = result.scalar_one_or_none()
            if not task:
                task = SchedulerTask(
                    name="TG 索引增量同步",
                    job_key=job_key,
                    trigger_type="interval",
                    cron_expr=None,
                    interval_seconds=interval_seconds,
                    kwargs_json=json.dumps({}, ensure_ascii=False),
                    enabled=enabled,
                    state="W" if enabled else "P",
                )
                db.add(task)
                await db.flush()
            else:
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


subscription_scheduler_service = SubscriptionSchedulerService()
