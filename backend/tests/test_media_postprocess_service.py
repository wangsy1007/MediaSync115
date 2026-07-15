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

        async def fake_start_scan(
            trigger: str = "manual", **kwargs: object
        ) -> dict:
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
        monkeypatch.setattr(
            runtime_settings_service, "get_strm_auto_after_archive", lambda: True
        )

        called: dict = {}

        async def fake_start_generate_library(
            trigger: str = "manual",
            mode: str = "full",
            scopes: list[dict] | None = None,
        ) -> dict:
            called["trigger"] = trigger
            called["mode"] = mode
            called["scopes"] = scopes
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
        assert called["mode"] == "incremental"
        assert called["scopes"] is None

    @pytest.mark.asyncio
    async def test_skip_strm_when_auto_after_archive_disabled(self, monkeypatch) -> None:
        """关闭「归档后自动生成 STRM」时应跳过"""
        monkeypatch.setattr(runtime_settings_service, "get_strm_enabled", lambda: True)
        monkeypatch.setattr(
            runtime_settings_service, "get_strm_auto_after_archive", lambda: False
        )

        result = await media_postprocess_service.trigger_strm_after_archive(
            {"success": 1, "skipped": 0},
            trigger="archive_manual",
        )

        assert result == {
            "triggered": False,
            "reason": "strm_auto_after_archive_disabled",
        }

    @pytest.mark.asyncio
    async def test_trigger_strm_forwards_deduplicated_archive_scopes(
        self, monkeypatch
    ) -> None:
        """测试归档成果转换为去重后的 STRM 增量范围"""
        monkeypatch.setattr(runtime_settings_service, "get_strm_enabled", lambda: True)
        monkeypatch.setattr(
            runtime_settings_service, "get_strm_auto_after_archive", lambda: True
        )

        called: dict = {}

        async def fake_start_generate_library(**kwargs) -> dict:
            called.update(kwargs)
            return {"success": True, "started": True}

        monkeypatch.setattr(
            strm_service, "start_generate_library", fake_start_generate_library
        )
        successful_item = {
            "status": "success",
            "source_fid": "fid-1",
            "target_cid": "cid-1",
            "target_desc": "电影/华语电影/测试电影 (2026)",
        }

        result = await media_postprocess_service.trigger_strm_after_archive(
            {
                "success": 1,
                "skipped": 1,
                "items": [
                    successful_item,
                    {**successful_item, "status": "skipped"},
                    {
                        "status": "failed",
                        "source_fid": "fid-2",
                        "target_cid": "cid-2",
                        "target_desc": "电影/外语电影/失败电影 (2026)",
                    },
                ],
            },
            trigger="archive_manual",
        )

        assert result["triggered"] is True
        assert called == {
            "trigger": "archive_manual",
            "mode": "incremental",
            "scopes": [
                {
                    "fid": "fid-1",
                    "target_cid": "cid-1",
                    "relative_prefix": "电影/华语电影/测试电影 (2026)",
                }
            ],
            "respect_save_queue": False,
        }

    @pytest.mark.asyncio
    async def test_skip_strm_when_no_processed_items(self, monkeypatch) -> None:
        """测试没有归档成果时跳过 STRM 生成"""
        monkeypatch.setattr(runtime_settings_service, "get_strm_enabled", lambda: True)
        monkeypatch.setattr(
            runtime_settings_service, "get_strm_auto_after_archive", lambda: True
        )

        result = await media_postprocess_service.trigger_strm_after_archive(
            {"success": 0, "skipped": 0, "failed": 3},
            trigger="archive_transfer",
        )

        assert result == {"triggered": False, "reason": "no_processed_items"}

    @pytest.mark.asyncio
    async def test_trigger_media_sync_after_subscription_transfer(
        self, monkeypatch
    ) -> None:
        """订阅转存完成后应触发已启用的媒体库同步"""
        monkeypatch.setattr(
            runtime_settings_service,
            "get_subscription_auto_sync_after_transfer",
            lambda: True,
        )
        monkeypatch.setattr(
            runtime_settings_service, "get_emby_sync_enabled", lambda: True
        )
        monkeypatch.setattr(
            runtime_settings_service, "get_feiniu_sync_enabled", lambda: False
        )

        called: dict[str, str] = {}

        async def fake_start_background_sync(
            trigger: str = "manual", **kwargs: object
        ) -> dict:
            called["trigger"] = trigger
            return {"success": True, "started": True, "message": "Emby 同步任务已启动"}

        monkeypatch.setattr(
            "app.services.emby_sync_index_service.emby_sync_index_service.start_background_sync",
            fake_start_background_sync,
        )

        result = (
            await media_postprocess_service.trigger_media_library_sync_after_subscription_transfer(
                transfer_count=2,
            )
        )

        assert result["triggered"] is True
        assert result["started"] is True
        assert called["trigger"] == "subscription_transfer"

    @pytest.mark.asyncio
    async def test_skip_media_sync_when_disabled(self, monkeypatch) -> None:
        """关闭订阅转存后同步时应跳过"""
        monkeypatch.setattr(
            runtime_settings_service,
            "get_subscription_auto_sync_after_transfer",
            lambda: False,
        )

        result = (
            await media_postprocess_service.trigger_media_library_sync_after_subscription_transfer(
                transfer_count=1,
            )
        )

        assert result == {
            "triggered": False,
            "reason": "subscription_auto_sync_after_transfer_disabled",
        }
