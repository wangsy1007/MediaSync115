import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from app.api.strm import (
    StrmGenerateRequest,
    _validate_strm_settings,
    generate_strm_files,
)
from app.services.runtime_settings_service import RuntimeSettingsService


class TestStrmApi:
    """STRM API 校验测试"""

    def test_validate_strm_settings_allows_partial_save(self) -> None:
        """测试保存配置时不要求归档输出目录已配置"""
        _validate_strm_settings(
            {
                "strm_enabled": True,
                "strm_output_dir": "/app/strm",
                "strm_base_url": "http://192.168.1.2:9008",
                "strm_redirect_mode": "redirect",
            }
        )

    def test_validate_strm_settings_normalizes_legacy_auto_mode(self) -> None:
        _validate_strm_settings({"strm_redirect_mode": "auto"})

    def test_update_strm_config_persists_refresh_flags(self) -> None:
        service = RuntimeSettingsService.__new__(RuntimeSettingsService)
        service._data = dict(RuntimeSettingsService._defaults)
        service._save = lambda: None

        service.update_strm_config(
            {
                "strm_refresh_emby_after_generate": True,
                "strm_refresh_feiniu_after_generate": True,
                "strm_incremental_interval_minutes": 120,
            }
        )

        assert service.get_strm_refresh_emby_after_generate() is True
        assert service.get_strm_refresh_feiniu_after_generate() is True
        assert service.get_strm_incremental_interval_minutes() == 120

    def test_update_strm_config_normalizes_legacy_auto_mode(self) -> None:
        service = RuntimeSettingsService.__new__(RuntimeSettingsService)
        service._data = dict(RuntimeSettingsService._defaults)
        service._save = lambda: None

        service.update_strm_config({"strm_redirect_mode": "auto"})

        assert service.get_strm_redirect_mode() == "redirect"

    def test_validate_strm_settings_rejects_invalid_base_url(self) -> None:
        """测试非法播放地址"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_strm_settings({"strm_base_url": "not-a-url"})

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_generate_defaults_to_incremental(self, monkeypatch) -> None:
        start = AsyncMock(return_value={"started": True})
        monkeypatch.setattr("app.api.strm.strm_service.start_generate_library", start)

        await generate_strm_files(payload=None, mode=None)

        start.assert_awaited_once_with(trigger="manual", mode="incremental")

    @pytest.mark.asyncio
    async def test_generate_accepts_json_full_mode(self, monkeypatch) -> None:
        start = AsyncMock(return_value={"started": True})
        monkeypatch.setattr("app.api.strm.strm_service.start_generate_library", start)

        await generate_strm_files(
            payload=StrmGenerateRequest(mode="full"),
            mode=None,
        )

        start.assert_awaited_once_with(trigger="manual", mode="full")

    @pytest.mark.asyncio
    async def test_generate_rejects_invalid_mode(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await generate_strm_files(
                payload=StrmGenerateRequest(mode="invalid"),
                mode=None,
            )

        assert exc_info.value.status_code == 400

    def test_strm_schedule_config_validation(self) -> None:
        service = RuntimeSettingsService.__new__(RuntimeSettingsService)
        service._data = {
            "strm_incremental_interval_minutes": 360,
            "strm_full_schedule_day": "sun",
            "strm_full_schedule_time": "03:00",
        }
        service._save = lambda: None

        with pytest.raises(ValueError, match="1"):
            service.update_strm_config({"strm_incremental_interval_minutes": 0})
        with pytest.raises(ValueError, match="星期"):
            service.update_strm_config({"strm_full_schedule_day": "holiday"})
        with pytest.raises(ValueError, match="HH:MM"):
            service.update_strm_config({"strm_full_schedule_time": "25:00"})
