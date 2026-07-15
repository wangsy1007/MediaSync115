from app.utils.tv_episode_dedup import dedupe_tv_transfer_files


class TestTvEpisodeTransferDedup:
    def test_prefers_single_over_collection(self) -> None:
        files = [
            {"fid": "pack", "name": "Show.S01E01-E10.2160p.mkv", "size": 20_000},
            {"fid": "single", "name": "Show.S01E01.1080p.mkv", "size": 8_000},
            {"fid": "e2", "name": "Show.S01E02.1080p.mkv", "size": 8_000},
        ]

        kept, skip_map = dedupe_tv_transfer_files(files)

        assert {item["fid"] for item in kept} == {"single", "e2"}
        assert "pack" in skip_map

    def test_skips_episode_already_on_pan(self) -> None:
        files = [
            {"fid": "e3", "name": "Show.S01E03.1080p.mkv", "size": 8_000},
        ]

        kept, skip_map = dedupe_tv_transfer_files(
            files,
            existing_episodes={(1, 3)},
        )

        assert kept == []
        assert "e3" in skip_map
