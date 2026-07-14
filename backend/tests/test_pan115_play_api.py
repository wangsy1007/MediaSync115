"""qmediasync 风格 /api/115/url 与 /api/proxy-115 单测。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.pan115_play as pan115_play_module
from app.api.pan115_play import router


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


class TestPan115PlayApi:
    def test_url_redirects_to_cdn(self, client: TestClient, monkeypatch) -> None:
        async def fake_fetch(pick_code: str, *, user_agent: str = "", force_proxy: bool = False):
            assert pick_code == "pc123"
            assert "SenPlayer" in user_agent
            return {"download_url": "https://cdnfhnfile.115cdn.net/a.mkv"}

        monkeypatch.setattr(
            pan115_play_module.runtime_settings_service,
            "get_strm_redirect_mode",
            lambda: "redirect",
        )
        monkeypatch.setattr(
            pan115_play_module.strm_service,
            "_fetch_pick_code_download_info",
            fake_fetch,
        )
        resp = client.get(
            "/api/115/url/video.mkv",
            params={"pickcode": "pc123", "force": 1},
            headers={"User-Agent": "SenPlayer/1.0"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://cdnfhnfile.115cdn.net/a.mkv"

    def test_url_local_proxy_when_mode_proxy(self, client: TestClient, monkeypatch) -> None:
        async def fake_fetch(pick_code: str, *, user_agent: str = "", force_proxy: bool = False):
            assert user_agent == pan115_play_module.PROXY_115_DEFAULT_UA
            return {"download_url": "https://cdnfhnfile.115cdn.net/a.iso"}

        monkeypatch.setattr(
            pan115_play_module.runtime_settings_service,
            "get_strm_redirect_mode",
            lambda: "proxy",
        )
        monkeypatch.setattr(
            pan115_play_module.strm_service,
            "_fetch_pick_code_download_info",
            fake_fetch,
        )
        resp = client.get(
            "/api/115/url/video.iso",
            params={"pickcode": "pc123", "force": 0},
            headers={"User-Agent": "HosPlayer/1.0"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/api/proxy-115?url=")

    def test_proxy_115_rejects_non_cdn(self, client: TestClient) -> None:
        resp = client.get(
            "/api/proxy-115",
            params={"url": "https://evil.example/x"},
            follow_redirects=False,
        )
        assert resp.status_code == 403
