import asyncio

import pytest

from app.services.subscription_run_task_service import SubscriptionRunTaskService


class TestSubscriptionRunTaskServiceStart:
    """订阅后台任务启动测试"""

    @pytest.mark.asyncio
    async def test_start_returns_queued_task_dict_not_asyncio_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = SubscriptionRunTaskService()

        async def noop_run_task(
            task_id: str, channel: str, force_auto_download: bool
        ) -> None:
            return None

        monkeypatch.setattr(service, "_run_task", noop_run_task)
        monkeypatch.setattr(
            "app.services.subscription_run_task_service.operation_log_service.log_background_event",
            lambda *args, **kwargs: asyncio.sleep(0),
        )

        result = await service.start("all", force_auto_download=True)

        assert isinstance(result, dict)
        assert result.get("task_id")
        assert result.get("channel") == "all"
        assert result.get("status") == "queued"
        assert not asyncio.iscoroutine(result)
        assert not hasattr(result, "done")

    @pytest.mark.asyncio
    async def test_start_all_rejects_when_all_task_already_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = SubscriptionRunTaskService()

        async def noop_run_task(
            task_id: str, channel: str, force_auto_download: bool
        ) -> None:
            return None

        monkeypatch.setattr(service, "_run_task", noop_run_task)
        monkeypatch.setattr(
            "app.services.subscription_run_task_service.operation_log_service.log_background_event",
            lambda *args, **kwargs: asyncio.sleep(0),
        )

        first = await service.start("all", force_auto_download=True)
        second = await service.start("all", force_auto_download=True)

        assert first.get("already_running") is not True
        assert second.get("already_running") is True
        assert second.get("task_id") == first.get("task_id")
