import asyncio
from unittest.mock import AsyncMock

from app.models.models import MediaType
from app.services.subscription_service import SubscriptionService, SubscriptionSnapshot


class TestHDHivePrefilterBeforeUnlock:
    def test_prepare_hdhive_receives_prefiltered_candidates(self) -> None:
        service = SubscriptionService()
        sub = SubscriptionSnapshot(
            id=0,
            tmdb_id=535167,
            douban_id="535167",
            title="流浪地球",
            media_type=MediaType.MOVIE,
            year="2019",
            auto_download=False,
            tv_scope="all",
            tv_season_number=None,
            tv_episode_start=None,
            tv_episode_end=None,
            tv_follow_mode="missing",
            tv_include_specials=False,
            has_successful_transfer=False,
        )

        raw_resources = [
            {
                "source_service": "hdhive",
                "slug": "irrelevant",
                "hdhive_locked": True,
                "unlock_points": 0,
                "resource_name": "其他电影资源",
            },
            {
                "source_service": "hdhive",
                "slug": "target",
                "hdhive_locked": True,
                "unlock_points": 0,
                "resource_name": "流浪地球 2019 4K",
            },
        ]
        prepared_resources = [
            {
                "source_service": "hdhive",
                "slug": "target",
                "share_link": "https://115.com/s/target?password=abcd",
                "resource_name": "流浪地球 2019 4K",
            }
        ]

        service._fetch_from_hdhive = AsyncMock(return_value=(raw_resources, []))  # type: ignore[method-assign]
        service._fetch_offline_magnets = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        service._prefilter_resources_for_unlock = AsyncMock(  # type: ignore[method-assign]
            return_value=[raw_resources[1]]
        )
        service._prepare_hdhive_locked_resources = AsyncMock(  # type: ignore[method-assign]
            return_value=prepared_resources
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
                    source_order=["hdhive"],
                )
            )
        finally:
            subscription_service_module.operation_log_service.log_background_event = original_log  # type: ignore[method-assign]

        service._prefilter_resources_for_unlock.assert_awaited_once()
        prepare_args = service._prepare_hdhive_locked_resources.await_args
        assert prepare_args is not None
        assert prepare_args.args[0] == [raw_resources[1]]
        assert len(resources) == 1
        assert resources[0]["share_link"] == "https://115.com/s/target?password=abcd"
        assert meta["attempts"][0]["status"] == "success"

    def test_finalize_savable_resources_clears_unsavable_hits(self) -> None:
        service = SubscriptionService()
        sub = SubscriptionSnapshot(
            id=0,
            tmdb_id=1,
            douban_id="",
            title="测试",
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

        locked_resources = [
            {
                "source_service": "hdhive",
                "slug": "locked-a",
                "hdhive_locked": True,
                "unlock_points": 0,
                "resource_name": "锁定资源 A",
            }
        ]

        service._fetch_from_hdhive = AsyncMock(return_value=(locked_resources, []))  # type: ignore[method-assign]
        service._fetch_offline_magnets = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
        service._prefilter_resources_for_unlock = AsyncMock(return_value=locked_resources)  # type: ignore[method-assign]
        service._prepare_hdhive_locked_resources = AsyncMock(  # type: ignore[method-assign]
            return_value=locked_resources
        )

        from app.services import subscription_service as subscription_service_module

        original_log = (
            subscription_service_module.operation_log_service.log_background_event
        )
        subscription_service_module.operation_log_service.log_background_event = AsyncMock()  # type: ignore[method-assign]
        try:
            resources, traces, meta = asyncio.run(
                service._fetch_resources(
                    channel="all",
                    sub=sub,
                    source_order=["hdhive"],
                )
            )
        finally:
            subscription_service_module.operation_log_service.log_background_event = original_log  # type: ignore[method-assign]

        assert resources == []
        assert meta["attempts"][0]["status"] == "empty"
        assert "未获取可转存链接" in str(meta["attempts"][0].get("error") or "")
        assert any(
            trace.get("step") == "savable_resources_empty" for trace in traces
        )
