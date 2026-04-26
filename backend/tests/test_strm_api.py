import pytest
from fastapi import HTTPException

from app.api.strm import _validate_strm_settings


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

    def test_validate_strm_settings_rejects_invalid_mode(self) -> None:
        """测试非法播放模式"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_strm_settings({"strm_redirect_mode": "invalid"})

        assert exc_info.value.status_code == 400

    def test_validate_strm_settings_rejects_invalid_base_url(self) -> None:
        """测试非法播放地址"""
        with pytest.raises(HTTPException) as exc_info:
            _validate_strm_settings({"strm_base_url": "not-a-url"})

        assert exc_info.value.status_code == 400
