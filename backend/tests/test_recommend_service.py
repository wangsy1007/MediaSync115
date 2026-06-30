"""「猜你想看」推荐服务测试。"""

import pytest

from app.services.emby_service import emby_service
from app.services.llm_service import LlmService
from app.services.recommend_service import RecommendService, _extract_tmdb_id


class TestLlmParsing:
    """LLM 返回解析。"""

    def test_parse_valid_json(self) -> None:
        content = (
            '{"recommendations": [{"title": "盗梦空间", "year": "2010", '
            '"media_type": "movie", "reason": "烧脑神作"}]}'
        )
        result = LlmService._parse_recommendations(content)
        assert len(result) == 1
        assert result[0]["title"] == "盗梦空间"
        assert result[0]["media_type"] == "movie"
        assert result[0]["year"] == "2010"

    def test_parse_with_extra_text(self) -> None:
        content = '好的，以下是推荐：{"recommendations": [{"title": "星际穿越", "media_type": "movie", "reason": "x"}]} 完成'
        result = LlmService._parse_recommendations(content)
        assert len(result) == 1
        assert result[0]["title"] == "星际穿越"

    def test_parse_invalid_returns_empty(self) -> None:
        assert LlmService._parse_recommendations("not json at all") == []
        assert LlmService._parse_recommendations("") == []

    def test_parse_drops_invalid_media_type(self) -> None:
        content = '{"recommendations": [{"title": "A", "media_type": "person"}, {"title": "B"}]}'
        result = LlmService._parse_recommendations(content)
        assert len(result) == 2
        assert result[0]["media_type"] == "movie"  # 非法类型回退为 movie
        assert result[1]["media_type"] == "movie"

    def test_parse_drops_empty_title(self) -> None:
        content = '{"recommendations": [{"title": "", "media_type": "movie"}, {"title": "B"}]}'
        result = LlmService._parse_recommendations(content)
        assert len(result) == 1
        assert result[0]["title"] == "B"


class TestExtractTmdbId:
    """Emby 条目 TMDB id 提取。"""

    def test_extract_from_provider_ids(self) -> None:
        assert _extract_tmdb_id({"ProviderIds": {"Tmdb": "12345"}}) == 12345
        assert _extract_tmdb_id({"ProviderIds": {"TMDB": "67890"}}) == 67890

    def test_extract_missing(self) -> None:
        assert _extract_tmdb_id({"ProviderIds": {"Imdb": "tt123"}}) is None
        assert _extract_tmdb_id({}) is None
        assert _extract_tmdb_id({"ProviderIds": "not-a-dict"}) is None

    def test_extract_non_numeric(self) -> None:
        assert _extract_tmdb_id({"ProviderIds": {"Tmdb": "abc"}}) is None


