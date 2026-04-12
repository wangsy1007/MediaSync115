import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.utils import proxy as proxy_module
from app.utils.proxy import ProxyManager, proxy_manager


def _restore_proxy_config(config: dict[str, str | None]) -> None:
    proxy_manager.update_proxy(
        http_proxy=config.get("http_proxy") or "",
        https_proxy=config.get("https_proxy") or "",
        all_proxy=config.get("all_proxy") or "",
        socks_proxy=config.get("socks_proxy") or "",
    )


def test_proxy_manager_uses_socks_fallback_for_httpx_clients(monkeypatch) -> None:
    manager = ProxyManager()
    original_config = dict(proxy_manager.get_current_config())
    manager.update_proxy(
        http_proxy="",
        https_proxy="",
        all_proxy="",
        socks_proxy="socks5://127.0.0.1:7890",
    )

    class DummyAsyncTransport:
        def __init__(self, proxy: str) -> None:
            self.proxy = proxy

    class DummySyncTransport:
        def __init__(self, proxy: str) -> None:
            self.proxy = proxy

    class DummyAsyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class DummySyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_httpx = SimpleNamespace(
        AsyncHTTPTransport=DummyAsyncTransport,
        HTTPTransport=DummySyncTransport,
        AsyncClient=DummyAsyncClient,
        Client=DummySyncClient,
    )
    monkeypatch.setattr(proxy_module, "_get_httpx", lambda: fake_httpx)

    try:
        async_client = manager.create_httpx_client(timeout=5.0)
        sync_client = manager.create_sync_httpx_client(timeout=5.0)

        async_mounts = async_client.kwargs["mounts"]
        sync_mounts = sync_client.kwargs["mounts"]
        assert async_mounts["http://"].proxy == "socks5://127.0.0.1:7890"
        assert async_mounts["https://"].proxy == "socks5://127.0.0.1:7890"
        assert sync_mounts["http://"].proxy == "socks5://127.0.0.1:7890"
        assert sync_mounts["https://"].proxy == "socks5://127.0.0.1:7890"
    finally:
        manager.update_proxy(
            http_proxy=original_config.get("http_proxy") or "",
            https_proxy=original_config.get("https_proxy") or "",
            all_proxy=original_config.get("all_proxy") or "",
            socks_proxy=original_config.get("socks_proxy") or "",
        )


def test_health_all_uses_configured_proxy_for_fixed_targets(
    client: TestClient, monkeypatch
) -> None:
    settings_api = importlib.import_module("app.api.settings")
    original_config = dict(proxy_manager.get_current_config())
    proxy_manager.update_proxy(
        http_proxy="",
        https_proxy="",
        all_proxy="",
        socks_proxy="socks5://127.0.0.1:7890",
    )

    monkeypatch.setattr(
        settings_api.runtime_settings_service,
        "get_tmdb_base_url",
        lambda: "https://api.themoviedb.org/3",
    )

    calls: list[dict[str, object]] = []
    status_map = {
        "https://hdhive.com/": 302,
        "https://api.themoviedb.org/3": 204,
        "https://api.telegram.org": 200,
    }

    class DummyResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    class DummyAsyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> DummyResponse:
            calls.append(
                {
                    "url": url,
                    "proxy": self.kwargs.get("proxy"),
                    "timeout": self.kwargs.get("timeout"),
                    "follow_redirects": self.kwargs.get("follow_redirects"),
                }
            )
            return DummyResponse(status_map[url])

    monkeypatch.setattr(settings_api.httpx, "AsyncClient", DummyAsyncClient)

    try:
        login_response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "password"},
        )
        assert login_response.status_code == 200
        response = client.get("/api/settings/health/all")

        assert response.status_code == 200
        payload = response.json()
        assert payload["valid_count"] == 3
        assert payload["total_count"] == 3
        assert payload["all_valid"] is True
        assert payload["services"]["hdhive"] == {
            "status": "ok",
            "valid": True,
            "message": "连接正常 (HTTP 302)",
            "target": "https://hdhive.com/",
            "applied_proxy": "socks5://127.0.0.1:7890",
            "proxy_scheme": "socks5",
            "status_code": 302,
        }
        assert payload["services"]["tmdb"] == {
            "status": "ok",
            "valid": True,
            "message": "连接正常 (HTTP 204)",
            "target": "https://api.themoviedb.org/3",
            "applied_proxy": "socks5://127.0.0.1:7890",
            "proxy_scheme": "socks5",
            "status_code": 204,
        }
        assert payload["services"]["tg"] == {
            "status": "ok",
            "valid": True,
            "message": "连接正常 (HTTP 200)",
            "target": "https://api.telegram.org",
            "applied_proxy": "socks5://127.0.0.1:7890",
            "proxy_scheme": "socks5",
            "status_code": 200,
        }
        assert len(calls) == 3
        assert {call["proxy"] for call in calls} == {"socks5://127.0.0.1:7890"}
        assert {call["follow_redirects"] for call in calls} == {False}
    finally:
        _restore_proxy_config(original_config)


