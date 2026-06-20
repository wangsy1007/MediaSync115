import asyncio
from unittest.mock import AsyncMock

from app.models.models import MediaType
from app.services.subscription_service import SubscriptionService, SubscriptionSnapshot


class TestFetchResourcesWaterfall:
    def test_fetch_resources_stops_after_first_source_hit(self) -> None:
        service = SubscriptionService()
        sub = SubscriptionSnapshot(
            id=0,
            tmdb_id=123,
            douban_id="",
            title="测试电影",
            media_type=MediaType.MOVIE,
            year="2024",
            auto_download=False,
            tv_scope="all",
            tv_season_number=None,
            tv_episode_start=None,
            tv_episode_end=None,
            tv_follow_mode="missing",
            tv_include_specials=False,
            has_successful_transfer=False,
        )

        async def fake_pansou(current_sub: SubscriptionSnapshot):
            return (
                [
                    {
                        "source_service": "pansou",
                        "share_link": "https://115.com/s/pansou1",
                        "resource_name": "Pansou 资源",
                    }
                ],
                [],
            )

        async def fake_hdhive(current_sub: SubscriptionSnapshot):
            raise AssertionError("不应在首个来源命中后继续请求 HDHive")

        service._fetch_from_pansou = AsyncMock(side_effect=fake_pansou)  # type: ignore[method-assign]
        service._fetch_from_hdhive = AsyncMock(side_effect=fake_hdhive)  # type: ignore[method-assign]
        service._fetch_from_tg = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        service._fetch_offline_magnets = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        service._prepare_hdhive_locked_resources = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda resources, *_args, **_kwargs: resources
        )

        from app.services import subscription_service as subscription_service_module

        original_log = (
            subscription_service_module.operation_log_service.log_background_event
        )
        subscription_service_module.operation_log_service.log_background_event = AsyncMock()  # type: ignore[method-assign]
        try:
            resources, _traces, meta = asyncio.run(
                service._fetch_resources(
                    channel="all",
                    sub=sub,
                    source_order=["pansou", "hdhive", "tg"],
                )
            )
        finally:
            subscription_service_module.operation_log_service.log_background_event = original_log  # type: ignore[method-assign]

        assert len(resources) == 1
        assert resources[0]["share_link"] == "https://115.com/s/pansou1"
        assert meta["source_order"] == ["pansou", "hdhive", "tg"]
        assert meta["attempts"] == [
            {"source": "pansou", "status": "success", "count": 1}
        ]
        service._fetch_from_hdhive.assert_not_called()

    def test_fetch_resources_falls_back_when_first_source_exhausted(self) -> None:
        service = SubscriptionService()
        sub = SubscriptionSnapshot(
            id=0,
            tmdb_id=456,
            douban_id="",
            title="测试电影2",
            media_type=MediaType.MOVIE,
            year="2024",
            auto_download=False,
            tv_scope="all",
            tv_season_number=None,
            tv_episode_start=None,
            tv_episode_end=None,
            tv_follow_mode="missing",
            tv_include_specials=False,
            has_successful_transfer=False,
        )

        async def fake_pansou(current_sub: SubscriptionSnapshot):
            return (
                [
                    {
                        "source_service": "pansou",
                        "share_link": "https://115.com/s/used",
                        "resource_name": "已尝试",
                    }
                ],
                [],
            )

        async def fake_hdhive(current_sub: SubscriptionSnapshot):
            return (
                [
                    {
                        "source_service": "hdhive",
                        "share_link": "https://115.com/s/new",
                        "resource_name": "HDHive 资源",
                    }
                ],
                [],
            )

        service._fetch_from_pansou = AsyncMock(side_effect=fake_pansou)  # type: ignore[method-assign]
        service._fetch_from_hdhive = AsyncMock(side_effect=fake_hdhive)  # type: ignore[method-assign]
        service._fetch_from_tg = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        service._fetch_offline_magnets = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        service._prepare_hdhive_locked_resources = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda resources, *_args, **_kwargs: resources
        )

        from app.services import subscription_service as subscription_service_module

        original_log = (
            subscription_service_module.operation_log_service.log_background_event
        )
        subscription_service_module.operation_log_service.log_background_event = AsyncMock()  # type: ignore[method-assign]
        try:
            resources, _traces, meta = asyncio.run(
                service._fetch_resources(
                    channel="all",
                    sub=sub,
                    source_order=["pansou", "hdhive"],
                    exclude_urls={"https://115.com/s/used"},
                )
            )
        finally:
            subscription_service_module.operation_log_service.log_background_event = original_log  # type: ignore[method-assign]

        assert len(resources) == 1
        assert resources[0]["share_link"] == "https://115.com/s/new"
        assert [item["source"] for item in meta["attempts"]] == ["pansou", "hdhive"]
        assert meta["attempts"][0]["status"] == "empty"
        assert meta["attempts"][1]["status"] == "success"
