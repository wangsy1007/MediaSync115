"""探索转存队列归档延迟触发测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.explore_action_queue_service import ExploreActionQueueService


@pytest.mark.asyncio
async def test_flush_deferred_archive_waits_until_save_queue_idle(monkeypatch) -> None:
    service = ExploreActionQueueService()
    trigger_mock = AsyncMock(return_value={"triggered": True})

    monkeypatch.setattr(
        "app.services.explore_action_queue_service.media_postprocess_service.trigger_archive_after_transfer",
        trigger_mock,
    )

    async with service._lock:
        service._save_archive_deferred = True
        service._save_queue = ["pending-task"]

    await service._flush_deferred_when_idle()
    trigger_mock.assert_not_called()
    assert service._save_archive_deferred is True

    async with service._lock:
        service._save_queue = []

    await service._flush_deferred_when_idle()
    trigger_mock.assert_awaited_once_with(
        trigger="explore_transfer",
        respect_save_queue=False,
    )
    assert service._save_archive_deferred is False


@pytest.mark.asyncio
async def test_archive_start_scan_queues_followup_when_busy() -> None:
    from app.services.archive_service import ArchiveService

    service = ArchiveService()
    mock_task = MagicMock()
    mock_task.done.return_value = False
    service._background_scan_task = mock_task

    first = await service.start_scan(trigger="explore_transfer")
    assert first["started"] is False
    assert first.get("queued") is True
    assert service._pending_rescan is True

    second = await service.start_scan(trigger="explore_transfer_batch")
    assert service._pending_rescan_trigger == "explore_transfer_batch"
