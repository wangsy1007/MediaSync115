"""探索榜单 section source 自动推断测试"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import search as search_api


class TestResolveExploreSectionSource:
    def test_tmdb_key(self) -> None:
        assert search_api._resolve_explore_section_source("trending_all_week") == "tmdb"

    def test_douban_key(self) -> None:
        assert search_api._resolve_explore_section_source("movie_hot") == "douban"

    def test_maoyan_key(self) -> None:
        assert search_api._resolve_explore_section_source("box_office") == "maoyan"

    def test_unknown_key(self) -> None:
        assert search_api._resolve_explore_section_source("unknown_section") is None


@pytest.mark.asyncio
async def test_get_explore_section_auto_corrects_wrong_source() -> None:
    payload = {
        "key": "trending_all_week",
        "title": "TMDB 趋势总榜（周）",
        "tag": "Trending",
        "source_url": "https://example.com",
        "fetched_at": "2026-07-14T00:00:00+08:00",
        "total": 1,
        "start": 0,
        "count": 1,
        "items": [
            {
                "id": 1,
                "tmdb_id": 1,
                "media_type": "movie",
                "title": "Test Movie",
            }
        ],
    }

    with patch(
        "app.api.search.fetch_tmdb_section",
        new=AsyncMock(return_value=payload),
    ), patch(
        "app.api.search._build_library_status_maps",
        new=AsyncMock(return_value=({}, {})),
    ):
        result = await search_api.get_explore_section(
            section_key="trending_all_week",
            source="douban",
            limit=30,
            start=0,
            refresh=False,
        )

    assert result["source"] == "tmdb"
    assert result["section"]["key"] == "trending_all_week"
    assert len(result["section"]["items"]) == 1


@pytest.mark.asyncio
async def test_get_explore_section_unknown_key_returns_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await search_api.get_explore_section(
            section_key="not_a_real_section",
            source="douban",
            limit=30,
            start=0,
            refresh=False,
        )
    assert exc_info.value.status_code == 404
