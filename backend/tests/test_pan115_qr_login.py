"""115 扫码登录设备列表与状态解析测试"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.constants.pan115_qr_login import (
    PAN115_QR_LOGIN_ALLOWED_APPS,
    list_pan115_qr_login_app_options,
    normalize_pan115_qr_login_app,
)
from app.core.timezone_utils import beijing_now
from app.services.pan115_service import Pan115Service


class TestPan115QrLoginApps:
    def test_normalize_rejects_unknown_app(self) -> None:
        assert normalize_pan115_qr_login_app("web") == "alipaymini"
        assert normalize_pan115_qr_login_app("bios") == "alipaymini"
        assert normalize_pan115_qr_login_app("os_windows") == "alipaymini"

    def test_normalize_keeps_valid_app(self) -> None:
        assert normalize_pan115_qr_login_app("wechatmini") == "wechatmini"
        assert normalize_pan115_qr_login_app("qandroid") == "qandroid"

    def test_list_options_match_allowed_set(self) -> None:
        items = list_pan115_qr_login_app_options()
        values = {item["value"] for item in items}
        assert values == set(PAN115_QR_LOGIN_ALLOWED_APPS)
        assert "web" not in values
        assert "alipaymini" in values


class TestPan115QrStatusParsing:
    def test_parse_qr_status_from_data(self) -> None:
        code, msg = Pan115Service._parse_qr_status(
            {"data": {"status": 1, "msg": "scanned"}}
        )
        assert code == 1
        assert msg == "scanned"

    def test_parse_qr_status_from_top_level(self) -> None:
        code, msg = Pan115Service._parse_qr_status({"status": "2", "message": "ok"})
        assert code == 2
        assert msg == "ok"

    def test_timeout_error_detection(self) -> None:
        assert Pan115Service._is_qr_status_timeout_error("Read timed out")
        assert Pan115Service._is_qr_status_timeout_error("TimeoutError()")
        assert not Pan115Service._is_qr_status_timeout_error("invalid uid")


@pytest.mark.asyncio
async def test_check_qr_status_timeout_keeps_pending(monkeypatch) -> None:
    service = Pan115Service()
    token = "tok-timeout"
    Pan115Service._QR_LOGIN_PENDING[token] = {
        "token": token,
        "uid": "uid-1",
        "scan_payload": {"uid": "uid-1", "time": 1, "sign": "s"},
        "qr_url": "https://115.com/scan/dg-uid-1",
        "app": "alipaymini",
        "state": "pending",
        "message": "等待扫码",
        "created_at": beijing_now(),
        "expires_at": beijing_now() + timedelta(minutes=3),
        "cookie": "",
    }

    class _FakeClient:
        @staticmethod
        async def login_qrcode_scan_status(*_a, **_k):
            raise asyncio.TimeoutError()

    monkeypatch.setattr(
        "app.services.pan115_service._get_p115_client_cls",
        lambda: _FakeClient,
    )

    result = await service.check_qr_login_status(token)
    assert result["pending"] is True
    assert result["authorized"] is False
    assert "等待" in result["message"]


@pytest.mark.asyncio
async def test_check_qr_status_authorized_with_cookie(monkeypatch) -> None:
    service = Pan115Service()
    token = "tok-ok"
    Pan115Service._QR_LOGIN_PENDING[token] = {
        "token": token,
        "uid": "uid-2",
        "scan_payload": {"uid": "uid-2", "time": 1, "sign": "s"},
        "qr_url": "https://115.com/scan/dg-uid-2",
        "app": "alipaymini",
        "state": "pending",
        "message": "等待扫码",
        "created_at": beijing_now(),
        "expires_at": beijing_now() + timedelta(minutes=3),
        "cookie": "",
    }

    class _FakeClient:
        @staticmethod
        async def login_qrcode_scan_status(*_a, **_k):
            return {"data": {"status": 2}}

    monkeypatch.setattr(
        "app.services.pan115_service._get_p115_client_cls",
        lambda: _FakeClient,
    )
    monkeypatch.setattr(
        service,
        "_fetch_qr_login_cookie",
        AsyncMock(return_value="UID=1; CID=2; SEID=3"),
    )

    result = await service.check_qr_login_status(token)
    assert result["authorized"] is True
    assert result["cookie"].startswith("UID=")
    assert result["status"] == "authorized"
