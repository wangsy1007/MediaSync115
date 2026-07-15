"""
订阅自动转存链接回退逻辑测试
"""
from unittest.mock import AsyncMock

import pytest

from app.models.models import DownloadRecord, MediaType
from app.services.subscription_service import (
    SubscriptionService,
    SubscriptionSnapshot,
    subscription_service,
)


def _movie_snapshot() -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id=1,
        tmdb_id=1,
        douban_id="",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        year="2024",
        auto_download=True,
        tv_scope="all",
        tv_season_number=None,
        tv_episode_start=None,
        tv_episode_end=None,
        tv_follow_mode="missing",
        tv_include_specials=False,
        has_successful_transfer=False,
    )


def _tv_snapshot() -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id=2,
        tmdb_id=2,
        douban_id="",
        title="Test TV",
        media_type=MediaType.TV,
        year="2024",
        auto_download=True,
        tv_scope="all",
        tv_season_number=None,
        tv_episode_start=None,
        tv_episode_end=None,
        tv_follow_mode="missing",
        tv_include_specials=False,
        has_successful_transfer=False,
    )


class TestSubscriptionLinkFallback:
    """链接失效后是否继续搜索下一条资源的判断"""

    def test_should_continue_for_movie_when_all_failed(self) -> None:
        assert subscription_service._should_continue_link_fallback(
            _movie_snapshot(),
            {"saved": 0, "failed": 1, "subscription_completed": False},
            attempted_count=1,
        )

    def test_should_stop_for_movie_when_saved(self) -> None:
        assert not subscription_service._should_continue_link_fallback(
            _movie_snapshot(),
            {"saved": 1, "failed": 0, "subscription_completed": False},
            attempted_count=1,
        )

    def test_should_continue_for_tv_with_remaining_missing(self) -> None:
        assert subscription_service._should_continue_link_fallback(
            _tv_snapshot(),
            {
                "saved": 1,
                "failed": 0,
                "subscription_completed": False,
                "remaining_missing_count": 3,
            },
            attempted_count=1,
        )

    def test_filter_resources_excluding_urls(self) -> None:
        resources = [
            {"share_link": "https://115.com/s/sw1"},
            {"share_link": "https://115.com/s/sw2"},
        ]
        filtered = SubscriptionService._filter_resources_excluding_urls(
            resources,
            {"https://115.com/s/sw1"},
        )
        assert len(filtered) == 1
        assert filtered[0]["share_link"] == "https://115.com/s/sw2"

    def test_filter_resources_excluding_source_ids(self) -> None:
        resources = [
            {"slug": "aaa111", "title": "资源 A"},
            {"slug": "bbb222", "title": "资源 B"},
        ]
        filtered = SubscriptionService._filter_resources_excluding_source_ids(
            resources,
            {"aaa111"},
        )
        assert len(filtered) == 1
        assert filtered[0]["slug"] == "bbb222"

    def test_extract_download_record_relevance_fields_includes_source_id(self) -> None:
        fields = SubscriptionService._extract_download_record_relevance_fields(
            {
                "slug": "df913ae5f38611f0a7c78e06b282dbd4",
                "matched_media_title": "肖申克的救赎",
                "hdhive_source_tmdb_id": 278,
            }
        )
        assert fields["resource_source_id"] == "df913ae5f38611f0a7c78e06b282dbd4"

    def test_extract_download_record_relevance_fields_falls_back_to_subscription(self) -> None:
        sub = _movie_snapshot()
        sub.tmdb_id = 278
        sub.title = "肖申克的救赎"
        fields = SubscriptionService._extract_download_record_relevance_fields(
            {"slug": "abc123", "title": "4K蓝光原盘"},
            sub=sub,
        )
        assert fields["source_tmdb_id"] == 278
        assert fields["matched_media_title"] == "肖申克的救赎"
        assert fields["relevance_verified"] is True

    def test_dedupe_records_by_url(self) -> None:
        records = [
            DownloadRecord(resource_url="https://115.com/s/a"),
            DownloadRecord(resource_url="https://115.com/s/a"),
            DownloadRecord(resource_url="https://115.com/s/b"),
        ]
        deduped = SubscriptionService._dedupe_records_by_url(records)
        assert len(deduped) == 2

    def test_dedupe_records_by_share_code(self) -> None:
        records = [
            DownloadRecord(resource_url="https://115.com/s/ABC123?password=aaaa"),
            DownloadRecord(resource_url="https://115cdn.com/s/abc123?pwd=bbbb"),
        ]
        deduped = SubscriptionService._dedupe_records_by_url(records)
        assert len(deduped) == 1

    @pytest.mark.asyncio
    async def test_fallback_does_not_retry_same_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = SubscriptionService()
        initial = DownloadRecord(
            resource_url="https://115.com/s/ABC123?password=aaaa",
            resource_name="资源 A",
            resource_type="pan115",
        )
        duplicate = DownloadRecord(
            resource_url="https://115cdn.com/s/abc123?pwd=bbbb",
            resource_name="资源 A（重复）",
            resource_type="pan115",
        )
        auto_save = AsyncMock(
            return_value={
                "saved": 0,
                "failed": 1,
                "skipped": 0,
                "errors": [{"error": "链接已过期"}],
                "subscription_completed": False,
                "remaining_missing_count": None,
            }
        )
        fetch_next = AsyncMock(return_value=[duplicate])
        monkeypatch.setattr(service, "_auto_save_resources", auto_save)
        monkeypatch.setattr(service, "_fetch_and_store_next_records", fetch_next)
        monkeypatch.setattr(service, "_create_step_log", AsyncMock())

        result = await service._auto_save_records_with_link_fallback(
            object(),
            "run-1",
            "all",
            _movie_snapshot(),
            [initial],
            transfer_source="new",
        )

        assert auto_save.await_count == 1
        assert fetch_next.await_count == 1
        assert result["failed"] == 1
        assert result["link_fallback_rounds"] == 0

    def test_expired_share_link_is_not_retryable(self) -> None:
        assert SubscriptionService._is_expired_share_link_error(
            "[Errno 5] {'error': '链接已过期', 'errno': 4100018}"
        )
        assert not SubscriptionService._is_retryable_transfer_error(
            "[Errno 5] {'error': '链接已过期', 'errno': 4100018}"
        )

    def test_merge_auto_save_stats(self) -> None:
        target = {
            "saved": 0,
            "failed": 1,
            "errors": [{"error": "a"}],
            "subscription_completed": False,
            "cleanup_step": "",
            "cleanup_message": "",
            "cleanup_payload": {},
            "remaining_missing_count": None,
        }
        SubscriptionService._merge_auto_save_stats(
            target,
            {
                "saved": 1,
                "failed": 0,
                "errors": [],
                "subscription_completed": True,
                "cleanup_step": "done",
                "cleanup_message": "ok",
                "cleanup_payload": {"k": 1},
                "remaining_missing_count": 0,
            },
        )
        assert target["saved"] == 1
        assert target["failed"] == 1
        assert target["subscription_completed"] is True
        assert target["cleanup_step"] == "done"
        assert target["remaining_missing_count"] == 0
