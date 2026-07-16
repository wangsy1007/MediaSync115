import asyncio
from unittest.mock import AsyncMock

from app.services.juying_web_service import JuyingWebService
from app.services.runtime_settings_service import RuntimeSettingsService


class TestJuyingWebService:
    def test_runtime_settings_encrypts_password(self, tmp_path) -> None:
        settings_service = RuntimeSettingsService()
        settings_service._file_path = tmp_path / "runtime_settings.json"
        settings_service.set_juying_password("plain-password")

        persisted = settings_service._file_path.read_text(encoding="utf-8")
        assert "plain-password" not in persisted
        assert settings_service.get_juying_password() == "plain-password"
        public = settings_service.get_all()
        assert public["juying_password_set"] is True
        assert "juying_password" not in public

    def test_search_normalizes_115_and_magnet_resources(self) -> None:
        service = JuyingWebService()
        service.configure(
            base_url="https://www.jying.top",
            username="user@example.com",
            password="secret",
            enabled=True,
        )
        service._find_movie = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "id": 379,
                "title": "流浪地球",
                "release_year": 2019,
                "movie_type": "movie",
                "tmdb_id": 535167,
            }
        )
        service._load_movie_resources = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "id": 1,
                    "resource_type": "115",
                    "title": "流浪地球 2160P",
                    "file_size": "30GB",
                    "link_exposed": True,
                    "access_ticket": "ticket-1",
                },
                {
                    "id": 2,
                    "resource_type": "MagnetLink",
                    "description": "流浪地球 1080P",
                    "link_exposed": True,
                    "access_ticket": "ticket-2",
                },
                {"id": 3, "resource_type": "baidu"},
            ]
        )

        result = asyncio.run(
            service.search_resources(
                title="流浪地球",
                year="2019",
                tmdb_id=535167,
            )
        )

        assert len(result["pan115"]) == 1
        assert result["pan115"][0]["source_service"] == "juying"
        assert result["pan115"][0]["share_link"] == ""
        assert len(result["magnets"]) == 1
        assert result["magnets"][0]["magnet"] == ""

        asyncio.run(service.close())

    def test_resolve_resource_validates_and_maps_115_target(self) -> None:
        service = JuyingWebService()
        service.configure(
            base_url="https://www.jying.top",
            username="user@example.com",
            password="secret",
            enabled=True,
        )
        service._resource_cache["1"] = type("Entry", (), {
            "expires_at": float("inf"),
            "value": {
                "id": 1,
                "resource_type": "115",
                "link_exposed": True,
                "access_ticket": "ticket-1",
            },
        })()
        service._request = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "target": "https://115cdn.com/s/example",
                "access_code": "abcd",
                "access_mode": "open",
                "expires_in": 120,
            }
        )

        result = asyncio.run(service.resolve_resource("juying-1"))

        assert result["resource_type"] == "115"
        assert result["share_link"] == "https://115cdn.com/s/example"
        assert result["access_code"] == "abcd"
        asyncio.run(service.close())

    def test_find_movie_retries_original_title_without_year(self) -> None:
        service = JuyingWebService()
        service.configure(
            base_url="https://www.jying.top",
            username="user@example.com",
            password="secret",
            enabled=True,
        )
        service._request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                {"results": []},
                {"results": []},
                {"results": []},
                {
                    "results": [
                        {
                            "id": 46882,
                            "title": "The Furious",
                            "release_year": 2025,
                            "movie_type": "movie",
                            "tmdb_id": "1280738",
                        }
                    ]
                },
            ]
        )

        result = asyncio.run(
            service._find_movie(
                title="火遮眼",
                alternative_titles=["The Furious"],
                year="2026",
                media_type="movie",
                tmdb_id=1280738,
                season=None,
            )
        )

        assert result is not None
        assert result["id"] == 46882
        calls = service._request.await_args_list
        assert calls[-1].kwargs["params"]["q"] == "The Furious"
        assert "year" not in calls[-1].kwargs["params"]
        asyncio.run(service.close())
