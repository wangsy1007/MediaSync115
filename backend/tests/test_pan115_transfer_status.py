import pytest

from app.api.pan115 import get_pan115_transfer_status
from app.services.operation_log_service import operation_log_service
from app.services.transfer_guard_service import transfer_guard_service


class TestPan115TransferStatus:
    """115 转存状态接口测试"""

    @pytest.mark.asyncio
    async def test_transfer_status_idle(self) -> None:
        payload = await get_pan115_transfer_status(folder_name=None)

        assert payload["in_progress"] is False
        assert payload["current"] is None

    @pytest.mark.asyncio
    async def test_transfer_status_in_progress(self) -> None:
        async with transfer_guard_service.acquire("测试转存"):
            payload = await get_pan115_transfer_status(folder_name=None)

            assert payload["in_progress"] is True
            assert payload["current"]["operation"] == "测试转存"

    @pytest.mark.asyncio
    async def test_transfer_status_recent_result(self) -> None:
        await operation_log_service.log_background_event(
            source_type="user_action",
            module="pan115",
            action="transfer.save_to_folder",
            status="success",
            message="[手动] 一键转存成功：测试剧集",
            extra={"folder_name": "测试剧集"},
        )

        payload = await get_pan115_transfer_status(folder_name="测试剧集")

        assert payload["recent_result"]["status"] == "success"
        assert "测试剧集" in payload["recent_result"]["message"]
