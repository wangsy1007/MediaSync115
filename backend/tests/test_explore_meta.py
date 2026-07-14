"""探索榜单元数据接口测试"""


class TestExploreMeta:
    """探索 meta 接口"""

    def test_tmdb_meta_reports_configured_flag(self, client, monkeypatch) -> None:
        """TMDB 来源应返回 tmdb_configured 字段"""
        monkeypatch.setenv("TMDB_API_KEY", "test-api-key")
        from app.core.config import settings

        settings.TMDB_API_KEY = "test-api-key"

        response = client.get("/api/search/explore/meta", params={"source": "tmdb"})
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("tmdb_configured") is True
        assert len(payload.get("sections") or []) > 0

    def test_tmdb_meta_reports_not_configured(self, client, monkeypatch) -> None:
        """未配置 TMDB Key 时应返回 tmdb_configured=false"""
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        from app.core.config import settings

        settings.TMDB_API_KEY = None

        response = client.get("/api/search/explore/meta", params={"source": "tmdb"})
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("tmdb_configured") is False

    def test_maoyan_meta_returns_sections(self, client) -> None:
        """猫眼来源应返回三个探索分区"""
        response = client.get("/api/search/explore/meta", params={"source": "maoyan"})
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("source") == "maoyan"
        keys = {row.get("key") for row in (payload.get("sections") or [])}
        assert keys == {"movie_on_show", "movie_coming", "box_office"}
