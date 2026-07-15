"""
订阅资源归属校验测试（防止自动转存串台）
"""
import pytest

from app.models.models import DownloadRecord, MediaType
from app.services.subscription_service import (
    SubscriptionService,
    SubscriptionSnapshot,
    subscription_service,
)


def _tv_snapshot(
    *,
    title: str,
    tmdb_id: int | None = 1,
    year: str = "2026",
) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id=1,
        tmdb_id=tmdb_id,
        douban_id="",
        title=title,
        media_type=MediaType.TV,
        year=year,
        auto_download=True,
        tv_scope="all",
        tv_season_number=None,
        tv_episode_start=None,
        tv_episode_end=None,
        tv_follow_mode="missing",
        tv_include_specials=False,
        has_successful_transfer=False,
    )


def _movie_snapshot(
    *,
    title: str,
    tmdb_id: int | None = 1,
    year: str = "2025",
) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id=2,
        tmdb_id=tmdb_id,
        douban_id="",
        title=title,
        media_type=MediaType.MOVIE,
        year=year,
        auto_download=True,
        tv_scope="all",
        tv_season_number=None,
        tv_episode_start=None,
        tv_episode_end=None,
        tv_follow_mode="missing",
        tv_include_specials=False,
        has_successful_transfer=False,
    )


