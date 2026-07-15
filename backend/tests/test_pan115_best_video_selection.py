import pytest

from app.services.pan115_service import Pan115Service


class TestPan115BestVideoSelection:
    """115 多视频择优转存测试"""

    def test_pick_best_video_prefers_higher_resolution(self) -> None:
        """测试优先选择高分辨率视频"""

        files = [
            {"fid": "1", "name": "Movie.1080p.WEB-DL.mkv", "size": 8_000},
            {"fid": "2", "name": "Movie.2160p.WEB-DL.mkv", "size": 6_000},
            {"fid": "3", "name": "Movie.720p.BluRay.mkv", "size": 10_000},
        ]

        best = Pan115Service.pick_best_video_file(files)

        assert best is not None
        assert best["fid"] == "2"

    def test_pick_best_video_penalizes_samples(self) -> None:
        """测试排除 sample 片段"""

        files = [
            {"fid": "1", "name": "Movie.sample.2160p.mkv", "size": 2_000},
            {"fid": "2", "name": "Movie.1080p.WEB-DL.mkv", "size": 8_000},
        ]

        best = Pan115Service.pick_best_video_file(files)

        assert best is not None
        assert best["fid"] == "2"

    def test_share_item_name_reads_proapi_fn_field(self) -> None:
        """proapi share/snap 使用 fn 字段表示文件名"""

        item = {
            "fid": "3413434513370655131",
            "fn": "偏偏遇见你.2026 - S01E17.mkv",
            "fs": "307122081",
        }

        assert Pan115Service._share_item_name(item).endswith(".mkv")
        assert Pan115Service._share_item_size(item) == 307122081
        assert Pan115Service._share_item_fid(item) == "3413434513370655131"

    def test_select_files_recognizes_proapi_fn_as_video(self) -> None:
        """分享列表仅有 fn 时也应识别为视频并参与择优"""

        files = [
            {
                "fid": "1",
                "fn": "Movie.720p.mkv",
                "fs": 5_000,
            },
            {
                "fid": "2",
                "fn": "Movie.1080p.mkv",
                "fs": 8_000,
            },
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(files)

        assert [item["fid"] for item in selected] == ["2"]

    def test_select_files_only_when_multiple_videos(self) -> None:
        """测试多个视频时只保留最佳视频"""

        files = [
            {"fid": "1", "name": "Movie.720p.mkv", "size": 5_000},
            {"fid": "2", "name": "Movie.1080p.mkv", "size": 8_000},
            {"fid": "3", "name": "Movie.zh.srt", "size": 100},
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(files)

        assert [item["fid"] for item in selected] == ["2"]

    def test_select_files_same_movie_different_names_in_folder(self) -> None:
        """同一文件夹内中英文片名不同，应只转存最高画质"""

        files = [
            {
                "fid": "1",
                "name": "十二生肖 2012 1080p BluRay.mkv",
                "size": 8_000,
                "relative_path": "MoviePack",
            },
            {
                "fid": "2",
                "name": "Chinese Zodiac 2012 2160p WEB-DL.mkv",
                "size": 12_000,
                "relative_path": "MoviePack",
            },
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(
            files, media_type="movie"
        )

        assert [item["fid"] for item in selected] == ["2"]

    def test_select_files_collection_keeps_one_best_per_movie(self) -> None:
        """同一文件夹内多部不同电影，应各保留最高画质"""

        files = [
            {
                "fid": "1",
                "name": "十二生肖 2012 1080p.mkv",
                "size": 8_000,
                "relative_path": "Pack",
            },
            {
                "fid": "2",
                "name": "十二生肖 2012 2160p.mkv",
                "size": 12_000,
                "relative_path": "Pack",
            },
            {
                "fid": "3",
                "name": "全城热恋 2010 720p.mkv",
                "size": 4_000,
                "relative_path": "Pack",
            },
            {
                "fid": "4",
                "name": "全城热恋 2010 1080p.mkv",
                "size": 7_000,
                "relative_path": "Pack",
            },
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(
            files, media_type="movie"
        )

        assert sorted(item["fid"] for item in selected) == ["2", "4"]

    def test_select_files_tv_episodes_are_not_merged(self) -> None:
        """电视剧多集不应被电影去重逻辑合并"""

        files = [
            {
                "fid": "1",
                "name": "Show.S01E01.1080p.mkv",
                "size": 8_000,
                "relative_path": "Season 1",
            },
            {
                "fid": "2",
                "name": "Show.S01E02.1080p.mkv",
                "size": 8_000,
                "relative_path": "Season 1",
            },
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(
            files, media_type="movie"
        )

        assert sorted(item["fid"] for item in selected) == ["1", "2"]

    def test_select_files_tv_episodes_dedupe_same_episode(self) -> None:
        """电视剧同集多文件应只转存最优一个"""

        files = [
            {
                "fid": "1",
                "name": "Show.S01E01.720p.mkv",
                "size": 5_000,
                "relative_path": "Season 1",
            },
            {
                "fid": "2",
                "name": "Show.S01E01.1080p.mkv",
                "size": 8_000,
                "relative_path": "Season 1",
            },
            {
                "fid": "3",
                "name": "Show.S01E02.1080p.mkv",
                "size": 8_000,
                "relative_path": "Season 1",
            },
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(
            files, media_type="tv"
        )

        assert sorted(item["fid"] for item in selected) == ["2", "3"]

    def test_select_files_media_type_tv_skips_movie_dedup(self) -> None:
        """显式电视剧转存时不做电影择优"""

        files = [
            {"fid": "1", "name": "Movie.720p.mkv", "size": 5_000},
            {"fid": "2", "name": "Movie.1080p.mkv", "size": 8_000},
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(
            files, media_type="tv"
        )

        assert sorted(item["fid"] for item in selected) == ["1", "2"]

    @pytest.mark.asyncio
    async def test_save_share_directly_transfers_best_video_only(
        self, monkeypatch
    ) -> None:
        """测试直存入口只转存最佳视频"""

        service = Pan115Service(cookie="test-cookie")
        received: dict[str, object] = {}

        async def fake_get_files(share_code, receive_code, cid="0", visited_cids=None):
            return [
                {"fid": "1", "name": "Movie.720p.mkv", "size": 5_000},
                {"fid": "2", "name": "Movie.1080p.mkv", "size": 8_000},
            ]

        async def fake_save_files(share_code, file_ids, pid="0", receive_code=""):
            received["file_ids"] = file_ids
            return {"state": True}

        monkeypatch.setattr(service, "_resolve_share_payload", lambda *_: ("abc", ""))
        monkeypatch.setattr(service, "get_share_all_files_recursive", fake_get_files)
        monkeypatch.setattr(service, "save_share_files", fake_save_files)

        result = await service.save_share_directly("https://115.com/s/abc")

        assert received["file_ids"] == ["2"]
        assert result["file_count"] == 1
        assert result["original_file_count"] == 2
        assert result["selected_best_video"] is True
