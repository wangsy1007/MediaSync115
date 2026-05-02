"""
115 转存互斥服务
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator


class TransferInProgressError(RuntimeError):
    """已有转存任务正在执行"""

    def __init__(self, current: dict[str, Any] | None = None) -> None:
        self.current = dict(current or {})
        operation = str(self.current.get("operation") or "未知转存任务")
        super().__init__(f"已有转存任务正在执行：{operation}，请等待完成后再试")


class TransferGuardService:
    """限制 115 转存任务同一时间只执行一个"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current: dict[str, Any] | None = None

    @asynccontextmanager
    async def acquire(self, operation: str) -> AsyncIterator[None]:
        """尝试获取转存互斥锁，已有任务时立即失败"""

        async with self._lock:
            if self._current is not None:
                raise TransferInProgressError(self._current)
            self._current = {
                "operation": str(operation or "115 转存"),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            yield
        finally:
            async with self._lock:
                self._current = None

    async def get_current(self) -> dict[str, Any] | None:
        """获取当前转存任务"""

        async with self._lock:
            return dict(self._current) if self._current else None


transfer_guard_service = TransferGuardService()
