"""转存队列与定时任务协调测试。"""

from unittest.mock import AsyncMock

import pytest

from app.services.explore_action_queue_service import ExploreActionQueueService


@pytest.mark.asyncio
async def test_is_save_queue_busy_when_queued_or_running() -> None:
    service = ExploreActionQueueService()
    assert await service.is_save_queue_busy() is False

    async with service._lock:
        service._save_queue = ["task-1"]
    assert await service.is_save_queue_busy() is True

    async with service._lock:
        service._save_queue = []
        service._tasks["task-2"] = {
            "task_id": "task-2",
            "queue_type": "save",
            "status": "running",
        }
    assert await service.is_save_queue_busy() is True


@pytest.mark.asyncio
async def test_flush_deferred_when_idle_runs_deferred_actions(monkeypatch) -> None:
    service = ExploreActionQueueService()
    trigger_mock = AsyncMock(return_value={"triggered": True})
    deferred_action = AsyncMock(return_value={"started": True})

    monkeypatch.setattr(
        "app.services.explore_action_queue_service.media_postprocess_service.trigger_archive_after_transfer",
        trigger_mock,
    )

    async with service._lock:
        service._save_archive_deferred = True
        service._deferred_idle_actions["scheduler:archive_scan"] = deferred_action

    await service._flush_deferred_when_idle()
    deferred_action.assert_awaited_once()
    trigger_mock.assert_awaited_once_with(
        trigger="explore_transfer",
        respect_save_queue=False,
    )
    assert service._deferred_idle_actions == {}
    assert service._save_archive_deferred is False


@pytest.mark.asyncio
async def test_flush_deferred_when_idle_waits_for_running_save(monkeypatch) -> None:
    service = ExploreActionQueueService()
    trigger_mock = AsyncMock()
    deferred_action = AsyncMock()

    monkeypatch.setattr(
        "app.services.explore_action_queue_service.media_postprocess_service.trigger_archive_after_transfer",
        trigger_mock,
    )

    async with service._lock:
        service._save_archive_deferred = True
        service._deferred_idle_actions["scheduler:archive_scan"] = deferred_action
        service._tasks["running-task"] = {
            "task_id": "running-task",
            "queue_type": "save",
            "status": "running",
        }

    await service._flush_deferred_when_idle()
    trigger_mock.assert_not_called()
    deferred_action.assert_not_called()
    assert service._save_archive_deferred is True
    assert "scheduler:archive_scan" in service._deferred_idle_actions


@pytest.mark.asyncio
async def test_defer_until_save_queue_idle() -> None:
    service = ExploreActionQueueService()
    action = AsyncMock(return_value={"ok": True})

    async with service._lock:
        service._save_queue = ["pending"]

    deferred = await service.defer_until_save_queue_idle("test:action", action)
    assert deferred is True
    action.assert_not_called()
    assert "test:action" in service._deferred_idle_actions

    async with service._lock:
        service._save_queue = []

    deferred = await service.defer_until_save_queue_idle("test:action", action)
    assert deferred is False
    action.assert_awaited_once()
