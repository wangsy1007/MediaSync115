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

    def test_parse_title_year_then_release_year(self) -> None:
        """片名自带年份时，应取画质前最后一个年份作上映年"""
        parsed = archive_service.parse_media_filename(
            "Cold.War.1994.2026.2160p.WEB-DL.HQ.HDR.60FPS.H.265.DTS5.1-HiveWeb.mp4"
        )
        assert parsed["year"] == "2026"
        assert parsed["query_title"] == "Cold War 1994"
        candidates = archive_service._build_title_query_candidates(parsed)
        assert "Cold War 1994" in candidates

    def test_parse_chinese_title_year_then_release_year(self) -> None:
        """中文片名粘连历史年份时，也应保留片名年份并识别上映年"""
        parsed = archive_service.parse_media_filename(
            "冷战1994.2026.2160p.WEB-DL.mkv"
        )
        assert parsed["year"] == "2026"
        assert "冷战" in parsed["query_title"]
        assert "1994" in parsed["query_title"]

    def test_rank_tmdb_items_by_year_prefers_exact(self) -> None:
        ranked = archive_service._rank_tmdb_items_by_year(
            [
                {"title": "寒战", "release_date": "2012-11-08"},
                {"title": "冷战1994", "release_date": "2026-04-30"},
                {"title": "冷战", "release_date": "1997-01-01"},
            ],
            2026,
        )
        assert len(ranked) == 1
        assert ranked[0]["title"] == "冷战1994"

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

    def test_parse_sxxexx_not_broken_by_stem_normalization(self) -> None:
        """数字与大写字母分界不得把 S02E01 拆成 S02.E01 导致季号丢失。"""
        parsed = archive_service.parse_media_filename(
            "House.of.the.Dragon.S02E01.2024.2160p.BluRay.REMUX.mkv"
        )
        assert parsed["media_type"] == "tv"
        assert parsed["season"] == 2
        assert parsed["episode"] == 1

        parsed2 = archive_service.parse_media_filename(
            "权力的游戏前传：龙族.2022.S03E02.第2集.2160p.HBO.WEB-DL.mkv"
        )
        assert parsed2["season"] == 3
        assert parsed2["episode"] == 2

        parsed3 = archive_service.parse_media_filename(
            "权力的游戏前传：龙族.House of the Dragon (2022) S02E03.火磨坊.2160p.mkv"
        )
        assert parsed3["season"] == 2
        assert parsed3["episode"] == 3

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

    def test_resolve_archive_display_title_strips_resource_ads(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "The Batman",
        }
        matched = {"title": "蝙蝠侠", "year": "2022"}
        title = archive_service._resolve_archive_display_title(
            parsed,
            matched,
            transfer_context={
                "folder_name": "【高清剧集网】蝙蝠侠 4K杜比视界",
                "resource_name": "【高清剧集网】The.Batman.2022.2160p.mkv",
            },
        )
        assert title == "蝙蝠侠"

    def test_resolve_archive_display_title_prefers_intent_title(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "Wrong English Title",
            "source_filename": "浪浪山小妖怪.2025.mkv",
        }
        matched = {"title": "错误匹配", "year": "2025", "tmdb_id": 12345}
        title = archive_service._resolve_archive_display_title(
            parsed,
            matched,
            transfer_context={
                "intent": {"display_title": "浪浪山小妖怪", "tmdb_id": 12345},
                "resource_name": "Some.English.Release.2025.mkv",
                "filename": "浪浪山小妖怪.2025.mkv",
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


class TestArchiveTargetConflict:
    def test_snapshot_detects_cloud_duplicate_suffix(self) -> None:
        snapshot = {
            "files": [
                {
                    "fid": "existing",
                    "name": "权力的游戏前传 (2022) - S01E01.mkv",
                    "normalized": "权力的游戏前传 (2022) - s01e01.mkv",
                }
            ],
            "basenames": {"权力的游戏前传 (2022) - s01e01.mkv"},
            "episodes": {(1, 1)},
        }
        message = archive_service._snapshot_has_filename_conflict(
            snapshot,
            source_filename="release.S01E01.2160p.mkv",
            target_filename="权力的游戏前传 (2022) - S01E01.mkv",
        )
        assert message
        assert "已跳过" in message

    def test_snapshot_ignores_same_fid(self) -> None:
        snapshot = {
            "files": [
                {
                    "fid": "same",
                    "name": "Show S01E01.mkv",
                    "normalized": "show s01e01.mkv",
                }
            ],
            "basenames": {"show s01e01.mkv"},
            "episodes": {(1, 1)},
        }
        message = archive_service._snapshot_has_filename_conflict(
            snapshot,
            source_filename="Show S01E01.mkv",
            target_filename="Show S01E01.mkv",
            exclude_fid="same",
        )
        assert message is None

    @pytest.mark.asyncio
    async def test_tv_conflict_skips_existing_episode_from_suffixed_file(
        self, monkeypatch
    ) -> None:
        class FakePan115:
            async def get_file_list(self, **kwargs):
                return {
                    "data": [
                        {
                            "fid": "old",
                            "name": "权力的游戏前传 (2022) - S01E01 (1).mkv",
                        }
                    ]
                }

            def _is_folder_item(self, row):
                return False

        parsed = {"media_type": "tv", "season": 1, "episode": 2}
        message = await archive_service._check_tv_episode_archive_conflict(
            FakePan115(),
            parsed,
            "release.S01E02.2160p.mkv",
            "season-cid",
            None,
            new_filename="权力的游戏前传 (2022) - S01E02.mkv",
        )
        assert message is None

        parsed = {"media_type": "tv", "season": 1, "episode": 1}
        message = await archive_service._check_tv_episode_archive_conflict(
            FakePan115(),
            parsed,
            "release.S01E01.2160p.mkv",
            "season-cid",
            None,
            new_filename="权力的游戏前传 (2022) - S01E01.mkv",
        )
        assert message
        assert "S01E01" in message

    def test_apply_tv_hints_from_intent(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "权力的游戏前传",
            "year": "1903",
            "season": None,
            "episode": None,
        }
        fixed = archive_service._apply_tv_media_type_hints(
            parsed,
            intent={"media_type": "tv", "tmdb_id": 94997, "display_title": "权力的游戏前传"},
        )
        assert fixed["media_type"] == "tv"
        assert fixed["season"] == 1

    def test_apply_tv_hints_from_relative_path(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "灿如繁星",
            "year": "2003",
            "season": None,
            "episode": None,
        }
        fixed = archive_service._apply_tv_media_type_hints(
            parsed,
            relative_path="灿如繁星/第1季/E01.mkv",
            folder_name="第1季",
        )
        assert fixed["media_type"] == "tv"
        assert fixed["season"] == 1

    def test_apply_tv_hints_keeps_real_movie(self) -> None:
        parsed = {
            "media_type": "movie",
            "query_title": "黑客帝国",
            "year": "1999",
            "season": None,
            "episode": None,
        }
        fixed = archive_service._apply_tv_media_type_hints(
            parsed,
            intent={"media_type": "movie", "tmdb_id": 603},
            relative_path="黑客帝国.1999.mkv",
        )
        assert fixed["media_type"] == "movie"
        assert fixed.get("season") is None

    @pytest.mark.asyncio
    async def test_tv_conflict_merges_season_episode_cache(self) -> None:
        class FakePan115:
            async def get_file_list(self, **kwargs):
                return {"data": []}

            def _is_folder_item(self, row):
                return False

        cache: dict[str, set[tuple[int, int]]] = {"season-cid": {(1, 1)}}
        message = await archive_service._check_tv_episode_archive_conflict(
            FakePan115(),
            {"media_type": "tv", "season": 1, "episode": 1},
            "Show.S01E01.1080p.mp4",
            "season-cid",
            cache,
            new_filename="Show (2024) - S01E01.mp4",
        )
        assert message
        assert "S01E01" in message
        assert (1, 1) in cache["season-cid"]

    @pytest.mark.asyncio
    async def test_finalize_deletes_same_episode_different_ext(self, monkeypatch) -> None:
        deleted: list[str] = []

        class FakePan115:
            async def get_file_list(self, **kwargs):
                return {
                    "data": [
                        {
                            "fid": "old",
                            "name": "雀骨 (2024) - S01E01.mkv",
                            "size": 10_000,
                        },
                        {
                            "fid": "new",
                            "name": "雀骨.S01E01.1080p.mp4",
                            "size": 5_000,
                        },
                    ]
                }

            def _is_folder_item(self, row):
                return False

            async def delete_file(self, fids):
                deleted.extend(fids if isinstance(fids, list) else [fids])

            async def rename_file(self, *args, **kwargs):
                return True

        async def fake_mark_skipped(task_id, message):
            return None

        monkeypatch.setattr(archive_service, "_mark_task_skipped", fake_mark_skipped)

        result = await archive_service._finalize_identified(
            FakePan115(),
            plan={
                "fid": "new",
                "filename": "雀骨.S01E01.1080p.mp4",
                "parsed": {"media_type": "tv", "season": 1, "episode": 1},
                "matched": {"tmdb_id": 1, "title": "雀骨", "year": "2024"},
                "naming": None,
                "display_title": "雀骨",
                "target_cid": "season-cid",
                "target_desc": "剧集/华语剧集/雀骨 (2024)/Season 01",
                "new_filename": "雀骨 (2024) - S01E01.mp4",
                "task_id": 1,
                "item": {"fid": "new", "name": "雀骨.S01E01.1080p.mp4"},
            },
        )
        assert result["status"] == ArchiveStatus.SKIPPED.value
        assert deleted == ["new"]

    @pytest.mark.asyncio
    async def test_cleanup_keeps_higher_quality_episode(self) -> None:
        deleted: list[str] = []

        class FakePan115:
            async def get_file_list(self, **kwargs):
                return {
                    "data": [
                        {
                            "fid": "low",
                            "name": "雀骨.S01E01.720p.mp4",
                            "size": 3_000,
                        },
                        {
                            "fid": "high",
                            "name": "雀骨.S01E01.2160p.mkv",
                            "size": 12_000,
                        },
                    ]
                }

            def _is_folder_item(self, row):
                return False

            async def delete_file(self, fids):
                deleted.extend(fids if isinstance(fids, list) else [fids])

        count = await archive_service._cleanup_duplicate_tv_episodes_in_folder(
            FakePan115(),
            "season-cid",
        )
        assert count == 1
        assert deleted == ["low"]

    @pytest.mark.asyncio
    async def test_cleanup_cloud_duplicate_suffix_variants(self) -> None:
        deleted: list[str] = []

        class FakePan115:
            async def get_file_list(self, **kwargs):
                return {
                    "data": [
                        {"fid": "a", "name": "28-4K.国语中字.mp4", "size": 8_000},
                        {"fid": "b", "name": "28-4K.国语中字(1).mp4", "size": 8_000},
                        {"fid": "c", "name": "28-4K.国语中字(2).mp4", "size": 8_000},
                        {"fid": "d", "name": "28-4K.国语中字(3).mp4", "size": 8_000},
                    ]
                }

            def _is_folder_item(self, row):
                return False

            async def delete_file(self, fids):
                deleted.extend(fids if isinstance(fids, list) else [fids])

        count = await archive_service._cleanup_duplicate_tv_episodes_in_folder(
            FakePan115(),
            "movie-cid",
        )
        assert count == 3
        assert set(deleted) == {"b", "c", "d"}

    @pytest.mark.asyncio
    async def test_collect_tv_season_folder_cids(self) -> None:
        class FakePan115:
            def _is_folder_item(self, row):
                return bool(row.get("folder"))

            def _extract_folder_id(self, row):
                return str(row.get("cid") or "")

            def _share_item_name(self, row):
                return str(row.get("name") or "")

            async def _list_folder_items(self, cid, **kwargs):
                tree = {
                    "out": [
                        {"cid": "tv", "name": "剧集", "folder": True},
                    ],
                    "tv": [
                        {"cid": "cn", "name": "国产剧", "folder": True},
                    ],
                    "cn": [
                        {"cid": "show", "name": "雀骨 (2026)", "folder": True},
                    ],
                    "show": [
                        {"cid": "s1", "name": "第1季", "folder": True},
                    ],
                    "s1": [],
                }
                return tree.get(cid, [])

        monkey_subdirs = {
            "tv_root": "剧集",
            "movie_root": "电影",
            "tv_categories": [
                {"id": "cn", "name": "国产剧", "enabled": True, "is_fallback": True},
            ],
            "movie_categories": [
                {"id": "default", "name": "外语电影", "enabled": True, "is_fallback": True},
            ],
        }
        original = archive_service._get_archive_subdirs
        archive_service._get_archive_subdirs = lambda: monkey_subdirs
        try:
            cids = await archive_service._collect_tv_season_folder_cids(
                FakePan115(), "out"
            )
        finally:
            archive_service._get_archive_subdirs = original
        # 分类/剧名/季 都会纳入清理候选
        assert cids == ["cn", "show", "s1"]

