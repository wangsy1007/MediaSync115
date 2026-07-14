"""探索转存队列与其他后台任务的协调守卫。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def defer_if_save_queue_busy(
    action_key: str,
    action: Callable[[], Awaitable[Any]],
) -> tuple[bool, Any | None]:
    """转存队列繁忙时延迟执行 action，返回 (deferred, result)。"""
    from app.services.explore_action_queue_service import explore_action_queue_service

    deferred = await explore_action_queue_service.defer_until_save_queue_idle(
        action_key,
        action,
    )
    if deferred:
        return True, None
    return False, await action()


async def is_save_queue_busy() -> bool:
    from app.services.explore_action_queue_service import explore_action_queue_service

    return await explore_action_queue_service.is_save_queue_busy()
