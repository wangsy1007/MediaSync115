import httpx
import pytest

from app.api import settings as settings_api


@pytest.mark.asyncio
async def test_tmdb_health_probe_reuses_real_service_client(monkeypatch):
    calls = 0

    monkeypatch.setattr(
        settings_api.runtime_settings_service,
        "get_tmdb_api_key",
        lambda: "test-api-key",
    )
    monkeypatch.setattr(
        settings_api,
        "_resolve_health_probe_route",
        lambda scheme: {
            "route_mode": "system",
            "applied_proxy": "",
            "proxy_scheme": "system",
            "route_hint": "系统网络（未配置应用代理）",
            "require_proxy": "0",
        },
    )

    async def fake_check_connection():
        nonlocal calls
        calls += 1
        return {"images_configured": True, "change_keys_count": 54}

    monkeypatch.setattr(
        settings_api.tmdb_service,
        "check_connection",
        fake_check_connection,
    )

    result = await settings_api._probe_tmdb_health(
        "https://api.themoviedb.org/3"
    )

    assert calls == 1
    assert result["status"] == "ok"
    assert result["valid"] is True
    assert result["status_code"] == 200
    assert result["proxy_scheme"] == "system"
    assert "TMDB API 连接正常" in result["message"]


@pytest.mark.asyncio
async def test_tmdb_health_probe_keeps_empty_transport_error_readable(monkeypatch):
    monkeypatch.setattr(
        settings_api.runtime_settings_service,
        "get_tmdb_api_key",
        lambda: "test-api-key",
    )
    monkeypatch.setattr(
        settings_api,
        "_resolve_health_probe_route",
        lambda scheme: {
            "route_mode": "system",
            "applied_proxy": "",
            "proxy_scheme": "system",
            "route_hint": "系统网络（未配置应用代理）",
            "require_proxy": "0",
        },
    )

    async def fail_check_connection():
        raise httpx.ConnectError("")

    monkeypatch.setattr(
        settings_api.tmdb_service,
        "check_connection",
        fail_check_connection,
    )
    monkeypatch.setattr(settings_api, "_TMDB_HEALTH_RETRY_BASE_SECONDS", 0)

    result = await settings_api._probe_tmdb_health(
        "https://api.themoviedb.org/3"
    )

    assert result["status"] == "error"
    assert result["valid"] is False
    assert "ConnectError" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadError,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    ],
)
async def test_tmdb_health_probe_retries_short_transport_error_burst(
    monkeypatch,
    transport_error,
):
    attempts = 0

    monkeypatch.setattr(
        settings_api.runtime_settings_service,
        "get_tmdb_api_key",
        lambda: "test-api-key",
    )
    monkeypatch.setattr(
        settings_api,
        "_resolve_health_probe_route",
        lambda scheme: {
            "route_mode": "system",
            "applied_proxy": "",
            "proxy_scheme": "system",
            "route_hint": "系统网络（未配置应用代理）",
            "require_proxy": "0",
        },
    )
    monkeypatch.setattr(settings_api, "_TMDB_HEALTH_RETRY_BASE_SECONDS", 0)

    async def flaky_check_connection():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise transport_error("")
        return {"images_configured": True, "change_keys_count": 54}

    monkeypatch.setattr(
        settings_api.tmdb_service,
        "check_connection",
        flaky_check_connection,
    )

    result = await settings_api._probe_tmdb_health(
        "https://api.themoviedb.org/3"
    )

    assert attempts == 3
    assert result["status"] == "ok"
    assert result["valid"] is True
