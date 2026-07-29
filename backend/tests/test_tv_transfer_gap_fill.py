import pytest

from app.services.pan115_service import Pan115Service
from app.utils.tv_episode_dedup import (
    dedupe_tv_transfer_files,
    filename_likely_same_show,
    folder_likely_same_show,
)


class TestTvTransferGapFill:
    def test_dedupe_keeps_missing_episodes_when_library_has_partial(self) -> None:
        """正式库已有前 10 集时，E01-E19 合集应保留 11-19。"""
        files = [
            {
                "fid": f"e{idx}",
                "name": f"Love.For.You.2026.S01E{idx:02d}.2160p.mp4",
                "size": 8_000,
            }
            for idx in range(1, 20)
        ]
        existing = {(1, episode) for episode in range(1, 11)}

        kept, skip_map = dedupe_tv_transfer_files(files, existing_episodes=existing)

        kept_eps = sorted(
            int(item["name"].split("S01E")[1][:2]) for item in kept
        )
        assert kept_eps == list(range(11, 20))
        assert len(skip_map) == 10

    @pytest.mark.asyncio
    async def test_collect_existing_uses_library_not_watch_root(
        self, monkeypatch
    ) -> None:
        """转存补缺集基准应包含正式库，而非监听目录根下待归档文件。"""
        service = Pan115Service()
        calls: list[tuple[str, str]] = []
        find_calls: list[tuple[str, str]] = []

        async def fake_collect(
            cid: str, *, show_title: str = "", max_depth: int = 6
        ) -> set[tuple[int, int]]:
            calls.append((cid, show_title))
            if cid == "show-folder":
                return {(1, episode) for episode in range(1, 11)}
            if cid == "target-subfolder":
                return set()
            if cid == "watch-root":
                return {(1, episode) for episode in range(11, 20)}
            return set()

        async def fake_find(output_cid: str, show_title: str) -> list[str]:
            find_calls.append((output_cid, show_title))
            return ["show-folder"]

        monkeypatch.setattr(service, "collect_tv_episodes_under_folder", fake_collect)
        monkeypatch.setattr(
            service,
            "find_tv_show_folders_in_archive",
            fake_find,
        )
        monkeypatch.setattr(
            "app.services.runtime_settings_service.runtime_settings_service.get_archive_output_cid",
            lambda: "output-cid",
        )

        existing = await service._collect_tv_existing_episodes_for_transfer(
            target_cid="target-subfolder",
            show_title="野狗骨头",
        )

        assert existing == {(1, episode) for episode in range(1, 11)}
        called_cids = {cid for cid, _title in calls}
        assert called_cids == {"target-subfolder", "show-folder"}
        assert ("show-folder", "") in calls
        assert find_calls == [("output-cid", "野狗骨头")]
        assert "watch-root" not in called_cids

    @pytest.mark.asyncio
    async def test_find_archive_show_folder_only_reads_category_level(
        self, monkeypatch
    ) -> None:
        """正式库查重只读根、剧集根和分类目录，不进入其它剧名目录。"""
        service = Pan115Service()
        calls: list[str] = []
        rows_by_cid = {
            "output": [
                {"fid": "movie-root", "n": "电影", "ico": "folder"},
                {"fid": "tv-root", "n": "剧集", "ico": "folder"},
            ],
            "tv-root": [
                {"fid": "us", "n": "美英剧", "ico": "folder"},
                {"fid": "cn", "n": "国产剧", "ico": "folder"},
                {"fid": "legacy-show", "n": "其它旧目录", "ico": "folder"},
            ],
            "us": [
                {
                    "fid": "house-of-dragon",
                    "n": "权力的游戏前传：龙族 (2022)",
                    "ico": "folder",
                },
                {"fid": "other-show", "n": "幕府将军 (2024)", "ico": "folder"},
            ],
            "cn": [],
        }

        async def fake_get_file_list(
            cid: str = "0",
            offset: int = 0,
            limit: int = 50,
            asc: int = 1,
            o: str = "user_ptime",
        ) -> dict:
            calls.append(cid)
            return {"data": rows_by_cid.get(cid, [])}

        monkeypatch.setattr(service, "get_file_list", fake_get_file_list)
        monkeypatch.setattr(
            "app.services.runtime_settings_service.runtime_settings_service.get_archive_subdirs",
            lambda: {
                "tv_root": "剧集",
                "tv_categories": [
                    {"name": "美英剧", "enabled": True},
                    {"name": "国产剧", "enabled": True},
                ],
            },
        )

        folder_ids = await service.find_tv_show_folders_in_archive(
            "output",
            "权力的游戏前传：龙族 (2022) S02",
        )

        assert folder_ids == ["house-of-dragon"]
        assert set(calls) == {"output", "tv-root", "us", "cn"}
        assert "legacy-show" not in calls
        assert "other-show" not in calls

    def test_show_match_ignores_selected_season_suffix(self) -> None:
        assert filename_likely_same_show(
            "House.of.the.Dragon.S02E01.2160p.mkv",
            "House of the Dragon (2022) S02",
        )
        assert folder_likely_same_show(
            "House of the Dragon (2022)",
            "House of the Dragon (2022) S02",
        )
        assert not folder_likely_same_show(
            "House of the Dragon (2022)",
            "House of Cards (2013) S02",
        )
