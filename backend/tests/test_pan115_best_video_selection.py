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

    def test_select_files_only_when_multiple_videos(self) -> None:
        """测试多个视频时只保留最佳视频"""

        files = [
            {"fid": "1", "name": "Movie.720p.mkv", "size": 5_000},
            {"fid": "2", "name": "Movie.1080p.mkv", "size": 8_000},
            {"fid": "3", "name": "Movie.zh.srt", "size": 100},
        ]

        selected = Pan115Service._select_files_for_best_quality_transfer(files)

        assert [item["fid"] for item in selected] == ["2"]

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
