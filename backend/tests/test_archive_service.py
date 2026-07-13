from types import SimpleNamespace

import pytest

import app.services.archive_service as archive_service_module
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

    def test_parse_tv_with_season_episode(self) -> None:
        """测试剧集文件名多种格式"""
        parsed = archive_service.parse_media_filename("Game.of.Thrones.3x05.1080p.mkv")
        assert parsed["media_type"] == "tv"
        assert parsed["season"] == 3
        assert parsed["episode"] == 5

    def test_is_video(self) -> None:
        """测试视频文件识别"""
        assert archive_service._is_video("test.mkv") is True
        assert archive_service._is_video("test.mp4") is True
        assert archive_service._is_video("test.srt") is False
        assert archive_service._is_video("test.nfo") is False
        assert archive_service._is_video("test") is False

    def test_normalize_title(self) -> None:
        """测试标题清理"""
        assert archive_service._normalize_title("[CHD].The.Matrix") == "The Matrix"
        assert (
            archive_service._normalize_title("The.Matrix.1080p.BluRay") == "The Matrix"
        )

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
