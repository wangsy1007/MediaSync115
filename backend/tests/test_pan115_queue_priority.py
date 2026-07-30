import asyncio
import time

import pytest

from app.services.pan115_service import _Pan115QueueExecutor, _QueueRequest


def _enqueue(
    executor: _Pan115QueueExecutor,
    coro_factory,
    *,
    operation: str,
    playback: bool = False,
) -> asyncio.Future:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    executor.enqueue(
        _QueueRequest(
            coro_factory=coro_factory,
            future=future,
            operation=operation,
            queued_at=time.monotonic(),
            bypass_rate_limit=playback,
        )
    )
    return future


@pytest.mark.asyncio
async def test_playback_lane_is_not_blocked_by_background_workers():
    executor = _Pan115QueueExecutor(
        qps=100,
        qpm=1000,
        qph=10000,
        worker_count=2,
    )
    release = asyncio.Event()
    both_started = asyncio.Event()
    started_count = 0

    async def blocked_background():
        nonlocal started_count
        started_count += 1
        if started_count == 2:
            both_started.set()
        await release.wait()
        return "background"

    background_futures = [
        _enqueue(executor, blocked_background, operation="fs_files"),
        _enqueue(executor, blocked_background, operation="fs_search"),
    ]

    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)

        async def resolve_playback():
            return "playback"

        playback_future = _enqueue(
            executor,
            resolve_playback,
            operation="download_url_app",
            playback=True,
        )
        assert await asyncio.wait_for(playback_future, timeout=0.5) == "playback"
    finally:
        for future in background_futures:
            future.cancel()
        release.set()
        await executor.stop()


def test_bulk_probe_user_agent_detection():
    from app.services.pan115_service import _is_bulk_probe_user_agent

    assert _is_bulk_probe_user_agent("curl/7.88.1") is True
    assert _is_bulk_probe_user_agent("Wget/1.21") is True
    assert _is_bulk_probe_user_agent("python-requests/2.31.0") is True
    assert _is_bulk_probe_user_agent("HosPlayer/1.0") is False
    assert _is_bulk_probe_user_agent("Emby/4.8") is False
    assert _is_bulk_probe_user_agent("") is False


@pytest.mark.asyncio
async def test_cancelled_caller_cancels_inflight_115_operation():
    executor = _Pan115QueueExecutor(
        qps=100,
        qpm=1000,
        qph=10000,
        worker_count=2,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def inflight_operation():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    future = _enqueue(executor, inflight_operation, operation="fs_files")
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        future.cancel()
        with pytest.raises(asyncio.CancelledError):
            await future
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        await executor.stop()
