import pytest
from fastapi import HTTPException

from app.api.pan115 import SaveShareRequest, save_share_file
from app.services.transfer_guard_service import (
    TransferInProgressError,
    transfer_guard_service,
)


class TestTransferGuardService:
    """115 转存互斥测试"""

    @pytest.mark.asyncio
    async def test_rejects_concurrent_transfer(self) -> None:
        """测试已有转存执行时拒绝新转存"""

        async with transfer_guard_service.acquire("任务 A"):
            with pytest.raises(TransferInProgressError) as exc_info:
                async with transfer_guard_service.acquire("任务 B"):
                    pass

        assert "任务 A" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_pan115_endpoint_returns_conflict_when_transfer_running(self) -> None:
        """测试转存接口在互斥冲突时返回 409"""

        async with transfer_guard_service.acquire("订阅剧集精准转存"):
            with pytest.raises(HTTPException) as exc_info:
                await save_share_file(
                    SaveShareRequest(
                        share_code="share-code",
                        file_id="file-id",
                        receive_code="",
                    )
                )

        assert exc_info.value.status_code == 409
        assert "已有转存任务正在执行" in str(exc_info.value.detail)
