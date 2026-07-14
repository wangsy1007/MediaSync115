"""电视剧缺集持久化缓存测试"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.timezone_utils import beijing_now
from app.models.models import SubscriptionTvMissingCache
from app.services.tv_missing_service import TvMissingService, tv_missing_service


class TestTvMissingDbCache:
    @pytest.mark.asyncio
    async def test_get_tv_missing_statuses_reads_db_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """refresh=false 时应读取数据库缓存，且不触发批量计算。"""
        service = TvMissingService()
        tmdb_id = 990001
        subscription_id = 990001
        cached_payload = {
            "status": "ok",
            "message": "缓存命中",
            "aired_episodes": [],
            "existing_episodes": [],
            "missing_episodes": [],
            "missing_by_season": {"1": [3, 4, 5]},
            "counts": {"total": 10, "aired": 10, "existing": 7, "missing": 3},
        }

        get_db_cached = AsyncMock(return_value=cached_payload)
        collect_indexed = AsyncMock(return_value=({}, True))
        collect_tmdb = AsyncMock(return_value={(1, 1)})
        monkeypatch.setattr(service, "_get_db_cached_status", get_db_cached)
        monkeypatch.setattr(service, "_collect_indexed_existing_pairs", collect_indexed)
        monkeypatch.setattr(service, "_collect_tmdb_episode_pairs", collect_tmdb)

        result = await service.get_tv_missing_statuses(
            [tmdb_id],
            refresh=False,
            subscription_id_by_tmdb={tmdb_id: subscription_id},
        )

        assert result[tmdb_id]["message"] == "缓存命中"
        assert result[tmdb_id]["counts"]["missing"] == 3
        get_db_cached.assert_awaited_once_with(subscription_id)
        collect_indexed.assert_not_called()
        collect_tmdb.assert_not_called()

    def test_db_cache_valid_within_ttl(self) -> None:
        service = TvMissingService()
        computed_at = beijing_now() - timedelta(hours=1)
        assert service._is_db_cache_valid(computed_at) is True

    def test_db_cache_valid_after_sync(self) -> None:
        service = TvMissingService()
        sync_at = beijing_now() - timedelta(hours=1)
        computed_at = sync_at + timedelta(minutes=5)
        service._latest_sync_at_cache = sync_at
        assert service._is_db_cache_valid(computed_at) is True

    def test_db_cache_row_to_status(self) -> None:
        row = SubscriptionTvMissingCache(
            subscription_id=1,
            status="ok",
            total_count=12,
            existing_count=10,
            missing_count=2,
            missing_by_season='{"2": [1, 2]}',
            message="ok",
            computed_at=beijing_now(),
        )
        payload = tv_missing_service._db_cache_row_to_status(row)
        assert payload["counts"]["total"] == 12
        assert payload["counts"]["missing"] == 2
        assert payload["missing_by_season"] == {"2": [1, 2]}
