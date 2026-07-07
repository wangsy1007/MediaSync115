"""调度器执行超时看门狗测试。

回归 2026-06-27 的事故：subscription.check 单轮卡死后，因 max_instances=1 +
内存 running 标志未复位，整个 job 永久停摆。此处验证 start() 的硬超时能取消
卡死任务并复位 running 标志，使下一轮可正常触发。
"""
import asyncio

import pytest

from app.models.scheduler_task import SchedulerTask
from app.scheduler import (
    DEFAULT_JOB_TIMEOUT_SECONDS,
    MIN_JOB_TIMEOUT_SECONDS,
    SchedulerManager,
    scheduler_manager,
)
from app.services.operation_log_service import operation_log_service as op_log_service


async def _noop(*_args, **_kwargs):
    return None


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch):
    """屏蔽调度器对 operation_logs / DB 的依赖，聚焦超时逻辑。"""
    monkeypatch.setattr(op_log_service, "log_background_event", _noop)
    monkeypatch.setattr(scheduler_manager, "_mark_job_result", _noop)
    yield


def _register_job(job_id: str, func, *, timeout: float) -> None:
    scheduler_manager._jobs[job_id] = {
        "func": func,
        "kwargs": {},
        "running": False,
        "kind": "dynamic",
        "ref_id": None,
        "timeout": timeout,
    }


async def test_start_kills_hung_job_on_timeout():
    job_id = "test:hung:timeout"
    release = asyncio.Event()

    async def _hung(**_kwargs):
        await release.wait()  # 永远不主动返回
        return {"ok": True}

    _register_job(job_id, _hung, timeout=0.3)
    try:
        result = await scheduler_manager.start(job_id)
        assert result["success"] is False
        assert "timed out" in result["message"]
        # 关键：running 标志必须复位，否则后续轮次会被 max_instances 永久跳过
        assert scheduler_manager._jobs[job_id]["running"] is False
    finally:
        release.set()
        scheduler_manager._jobs.pop(job_id, None)


async def test_start_returns_success_on_fast_job():
    job_id = "test:fast:success"

    def _fast(**_kwargs):
        return {"ok": True}

    _register_job(job_id, _fast, timeout=5.0)
    try:
        result = await scheduler_manager.start(job_id)
        assert result["success"] is True
        assert scheduler_manager._jobs[job_id]["running"] is False
    finally:
        scheduler_manager._jobs.pop(job_id, None)


def _make_task(trigger_type, interval_seconds=None) -> SchedulerTask:
    return SchedulerTask(trigger_type=trigger_type, interval_seconds=interval_seconds)


def test_derive_job_timeout_interval_clamped_to_cap():
    # 3 小时间隔 -> 0.8*10800=8640，夹到 2h 上限
    assert (
        SchedulerManager._derive_job_timeout(_make_task("interval", 10800))
        == DEFAULT_JOB_TIMEOUT_SECONDS
    )


def test_derive_job_timeout_interval_proportional():
    # 15 分钟间隔 -> 0.8*900=720s
    assert SchedulerManager._derive_job_timeout(_make_task("interval", 900)) == 720


def test_derive_job_timeout_interval_floored_to_min():
    # 极小间隔 -> 5 分钟下限
    assert (
        SchedulerManager._derive_job_timeout(_make_task("interval", 60))
        == MIN_JOB_TIMEOUT_SECONDS
    )


def test_derive_job_timeout_cron_uses_default():
    assert (
        SchedulerManager._derive_job_timeout(_make_task("cron"))
        == DEFAULT_JOB_TIMEOUT_SECONDS
    )
    assert (
        SchedulerManager._derive_job_timeout(_make_task(None))
        == DEFAULT_JOB_TIMEOUT_SECONDS
    )