class TestBuildProfile:
    """画像聚合逻辑（mock Emby 用户行为数据）。"""

    @pytest.mark.asyncio
    async def test_build_profile_aggregates(self, monkeypatch) -> None:
        async def fake_pick_user_id():
            return "user-1"

        async def fake_played(user_id, limit=50):
            return [
                {"Name": "盗梦空间", "ProductionYear": 2010, "Genres": ["科幻", "悬疑"],
                 "ProviderIds": {"Tmdb": "123"}, "People": [{"Name": "诺兰", "Type": "Director"}],
                 "PlayedPercentage": 95.0},
                {"Name": "星际穿越", "ProductionYear": 2014, "Genres": ["科幻", "冒险"],
                 "ProviderIds": {"Tmdb": "124"}, "PlayedPercentage": 90.0},
            ]

        async def fake_resume(user_id, limit=20):
            return [{"Name": "沙丘", "ProductionYear": 2021, "Genres": ["科幻"],
                     "PlaybackPositionTicks": 500, "RunTimeTicks": 1000}]  # 50% 进度

        async def fake_favorites(user_id, limit=30):
            return [{"Name": "银翼杀手", "ProductionYear": 2017, "Genres": ["科幻", "剧情"]}]

        async def fake_latest(user_id, limit=20):
            return [{"Name": "奥本海默", "Genres": ["传记"]}]

        async def fake_recent_movies(limit=30):
            return []

        async def fake_recent_series(limit=30):
            return []

        monkeypatch.setattr(emby_service, "pick_user_id", fake_pick_user_id)
        monkeypatch.setattr(emby_service, "get_user_played", fake_played)
        monkeypatch.setattr(emby_service, "get_user_resume", fake_resume)
        monkeypatch.setattr(emby_service, "get_user_favorites", fake_favorites)
        monkeypatch.setattr(emby_service, "get_user_latest", fake_latest)
        monkeypatch.setattr(emby_service, "list_recent_movies", fake_recent_movies)
        monkeypatch.setattr(emby_service, "list_recent_series", fake_recent_series)

        service = RecommendService()
        profile = await service.build_profile()

        assert profile["user_id"] == "user-1"
        titles = {p["title"] for p in profile["recent_played"]}
        assert "盗梦空间" in titles and "星际穿越" in titles
        # 已看条目现在包含 completion
        assert profile["recent_played"][0].get("completion") is not None
        assert "银翼杀手" in {p["title"] for p in profile["favorites"]}
        assert "沙丘" in {p["title"] for p in profile["in_progress"]}
        # 沙丘进度 50%
        assert profile["in_progress"][0].get("completion") == 50.0
        # 科幻出现多次，应排第一
        assert profile["top_genres"][0] == "科幻"
        assert "诺兰" in profile["top_people"]
        assert profile["year_range"] == "2010-2014"
        # 新增权重字段
        assert isinstance(profile.get("high_interest_genres"), list)
        assert isinstance(profile.get("high_interest_directors"), list)
        assert isinstance(profile.get("low_interest_signals"), list)

    @pytest.mark.asyncio
    async def test_build_profile_with_library_weight(self, monkeypatch) -> None:
        """入库权重：最近入库的科幻/悬疑片 + 诺兰导演应有高权重。"""
        async def fake_pick():
            return "user-1"
        async def fake_played(uid, limit):
            return []
        async def fake_resume(uid, limit):
            return []
        async def fake_fav(uid, limit):
            return []
        async def fake_latest(uid, limit):
            return []
        async def fake_recent_movies(limit):
            return [
                {"Name": "信条", "ProductionYear": 2020, "Genres": ["科幻", "动作"],
                 "People": [{"Name": "诺兰", "Type": "Director"}]},
                {"Name": "沙丘2", "ProductionYear": 2024, "Genres": ["科幻", "冒险"],
                 "People": [{"Name": "维伦纽瓦", "Type": "Director"}]},
            ]
        async def fake_recent_series(limit):
            return [
                {"Name": "基地", "ProductionYear": 2021, "Genres": ["科幻", "剧情"]},
            ]

        for attr, fn in [("pick_user_id", fake_pick), ("get_user_played", fake_played),
                          ("get_user_resume", fake_resume), ("get_user_favorites", fake_fav),
                          ("get_user_latest", fake_latest), ("list_recent_movies", fake_recent_movies),
                          ("list_recent_series", fake_recent_series)]:
            monkeypatch.setattr(emby_service, attr, fn)

        profile = await RecommendService().build_profile()
        assert len(profile["high_interest_genres"]) >= 1
        assert "科幻" in str(profile["high_interest_genres"])
        assert profile["top_genres"][0] == "科幻"  # 3*3=9 次 > 其它
        assert any("诺兰" in d for d in profile["high_interest_directors"])

    @pytest.mark.asyncio
    async def test_build_profile_no_user(self, monkeypatch) -> None:
        async def fake_pick_user_id():
            return None

        monkeypatch.setattr(emby_service, "pick_user_id", fake_pick_user_id)
        service = RecommendService()
        profile = await service.build_profile()
        assert profile["user_id"] is None
        assert profile["recent_played"] == []
        assert "未配置" in profile["summary"]


class TestSummarizeProfile:
    def test_summarize_with_data(self) -> None:
        summary = RecommendService._summarize_profile(
            {"top_genres": ["科幻", "悬疑"], "recent_played": [{"title": "a"}], "top_people": ["诺兰"]}
        )
        assert "科幻" in summary and "诺兰" in summary

    def test_summarize_empty(self) -> None:
        assert "画像数据较少" in RecommendService._summarize_profile({})