class TestSubscriptionResourceRelevance:
  """NAS 日志中已出现的串台样例应被拦截"""

  @pytest.mark.asyncio
  async def test_rejects_wrong_tg_tv_title(self) -> None:
      sub = _tv_snapshot(title="群体")
      context = {"title": "群体", "original_title": "", "year": "2026"}
      item = {
          "title": "📺 电视剧：女帝 (2026) - S01E01-E24(完结)",
          "resource_name": "📺 电视剧：女帝 (2026) - S01E01-E24(完结)",
      }
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, item, context
      )

  @pytest.mark.asyncio
  async def test_rejects_wrong_tg_movie_title(self) -> None:
      sub = _movie_snapshot(title="春")
      context = {"title": "春", "original_title": "", "year": "2025"}
      item = {"title": "🎬 电影：青爱 (2025)"}
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, item, context
      )

  @pytest.mark.asyncio
  async def test_accepts_matching_tg_title(self) -> None:
      sub = _tv_snapshot(title="希望")
      context = {"title": "希望", "original_title": "", "year": "2026"}
      item = {"title": "📺 电视剧：希望 (2026) - S01E09"}
      assert await subscription_service._is_resource_relevant_for_subscription(
          sub, item, context
      )

  @pytest.mark.asyncio
  async def test_accepts_episode_only_hdhive_name(self) -> None:
      sub = _tv_snapshot(title="将夜")
      context = {"title": "将夜", "original_title": "Ever Night", "year": "2018"}
      item = {"title": "S01E01-E11 4K WEB-DL HDR HiveWeb"}
      assert await subscription_service._is_resource_relevant_for_subscription(
          sub, item, context
      )

  @pytest.mark.asyncio
  async def test_tmdb_tag_must_match_subscription(self) -> None:
      sub = _tv_snapshot(title="莫离", tmdb_id=292696)
      context = {"title": "莫离", "original_title": "", "year": "2026"}
      wrong = {
          "title": "📺 电视剧：爱情有烟火 (2026) [tmdbid-230311] S01E01-E11",
      }
      right = {
          "title": "📺 电视剧：莫离 (2026) [tmdbid-292696] S01E01-E24",
      }
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, wrong, context
      )
      assert await subscription_service._is_resource_relevant_for_subscription(
          sub, right, context
      )

  @pytest.mark.asyncio
  async def test_filter_resources_for_subscription(self) -> None:
      sub = _tv_snapshot(title="故土")
      context = {"title": "故土", "original_title": "", "year": "2026"}
      resources = [
          {"title": "📺 电视剧：搜神记 (2026) - S01E15"},
          {"title": "📺 电视剧：故土 (2026) - S01E15"},
          {"title": "S01E15 4K WEB-DL"},
      ]
      kept, excluded = await subscription_service._filter_resources_for_subscription(
          sub, resources, context
      )
      assert excluded == 1
      assert len(kept) == 2

  @pytest.mark.asyncio
  async def test_accepts_hdhive_generic_label_with_matched_media_title(self) -> None:
      sub = _movie_snapshot(title="十二生肖", tmdb_id=98567, year="2012")
      context = {"title": "十二生肖", "original_title": "十二生肖", "year": "2012"}
      item = {
          "title": "1080P蓝光原盘[港版原盘 国粤双语 简繁中字][DTS-HDMA 7.1]",
          "matched_media_title": "十二生肖",
          "hdhive_source_tmdb_id": 98567,
      }
      assert await subscription_service._is_resource_relevant_for_subscription(
          sub, item, context
      )

  @pytest.mark.asyncio
  async def test_rejects_hdhive_collection_pack_for_single_movie(self) -> None:
      sub = _movie_snapshot(title="十二生肖", tmdb_id=98567, year="2012")
      context = {"title": "十二生肖", "original_title": "十二生肖", "year": "2012"}
      item = {
          "title": "[成龙1992-2016蓝光原盘集2][878.70GB]12生肖 Chinese Zodiac 2012 .iso",
          "matched_media_title": "十二生肖",
          "hdhive_source_tmdb_id": 98567,
      }
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, item, context
      )

  @pytest.mark.asyncio
  async def test_accepts_download_record_with_hdhive_metadata(self) -> None:
      """HDHive 通用资源名入库后，转存阶段应能识别 TMDB 归属。"""
      sub = _movie_snapshot(title="肖申克的救赎", tmdb_id=278, year="1994")
      context = {
          "title": "肖申克的救赎",
          "original_title": "The Shawshank Redemption",
          "year": "1994",
      }
      record = DownloadRecord(
          subscription_id=6,
          resource_name="4K蓝光原盘，内封中文字幕，HDR+杜比视界！",
          resource_url="https://115.com/s/example",
          resource_type="pan115",
          source_tmdb_id=278,
          matched_media_title="肖申克的救赎",
          relevance_verified=False,
      )
      assert await subscription_service._is_resource_relevant_for_subscription(
          sub, record, context
      )

  @pytest.mark.asyncio
  async def test_accepts_relevance_verified_download_record(self) -> None:
      """已通过搜索阶段归属过滤的资源，转存时不再重复误判。"""
      sub = _movie_snapshot(title="肖申克的救赎", tmdb_id=278, year="1994")
      context = {
          "title": "肖申克的救赎",
          "original_title": "The Shawshank Redemption",
          "year": "1994",
      }
      record = DownloadRecord(
          subscription_id=6,
          resource_name="4K蓝光原盘，内封中文字幕，HDR+杜比视界！",
          resource_url="https://115.com/s/example2",
          resource_type="pan115",
          source_tmdb_id=278,
          matched_media_title="肖申克的救赎",
          relevance_verified=True,
      )
      assert await subscription_service._is_resource_relevant_for_subscription(
          sub, record, context
      )

  @pytest.mark.asyncio
  async def test_rejects_relevance_verified_collection_pack(self) -> None:
      sub = _movie_snapshot(title="十二生肖", tmdb_id=98567, year="2012")
      context = {"title": "十二生肖", "original_title": "十二生肖", "year": "2012"}
      record = DownloadRecord(
          subscription_id=2,
          resource_name="[成龙1992-2016蓝光原盘集2][878.70GB]12生肖 Chinese Zodiac 2012 .iso",
          resource_url="https://115.com/s/collection",
          resource_type="pan115",
          source_tmdb_id=98567,
          matched_media_title="十二生肖",
          relevance_verified=True,
      )
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, record, context
      )

  @pytest.mark.asyncio
  async def test_legacy_download_record_is_not_blindly_claimed_on_backfill(self) -> None:
      """无归属信息的历史记录不能仅凭 subscription_id 认领为当前订阅。"""
      sub = _movie_snapshot(title="肖申克的救赎", tmdb_id=278, year="1994")
      record = DownloadRecord(
          subscription_id=6,
          resource_name="4K蓝光原盘，内封中文字幕，HDR+杜比视界！",
          resource_url="https://115.com/s/example",
          resource_type="pan115",
      )
      SubscriptionService._backfill_download_record_relevance(record, sub)
      assert record.source_tmdb_id is None
      assert record.matched_media_title is None
      assert not record.relevance_verified

  @pytest.mark.asyncio
  async def test_rejects_verified_record_from_reused_subscription_id(self) -> None:
      sub = _movie_snapshot(title="星际穿越", tmdb_id=157336, year="2014")
      context = {
          "title": "星际穿越",
          "original_title": "Interstellar",
          "year": "2014",
      }
      record = DownloadRecord(
          subscription_id=sub.id,
          resource_name="📺 电视剧：雨霖铃 (2026) - S01E30",
          resource_url="https://115.com/s/old-record",
          resource_type="pan115",
          source_tmdb_id=999999,
          matched_media_title="雨霖铃",
          relevance_verified=True,
      )
      SubscriptionService._backfill_download_record_relevance(record, sub)
      assert record.source_tmdb_id == 999999
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, record, context
      )

  @pytest.mark.asyncio
  async def test_explicit_wrong_tg_title_cannot_be_rescued_by_overview(self) -> None:
      """标题明确属于其他剧时，简介里出现“主角”也不能通过归属校验。"""
      sub = _tv_snapshot(title="主角", tmdb_id=284110, year="2026")
      context = {"title": "主角", "original_title": "", "year": "2026"}
      record = DownloadRecord(
          subscription_id=sub.id,
          resource_name="📺 电视剧：我们愉快的好日子 (2026) - S01E35",
          resource_url="https://115.com/s/polluted-record",
          resource_type="pan115",
          source_tmdb_id=284110,
          matched_media_title="讲述主角成长的故事",
          relevance_verified=True,
      )
      assert not await subscription_service._is_resource_relevant_for_subscription(
          sub, record, context
      )

  def test_extract_download_record_relevance_fields(self) -> None:
      fields = SubscriptionService._extract_download_record_relevance_fields(
          {
              "title": "4K蓝光原盘，内封中文字幕，HDR+杜比视界！",
              "matched_media_title": "肖申克的救赎",
              "hdhive_source_tmdb_id": 278,
          }
      )
      assert fields["source_tmdb_id"] == 278
      assert fields["matched_media_title"] == "肖申克的救赎"
      assert fields["relevance_verified"] is True

  def test_extract_download_record_relevance_fields_with_subscription(self) -> None:
      sub = _movie_snapshot(title="星际穿越", tmdb_id=157336, year="2014")
      fields = SubscriptionService._extract_download_record_relevance_fields(
          {"slug": "slug-1", "title": "2160p REMUX"},
          sub=sub,
      )
      assert fields["source_tmdb_id"] == 157336
      assert fields["matched_media_title"] == "星际穿越"
