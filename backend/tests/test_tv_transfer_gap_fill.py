import pytest

from app.services.pan115_service import Pan115Service
from app.utils.tv_episode_dedup import dedupe_tv_transfer_files


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

        async def fake_collect(
            cid: str, *, show_title: str = "", max_depth: int = 6
        ) -> set[tuple[int, int]]:
            calls.append((cid, show_title))
            if cid == "output-cid":
                return {(1, episode) for episode in range(1, 11)}
            if cid == "target-subfolder":
                return set()
            if cid == "watch-root":
                return {(1, episode) for episode in range(11, 20)}
            return set()

        monkeypatch.setattr(service, "collect_tv_episodes_under_folder", fake_collect)
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
        assert called_cids == {"target-subfolder", "output-cid"}
        assert "watch-root" not in called_cids
