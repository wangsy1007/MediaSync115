from app.utils.tv_episode_dedup import dedupe_tv_transfer_files


class TestTvEpisodeTransferDedup:
    def test_keeps_collection_when_it_fills_missing_episodes(self) -> None:
        files = [
            {"fid": "pack", "name": "Show.S01E01-E10.2160p.mkv", "size": 20_000},
        ]

        kept, skip_map = dedupe_tv_transfer_files(
            files,
            existing_episodes={(1, 1)},
        )

        assert [item["fid"] for item in kept] == ["pack"]
        assert "pack" not in skip_map

    def test_prefers_single_over_collection_for_same_missing_episode(self) -> None:
        files = [
            {"fid": "pack", "name": "Show.S01E01-E10.2160p.mkv", "size": 20_000},
            {"fid": "single", "name": "Show.S01E01.1080p.mkv", "size": 8_000},
            {"fid": "e2", "name": "Show.S01E02.1080p.mkv", "size": 8_000},
        ]

        kept, skip_map = dedupe_tv_transfer_files(files)

        assert {item["fid"] for item in kept} == {"pack"}

    def test_keeps_singles_for_episodes_not_in_collection(self) -> None:
        files = [
            {"fid": "pack", "name": "Show.S01E02-E05.2160p.mkv", "size": 20_000},
            {"fid": "e1", "name": "Show.S01E01.1080p.mkv", "size": 8_000},
        ]

        kept, _skip_map = dedupe_tv_transfer_files(files)

        assert {item["fid"] for item in kept} == {"e1", "pack"}

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

    def test_dedupes_duplicate_singles_by_quality(self) -> None:
        files = [
            {"fid": "low", "name": "Show.S01E01.720p.mkv", "size": 4_000},
            {"fid": "high", "name": "Show.S01E01.2160p.mkv", "size": 12_000},
        ]

        kept, skip_map = dedupe_tv_transfer_files(files)

        assert [item["fid"] for item in kept] == ["high"]
        assert "low" in skip_map
