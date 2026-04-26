import pytest

from app.services.archive_service import archive_service
from app.services.media_postprocess_service import media_postprocess_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.strm_service import strm_service


class TestMediaPostprocessService:
    """媒体后处理服务测试"""

    @pytest.mark.asyncio
    async def test_trigger_archive_after_transfer(self, monkeypatch) -> None:
        """测试转存后自动触发归档"""
        monkeypatch.setattr(runtime_settings_service, "get_archive_enabled", lambda: True)
        monkeypatch.setattr(
            runtime_settings_service, "get_archive_auto_on_transfer", lambda: True
        )
        monkeypatch.setattr(runtime_settings_service, "get_archive_watch_cid", lambda: "1")

        called: dict[str, str] = {}

        async def fake_start_scan(trigger: str = "manual") -> dict:
            called["trigger"] = trigger
            return {"started": True}

        monkeypatch.setattr(archive_service, "start_scan", fake_start_scan)

        result = await media_postprocess_service.trigger_archive_after_transfer(
            trigger="subscription_transfer"
        )

        assert result["triggered"] is True
        assert called["trigger"] == "subscription_transfer"

    @pytest.mark.asyncio
    async def test_trigger_strm_after_archive(self, monkeypatch) -> None:
        """测试归档完成后自动触发 STRM 生成"""
        monkeypatch.setattr(runtime_settings_service, "get_strm_enabled", lambda: True)

        called: dict[str, str] = {}

        async def fake_start_generate_library(trigger: str = "manual") -> dict:
            called["trigger"] = trigger
            return {"success": True, "started": True}

        monkeypatch.setattr(
            strm_service, "start_generate_library", fake_start_generate_library
        )

        result = await media_postprocess_service.trigger_strm_after_archive(
            {"success": 1, "skipped": 0},
            trigger="archive_subscription_transfer",
        )

        assert result["triggered"] is True
        assert called["trigger"] == "archive_subscription_transfer"

    @pytest.mark.asyncio
    async def test_skip_strm_when_no_processed_items(self, monkeypatch) -> None:
        """测试没有归档成果时跳过 STRM 生成"""
        monkeypatch.setattr(runtime_settings_service, "get_strm_enabled", lambda: True)

        result = await media_postprocess_service.trigger_strm_after_archive(
            {"success": 0, "skipped": 0, "failed": 3},
            trigger="archive_transfer",
        )

        assert result == {"triggered": False, "reason": "no_processed_items"}
