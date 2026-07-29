import asyncio

import httpx
import pytest

from app.core.config import settings
from app.services import tmdb_explore_service, tmdb_service as tmdb_service_module


def _source() -> dict:
    return next(
        row
        for row in tmdb_explore_service.TMDB_SECTION_SOURCES
        if row["key"] == "trending_tv_week"
    )


@pytest.mark.asyncio
async def test_full_tmdb_section_reuses_shared_client_sequentially(monkeypatch):
    calls: list[int] = []
    active = 0
    max_active = 0

    async def fake_get_list_page(path, *, page=1, extra_params=None):
        nonlocal active, max_active
        assert path == "/trending/tv/week"
        calls.append(page)
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        start_id = (page - 1) * 20
        return {
            "total_results": 100,
            "results": [
                {
                    "id": start_id + index + 1,
                    "name": f"TV {start_id + index + 1}",
                    "first_air_date": "2026-01-01",
                }
                for index in range(20)
            ],
        }

    monkeypatch.setattr(
        tmdb_explore_service.tmdb_service,
        "get_list_page",
        fake_get_list_page,
    )
    tmdb_explore_service._tmdb_sections_cache.clear()

    payload = await tmdb_explore_service.fetch_tmdb_section(
        _source(),
        limit=30,
        refresh=True,
    )

    assert calls == [1, 2]
    assert max_active == 1
    assert len(payload["items"]) == 30
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][-1]["rank"] == 30


@pytest.mark.asyncio
async def test_tmdb_transport_error_retries_before_success(monkeypatch):
    attempts = 0

    class FakeClient:
        async def get(self, url, params):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise httpx.ConnectError("")
            return httpx.Response(
                200,
                json={"results": [{"id": 1}]},
                request=httpx.Request("GET", url),
            )

    async def fake_get_client(*, verify=True):
        return FakeClient()

    monkeypatch.setattr(
        tmdb_service_module,
        "_get_tmdb_http_client",
        fake_get_client,
    )

    payload = await tmdb_service_module.tmdb_service._request_json(
        "https://api.themoviedb.org/3/trending/tv/week",
        {"api_key": "test"},
    )

    assert attempts == 3
    assert payload["results"][0]["id"] == 1


@pytest.mark.asyncio
async def test_tmdb_section_connect_error_has_readable_message(monkeypatch):
    async def fail_get_list_page(path, *, page=1, extra_params=None):
        raise httpx.ConnectError("")

    monkeypatch.setattr(
        tmdb_explore_service.tmdb_service,
        "get_list_page",
        fail_get_list_page,
    )
    monkeypatch.setattr(settings, "TMDB_API_KEY", "test-key")
    tmdb_explore_service._tmdb_sections_cache.clear()

    with pytest.raises(RuntimeError, match="ConnectError"):
        await tmdb_explore_service.fetch_tmdb_section(
            _source(),
            limit=30,
            refresh=True,
        )