def test_health_all_reports_missing_proxy_without_direct_connect(
    client: TestClient, monkeypatch
) -> None:
    settings_api = importlib.import_module("app.api.settings")
    original_config = dict(proxy_manager.get_current_config())
    proxy_manager.update_proxy(
        http_proxy="",
        https_proxy="",
        all_proxy="",
        socks_proxy="",
    )

    monkeypatch.setattr(
        settings_api.runtime_settings_service,
        "get_tmdb_base_url",
        lambda: "https://api.themoviedb.org/3",
    )

    class DummyAsyncClient:
        def __init__(self, **kwargs) -> None:
            raise AssertionError(
                "AsyncClient should not be created when no proxy is matched"
            )

    monkeypatch.setattr(settings_api.httpx, "AsyncClient", DummyAsyncClient)

    try:
        login_response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "password"},
        )
        assert login_response.status_code == 200
        response = client.get("/api/settings/health/all")

        assert response.status_code == 200
        payload = response.json()
        assert payload["valid_count"] == 0
        assert payload["total_count"] == 3
        assert payload["all_valid"] is False
        for service_key in ("hdhive", "tmdb", "tg"):
            assert payload["services"][service_key]["status"] == "error"
            assert payload["services"][service_key]["valid"] is False
            assert payload["services"][service_key]["message"] == "未命中代理"
            assert payload["services"][service_key]["applied_proxy"] == ""
            assert payload["services"][service_key]["proxy_scheme"] == ""
            assert payload["services"][service_key]["status_code"] is None
    finally:
        _restore_proxy_config(original_config)


def test_tg_transport_parser_supports_authenticated_http_proxy() -> None:
    tg_module = importlib.import_module("app.services.tg_service")
    parsed = tg_module.TgService._build_proxy("http://user:pass@127.0.0.1:7890")
    assert parsed == ("http", "127.0.0.1", 7890, True, "user", "pass")


def test_tg_client_falls_back_to_global_proxy(monkeypatch) -> None:
    tg_module = importlib.import_module("app.services.tg_service")
    original_config = dict(proxy_manager.get_current_config())
    proxy_manager.update_proxy(
        http_proxy="",
        https_proxy="",
        all_proxy="",
        socks_proxy="socks5://127.0.0.1:1080",
    )

    captured: dict[str, object] = {}

    class DummyStringSession:
        def __init__(self, value: str) -> None:
            self.value = value

    class DummyTelegramClient:
        def __init__(self, session, **kwargs) -> None:
            captured["session"] = getattr(session, "value", session)
            captured.update(kwargs)

    monkeypatch.setattr(tg_module, "TELETHON_AVAILABLE", True)
    monkeypatch.setattr(tg_module, "StringSession", DummyStringSession)
    monkeypatch.setattr(tg_module, "TelegramClient", DummyTelegramClient)

    try:
        service = tg_module.TgService()
        service.set_config(api_id="10001", api_hash="hash-value")
        service._build_client("session-value")
    finally:
        _restore_proxy_config(original_config)

    assert captured["session"] == "session-value"
    assert captured["proxy"] == ("socks5", "127.0.0.1", 1080)
