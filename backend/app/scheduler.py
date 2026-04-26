import asyncio
import json
import logging
from datetime import datetime
from threading import Lock
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.scheduler_task import SchedulerTask
from app.models.workflow import Workflow
from app.services.job_registry import job_registry
from app.services.operation_log_service import operation_log_service
from app.services.workflow_executor import workflow_executor
from app.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class SchedulerManager:
    _instance = None
    _instance_lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        timezone = getattr(settings, "TZ", "Asia/Shanghai")
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._run_lock = Lock()
        self._initialized = True

    async def init(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

        await self.load_dynamic_jobs()
        await self.load_workflow_jobs()

    async def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.remove_all_jobs()
            self.scheduler.shutdown(wait=False)
        self._jobs.clear()

    async def load_dynamic_jobs(self) -> None:
        async with async_session_maker() as db:
            result = await db.execute(select(SchedulerTask).where(SchedulerTask.enabled == True))  # noqa: E712
            tasks = result.scalars().all()

        for task in tasks:
            await self.update_dynamic_job(task)

    async def load_workflow_jobs(self) -> None:
        async with async_session_maker() as db:
            workflows = await WorkflowService(db).list_enabled_timer_workflows()
        for workflow in workflows:
            await self.update_workflow_job(workflow)

    async def start(self, job_id: str, *, force: bool = False) -> dict[str, Any]:
        meta = self._jobs.get(job_id)
        if not meta:
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="scheduler",
                action="scheduler.job.start",
                status="warning",
                message=f"调度任务不存在: {job_id}",
                trace_id=job_id,
            )
            return {"success": False, "message": f"job not found: {job_id}"}

        with self._run_lock:
            if meta.get("running"):
                if force:
                    logger.warning("Force-resetting stuck running flag for job: %s", job_id)
                    meta["running"] = False
                else:
                    await operation_log_service.log_background_event(
                        source_type="scheduler",
                        module="scheduler",
                        action="scheduler.job.start",
                        status="warning",
                        message=f"调度任务已在运行: {job_id}",
                        trace_id=job_id,
                    )
                    return {"success": False, "message": f"job is already running: {job_id}"}
            meta["running"] = True
        await operation_log_service.log_background_event(
            source_type="scheduler",
            module="scheduler",
            action="scheduler.job.start",
            status="info",
            message=f"调度任务开始执行: {job_id}",
            trace_id=job_id,
        )

        try:
            func = meta.get("func")
            kwargs = dict(meta.get("kwargs") or {})
            result = await self._run_callable(func, kwargs)
            run_ok = True
            run_error = ""
        except Exception as exc:
            logger.exception("Scheduled job failed: %s", job_id)
            result = None
            run_ok = False
            run_error = str(exc)
        persist_error = ""
        try:
            await self._mark_job_result(job_id, run_ok, result if run_ok else run_error)
        except Exception as exc:
            persist_error = str(exc)
            logger.exception("Failed to persist scheduled job result: %s", job_id)
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="scheduler",
                action="scheduler.job.result_persist_failed",
                status="warning",
                message=f"调度任务结果持久化失败: {job_id}",
                trace_id=job_id,
                extra={"error": persist_error[:500]},
            )
        try:
            finish_status = "success" if run_ok and not persist_error else ("warning" if run_ok else "failed")
            finish_message = (
                f"调度任务执行成功: {job_id}"
                if run_ok
                else f"调度任务执行失败: {job_id}"
            )
            finish_extra: dict[str, Any] = {"result": result} if run_ok else {"error": run_error}
            if persist_error:
                finish_extra["persist_error"] = persist_error[:500]
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="scheduler",
                action="scheduler.job.finish",
                status=finish_status,
                message=finish_message,
                trace_id=job_id,
                extra=finish_extra,
            )
        except Exception:
            logger.exception("Failed to write scheduler finish log: %s", job_id)
        finally:
            with self._run_lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["running"] = False
        if run_ok:
            return {"success": True, "result": result, "persist_error": persist_error or None}
        return {"success": False, "message": run_error, "persist_error": persist_error or None}

    async def run_now(self, job_id: str, *, force: bool = False) -> dict[str, Any]:
        meta = self._jobs.get(job_id)
        if meta and meta.get("kind") == "dynamic":
            ref_id = meta.get("ref_id")
            if ref_id:
                async with async_session_maker() as db:
                    task = await db.get(SchedulerTask, int(ref_id))
                    if task and not task.enabled:
                        if not force:
                            return {"success": False, "message": f"task is disabled: {job_id}"}
        return await self.start(job_id, force=force)

    async def trigger_event_workflows(self, event_type: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        async with async_session_maker() as db:
            workflows = await WorkflowService(db).list_enabled_event_workflows(event_type)

        if not workflows:
            return []

        results = []
        for workflow in workflows:
            result = await self.run_workflow_once(workflow.id, payload=payload or {})
            results.append({"workflow_id": workflow.id, **result})
        return results

    async def run_workflow_once(self, workflow_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        job_id = self._workflow_job_id(workflow_id)
        if job_id not in self._jobs:
            self._jobs[job_id] = {
                "func": self._build_workflow_callable(workflow_id, trigger_payload=payload or {}),
                "kwargs": {},
                "running": False,
                "kind": "workflow",
                "ref_id": workflow_id,
            }
        return await self.start(job_id)

    async def update_dynamic_job(self, task: SchedulerTask) -> None:
        job_id = self._dynamic_job_id(task.id)
        self.remove_job(job_id)

        func = job_registry.get(task.job_key)
        if not func:
            logger.warning("Unknown job_key for task %s: %s", task.id, task.job_key)
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="scheduler",
                action="scheduler.job.update",
                status="warning",
                message=f"未知任务类型: {task.job_key}",
                trace_id=self._dynamic_job_id(task.id),
                extra={"task_id": task.id, "job_key": task.job_key},
            )
            return

        kwargs = self._parse_json(task.kwargs_json, {})
        self._jobs[job_id] = {
            "func": func,
            "kwargs": kwargs,
            "running": False,
            "kind": "dynamic",
            "ref_id": task.id,
        }

        if not task.enabled:
            return

        normalized_trigger = (task.trigger_type or "").strip().lower()
        if normalized_trigger == "interval":
            seconds = int(task.interval_seconds or 0)
            if seconds <= 0:
                raise ValueError("interval trigger requires interval_seconds > 0")
            trigger = IntervalTrigger(seconds=seconds)
            self.scheduler.add_job(
                self.start,
                trigger=trigger,
                kwargs={"job_id": job_id},
                id=job_id,
                name=task.name,
                coalesce=True,
                misfire_grace_time=None,
                max_instances=1,
                replace_existing=True,
            )
        else:
            trigger = self._build_cron_trigger(task.cron_expr)
            self.scheduler.add_job(
                self.start,
                trigger=trigger,
                kwargs={"job_id": job_id},
                id=job_id,
                name=task.name,
                coalesce=True,
                misfire_grace_time=None,
                max_instances=1,
                replace_existing=True,
            )

    async def remove_dynamic_job(self, task_id: int) -> None:
        self.remove_job(self._dynamic_job_id(task_id))

    async def update_workflow_job(self, workflow: Workflow) -> None:
        job_id = self._workflow_job_id(workflow.id)
        self.remove_job(job_id)

        self._jobs[job_id] = {
            "func": self._build_workflow_callable(workflow.id),
            "kwargs": {},
            "running": False,
            "kind": "workflow",
            "ref_id": workflow.id,
        }

        if workflow.trigger_type != "timer" or workflow.state != "W" or not workflow.timer:
            return

        trigger = CronTrigger.from_crontab(str(workflow.timer).strip())
        self.scheduler.add_job(
            self.start,
            trigger=trigger,
            kwargs={"job_id": job_id},
            id=job_id,
            name=f"workflow:{workflow.name}",
            coalesce=True,
            misfire_grace_time=None,
            max_instances=1,
            replace_existing=True,
        )

    async def remove_workflow_job(self, workflow_id: int) -> None:
        self.remove_job(self._workflow_job_id(workflow_id))

    def remove_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for job in self.scheduler.get_jobs():
            meta = self._jobs.get(job.id, {})
            rows.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "running": bool(meta.get("running", False)),
                    "kind": meta.get("kind"),
                }
            )
        for job_id, meta in self._jobs.items():
            if any(item["id"] == job_id for item in rows):
                continue
            rows.append(
                {
                    "id": job_id,
                    "name": job_id,
                    "next_run_time": None,
                    "running": bool(meta.get("running", False)),
                    "kind": meta.get("kind"),
                }
            )
        return rows

    async def _mark_job_result(self, job_id: str, success: bool, result: Any) -> None:
        meta = self._jobs.get(job_id, {})
        kind = meta.get("kind")
        ref_id = meta.get("ref_id")
        if kind == "dynamic" and ref_id:
            await self._mark_dynamic_result(int(ref_id), success, result)
        elif kind == "workflow" and ref_id:
            await self._mark_workflow_result(int(ref_id), success, result)

    async def _mark_dynamic_result(self, task_id: int, success: bool, result: Any) -> None:
        async with async_session_maker() as db:
            task = await db.get(SchedulerTask, task_id)
            if not task:
                return
            task.last_run_at = datetime.utcnow()
            task.last_error = None if success else str(result)
            task.state = "W" if success else "E"
            await db.commit()

    async def _mark_workflow_result(self, workflow_id: int, success: bool, result: Any) -> None:
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, workflow_id)
            if not workflow:
                return
            workflow.last_run_at = datetime.utcnow()
            workflow.last_result = json.dumps(
                {
                    "success": success,
                    "result": result,
                    "at": datetime.utcnow().isoformat(),
                },
                ensure_ascii=False,
            )
            workflow.current_action = None
            workflow.run_count = int(workflow.run_count or 0) + 1
            await db.commit()

    def _build_workflow_callable(self, workflow_id: int, trigger_payload: dict[str, Any] | None = None) -> Callable[..., Any]:
        async def _run_workflow(**kwargs):
            async with async_session_maker() as db:
                service = WorkflowService(db)
                workflow = await service.get(workflow_id)
                if not workflow:
                    raise ValueError(f"workflow not found: {workflow_id}")

                actions = service.parse_json_field(workflow.actions, [])
                flows = service.parse_json_field(workflow.flows, [])
                context = service.parse_json_field(workflow.context, {})
                if not isinstance(context, dict):
                    context = {}
                context.update(trigger_payload or {})
                context.update(kwargs or {})

                ok, message, output_context = await workflow_executor.execute(
                    workflow_id=workflow.id,
                    actions=actions,
                    flows=flows,
                    context=context,
                )
                if output_context:
                    workflow.context = json.dumps(output_context, ensure_ascii=False)
                await service.mark_result(workflow.id, ok, message)
                if not ok:
                    raise RuntimeError(message)
                return {"success": ok, "message": message, "context": output_context}

        return _run_workflow

    async def _run_callable(self, func: Callable[..., Any] | None, kwargs: dict[str, Any]) -> Any:
        if not func:
            raise ValueError("job callable is empty")

        result = func(**kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    @staticmethod
    def _build_cron_trigger(cron_expr: str | None):
        if not cron_expr:
            raise ValueError("cron trigger requires cron_expr")
        return CronTrigger.from_crontab(str(cron_expr).strip())

    @staticmethod
    def _parse_json(raw: str | None, default: Any):
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    @staticmethod
    def _dynamic_job_id(task_id: int) -> str:
        return f"dynamic:{task_id}"

    @staticmethod
    def _workflow_job_id(workflow_id: int) -> str:
        return f"workflow:{workflow_id}"


scheduler_manager = SchedulerManager()
