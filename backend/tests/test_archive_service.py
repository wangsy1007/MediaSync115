from types import SimpleNamespace

import asyncio
import pytest

import app.services.archive_service as archive_service_module
from app.models.archive import ArchiveStatus
from app.services.archive_service import archive_service


class TestArchiveService:
    """归档刮削服务测试"""

    def test_parse_movie_filename(self) -> None:
        """测试电影文件名解析"""
        parsed = archive_service.parse_media_filename(
            "The.Matrix.1999.1080p.BluRay.x264.mkv"
        )

        assert parsed["media_type"] == "movie"
        assert parsed["query_title"] == "The Matrix"
        assert parsed["year"] == "1999"
        assert parsed["season"] is None
        assert parsed["episode"] is None

    def test_parse_tv_filename(self) -> None:
        """测试剧集文件名解析"""
        parsed = archive_service.parse_media_filename(
            "Breaking.Bad.S01E02.1080p.WEB-DL.mkv"
        )

        assert parsed["media_type"] == "tv"
        assert parsed["query_title"] == "Breaking Bad"
        assert parsed["season"] == 1
        assert parsed["episode"] == 2

    def test_parse_movie_with_chinese(self) -> None:
        """测试中文电影文件名解析"""
        parsed = archive_service.parse_media_filename(
            "黑客帝国.1999.1080p.BluRay.x264.mkv"
        )

        assert parsed["media_type"] == "movie"
        assert parsed["year"] == "1999"
        assert parsed["query_title"] == "黑客帝国"

    def test_parse_chinese_title_glued_to_quality_tags(self) -> None:
        """中文片名与 4K/HDR 等标签粘连时应正确截取标题"""
        parsed = archive_service.parse_media_filename(
            "火遮眼4K.HDR&杜比视界内封精修简英双语&简中特效sup字幕2160p.iT.WEB-DL.DV.HDR.DDP5.1.Atmos.H.265-qun776760979.mkv"
        )
        assert parsed["media_type"] == "movie"
        assert parsed["query_title"] == "火遮眼"
        candidates = archive_service._build_title_query_candidates(parsed)
        assert "火遮眼" in candidates

    def test_parse_bracket_prefix_and_uhd(self) -> None:
        """片头广告括号与 UHD/WEB-DL 标记应被剥离"""
        parsed = archive_service.parse_media_filename(
            "【高清剧集网】The.Batman.2022.2160p.UHD.BluRay.x265.HDR.mkv"
        )
        assert parsed["query_title"] == "The Batman"
        assert parsed["year"] == "2022"

    def test_parse_glued_115_prefix_and_year(self) -> None:
        """115 前缀、粘连年份与发布组标签应能解析出片名"""
        parsed = archive_service.parse_media_filename(
            "115Zootopia.22025RepackUSAsGnbCHDBits.iso"
        )
        assert parsed["query_title"] == "Zootopia"
        assert parsed["year"] == "2025"
        candidates = archive_service._build_title_query_candidates(parsed)
        assert "Zootopia" in candidates

    def test_parse_chinese_tv_episode(self) -> None:
        """中文集数格式"""
        parsed = archive_service.parse_media_filename(
            "庆余年.第01集.1080p.WEB-DL.mkv"
        )
        assert parsed["media_type"] == "tv"
        assert parsed["episode"] == 1
        assert parsed["query_title"] == "庆余年"

        parsed2 = archive_service.parse_media_filename(
            "三体.第2季.第03集.2160p.mkv"
        )
        assert parsed2["media_type"] == "tv"
        assert parsed2["season"] == 2
        assert parsed2["episode"] == 3
        assert parsed2["query_title"] == "三体"

    def test_parse_tv_with_season_episode(self) -> None:
        """测试剧集文件名多种格式"""
        parsed = archive_service.parse_media_filename("Game.of.Thrones.3x05.1080p.mkv")
        assert parsed["media_type"] == "tv"
        assert parsed["season"] == 3
        assert parsed["episode"] == 5
        assert parsed["query_title"] == "Game of Thrones"

    def test_is_video(self) -> None:
        """测试视频文件识别"""
        assert archive_service._is_video("test.mkv") is True
        assert archive_service._is_video("test.mp4") is True
        assert archive_service._is_video("test.iso") is True
        assert archive_service._is_video("test.m2ts") is True
        assert archive_service._is_video("test.srt") is False
        assert archive_service._is_video("test.nfo") is False
        assert archive_service._is_video("test") is False

    def test_normalize_title(self) -> None:
        """测试标题清理"""
        assert archive_service._normalize_title("[CHD].The.Matrix") == "The Matrix"
        assert (
            archive_service._normalize_title("The.Matrix.1080p.BluRay") == "The Matrix"
        )
        assert archive_service._normalize_title("火遮眼4K") == "火遮眼"
        assert archive_service._normalize_title("Spider-Man.No.Way.Home") == (
            "Spider Man No Way Home"
        )

    @pytest.mark.asyncio
    async def test_identify_media_tries_cjk_fallback(self, monkeypatch) -> None:
        """脏文件名识别时应回退到中文短标题"""
        calls: list[str] = []

        async def fake_search(*, query, media_type, page=1, year=None):
            calls.append(query)
            if query == "火遮眼":
                return {
                    "results": [
                        {"id": 1280738, "tmdb_id": 1280738, "title": "火遮眼"}
                    ]
                }
            return {"results": []}

        async def fake_detail(tmdb_id):
            return {
                "title": "火遮眼",
                "release_date": "2025-01-01",
                "genres": [{"id": 28, "name": "动作"}],
                "origin_country": ["CN"],
                "production_countries": [{"iso_3166_1": "CN"}],
            }

        monkeypatch.setattr(
            archive_service_module.tmdb_service,
            "search_by_media_type",
            fake_search,
        )
        monkeypatch.setattr(
            archive_service_module.tmdb_service,
            "get_movie_detail",
            fake_detail,
        )

        parsed = archive_service.parse_media_filename(
            "火遮眼4K.HDR&杜比视界内封精修2160p.WEB-DL.mkv"
        )
        matched = await archive_service.identify_media(parsed)
        assert matched is not None
        assert matched["tmdb_id"] == 1280738
        assert matched["title"] == "火遮眼"
        assert "火遮眼" in calls

    def test_build_target_desc_with_custom_roots(self) -> None:
        """测试自定义一级目录的目标路径描述"""
        subdirs = {"movie_root": "Movies", "tv_root": "TV Shows"}
        movie_desc = archive_service._build_target_desc(
            "movie", subdirs, "华语电影", "黑客帝国 (1999)"
        )
        tv_desc = archive_service._build_target_desc(
            "tv", subdirs, "国产剧", "庆余年 (2019)", season=1
        )
        assert movie_desc == "Movies/华语电影/黑客帝国 (1999)"
        assert tv_desc == "TV Shows/国产剧/庆余年 (2019)/第1季"

    def test_build_target_filename_with_custom_naming(self) -> None:
        """测试自定义文件命名模板"""
        parsed = {
            "media_type": "movie",
            "query_title": "The Matrix",
            "extension": ".mkv",
        }
        matched = {"title": "黑客帝国", "year": "1999", "tmdb_id": 603, "region_name": "华语电影"}
        naming = {"movie_file": "{title}.{year}.{format}{ext}"}
        filename = archive_service._build_target_filename(
            parsed,
            matched,
            "The.Matrix.1999.2160p.HDR10.HEVC.WEB-DL.mkv",
            naming,
        )
        assert filename == "黑客帝国.1999.4K HDR10 HEVC.mkv"

    def test_resolve_archive_display_title_prefers_transfer_name_for_movie(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "The Wandering Earth II",
        }
        matched = {"title": "流浪地球2", "year": "2023"}
        title = archive_service._resolve_archive_display_title(
            parsed,
            matched,
            transfer_context={
                "resource_name": "流浪地球2.2023.2160p.WEB-DL.mkv",
                "subscription_title": "流浪地球2",
            },
        )
        assert title == "流浪地球2"

    def test_resolve_archive_display_title_prefers_intent_title(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "Wrong English Title",
        }
        matched = {"title": "错误匹配", "year": "2025"}
        title = archive_service._resolve_archive_display_title(
            parsed,
            matched,
            transfer_context={
                "intent": {"display_title": "浪浪山小妖怪"},
                "resource_name": "Some.English.Release.2025.mkv",
            },
        )
        assert title == "浪浪山小妖怪"

    def test_title_from_transfer_resource_name(self) -> None:
        title = archive_service._title_from_transfer_resource_name(
            "The.Batman.2022.2160p.UHD.BluRay.x265.HDR.mkv"
        )
        assert title == "The Batman"

    def test_build_target_filename_uses_display_title(self) -> None:
        parsed = {"media_type": "movie", "query_title": "Matrix", "extension": ".mkv"}
        matched = {"title": "黑客帝国", "year": "1999"}
        filename = archive_service._build_target_filename(
            parsed,
            matched,
            "old.mkv",
            None,
            display_title="流浪地球2",
        )
        assert filename == "流浪地球2 (1999).mkv"

    @pytest.mark.asyncio
    async def test_retry_success_triggers_scoped_strm(self, monkeypatch) -> None:
        """测试重试成功后携带归档成果触发 STRM"""

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, model, task_id):
                return SimpleNamespace(
                    source_path="source-fid",
                    source_filename="测试电影.2026.mkv",
                )

        result = {
            "task_id": 7,
            "status": "success",
            "source_fid": "source-fid",
            "source_filename": "测试电影.2026.mkv",
            "target_cid": "target-cid",
            "target_desc": "电影/华语电影/测试电影 (2026)",
        }
        triggered: dict = {}

        async def fake_process_one(*args, **kwargs):
            return result

        async def fake_trigger(summary, trigger):
            triggered["summary"] = summary
            triggered["trigger"] = trigger

        monkeypatch.setattr(
            archive_service_module, "async_session_maker", lambda: FakeSession()
        )
        monkeypatch.setattr(archive_service, "_get_pan115", lambda: object())
        monkeypatch.setattr(archive_service, "_process_one", fake_process_one)
        monkeypatch.setattr(
            archive_service, "_trigger_strm_after_archive", fake_trigger
        )

        response = await archive_service.retry_task(7)

        assert response is result
        assert triggered["trigger"] == "retry"
        assert triggered["summary"] == {
            "success": 1,
            "failed": 0,
            "skipped": 0,
            "total": 1,
            "items": [result],
        }

    @pytest.mark.asyncio
    async def test_recover_stale_state_marks_processing_failed(
        self, monkeypatch
    ) -> None:
        """服务重启后应把 processing 任务标记为失败"""

        class FakeTask:
            status = ArchiveStatus.PROCESSING
            error_message = None
            completed_at = None

        fake_task = FakeTask()

        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return [fake_task]

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def execute(self, query):
                return FakeResult()

            async def commit(self):
                return None

        monkeypatch.setattr(
            archive_service_module, "async_session_maker", lambda: FakeSession()
        )

        result = await archive_service.recover_stale_state()

        assert result["recovered_tasks"] == 1
        assert fake_task.status == ArchiveStatus.FAILED
        assert "服务重启" in str(fake_task.error_message)

    @pytest.mark.asyncio
    async def test_run_scan_timeout_marks_processing_failed(
        self, monkeypatch
    ) -> None:
        """扫描超时应释放锁并把 processing 任务标记为失败"""

        async def slow_scan(*args, **kwargs):
            await asyncio.sleep(0.2)
            return {"success": 0, "failed": 0, "skipped": 0, "total": 0, "items": []}

        marked: dict[str, int] = {"count": 0}

        async def fake_mark(**kwargs):
            marked["count"] += 1
            return 1

        monkeypatch.setattr(archive_service, "ARCHIVE_SCAN_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(archive_service, "_run_scan_locked", slow_scan)
        monkeypatch.setattr(
            archive_service, "_mark_processing_tasks_failed", fake_mark
        )

        with pytest.raises(TimeoutError):
            await archive_service.run_scan(trigger="manual")

        assert marked["count"] == 1

    @pytest.mark.asyncio
    async def test_cancel_scan_marks_all_processing_tasks_failed(
        self, monkeypatch
    ) -> None:
        """无后台扫描任务时，取消仍应清理所有 processing 任务"""

        marked: dict[str, object] = {}

        async def fake_mark(**kwargs):
            marked.update(kwargs)
            return 2

        async def fake_runtime():
            return {"scan_running": False, "processing_count": 0, "scan_active": False}

        monkeypatch.setattr(archive_service, "_background_scan_task", None)
        monkeypatch.setattr(
            archive_service, "_mark_processing_tasks_failed", fake_mark
        )
        monkeypatch.setattr(
            archive_service, "get_runtime_status_async", fake_runtime
        )

        result = await archive_service.cancel_scan()

        assert result["cancelled"] is True
        assert result["recovered_tasks"] == 2
        assert marked.get("max_age_minutes") is None
        assert "已取消" in str(marked.get("reason"))

    @pytest.mark.asyncio
    async def test_reconcile_idle_processing_tasks_uses_idle_threshold(
        self, monkeypatch
    ) -> None:
        marked: dict[str, object] = {}

        async def fake_mark(**kwargs):
            marked.update(kwargs)
            return 1

        monkeypatch.setattr(
            archive_service, "_mark_processing_tasks_failed", fake_mark
        )

        count = await archive_service.reconcile_idle_processing_tasks()

        assert count == 1
        assert marked.get("max_age_minutes") == archive_service_module.ARCHIVE_IDLE_PROCESSING_MINUTES


class TestArchiveTvEpisodeDedup:
    def test_dedupe_keeps_collection_for_missing_episodes(self) -> None:
        identified = [
            {
                "item": {"fid": "pack", "name": "Show.S01E01-E10.2160p.mkv", "size": 20_000},
                "parsed": {"media_type": "tv", "season": 1, "episode": 1},
                "matched": {"tmdb_id": 100, "title": "Show"},
            },
        ]

        skip_map = archive_service._dedupe_tv_identified_items(identified)

        assert skip_map == {}

    def test_dedupe_builds_best_single_for_same_episode(self) -> None:
        identified = [
            {
                "item": {"fid": "low", "name": "Show.S01E01.720p.mkv", "size": 4_000},
                "parsed": {"media_type": "tv", "season": 1, "episode": 1},
                "matched": {"tmdb_id": 100, "title": "Show"},
            },
            {
                "item": {"fid": "high", "name": "Show.S01E01.2160p.mkv", "size": 12_000},
                "parsed": {"media_type": "tv", "season": 1, "episode": 1},
                "matched": {"tmdb_id": 100, "title": "Show"},
            },
        ]

        skip_map = archive_service._dedupe_tv_identified_items(identified)

        assert skip_map.get("low")
        assert "high" not in skip_map

