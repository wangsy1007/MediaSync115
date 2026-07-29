"""
SyncService 解析逻辑测试
"""

import pytest

from app.services.sync_service import SyncService


def test_extract_receive_code_prefers_explicit() -> None:
    code = SyncService._extract_receive_code(
        "https://115.com/s/abcd1234?password=zzzz",
        {"receive_code": "yyyy"},
        "wxyz",
    )
    assert code == "wxyz"


def test_extract_receive_code_from_payload() -> None:
    code = SyncService._extract_receive_code(
        "https://115.com/s/abcd1234",
        {"receive_code": "a1b2"},
        "",
    )
    assert code == "a1b2"


def test_extract_receive_code_from_short_code() -> None:
    code = SyncService._extract_receive_code("abcd1234-1x2y", None, "")
    assert code == "1x2y"


def test_extract_receive_code_from_password_query() -> None:
    code = SyncService._extract_receive_code("https://115.com/s/abcd1234?password=p9q8", None, "")
    assert code == "p9q8"


def test_extract_receive_code_from_urlencoded_password_query() -> None:
    code = SyncService._extract_receive_code("https%3A%2F%2F115.com%2Fs%2Fabcd1234%3Fpwd%3Dk7m3", None, "")
    assert code == "k7m3"


def test_extract_receive_code_from_text_hint() -> None:
    code = SyncService._extract_receive_code("链接 https://115.com/s/abcd1234 提取码: c3d4", None, "")
    assert code == "c3d4"


def test_extract_share_code_from_payload() -> None:
    code = SyncService._extract_share_code("https://115.com/s/zzzz9999", {"share_code": "abcd1234"})
    assert code == "abcd1234"


def test_extract_share_code_from_url() -> None:
    code = SyncService._extract_share_code("https://115.com/s/abcd1234?password=a1b2", None)
    assert code == "abcd1234"


@pytest.mark.asyncio
async def test_sync_tv_show_prefers_local_emby_index(monkeypatch) -> None:
    service = SyncService()
    actions: list[str] = []
    save_called = False

    async def fake_get_tv_status(tmdb_id: int) -> dict:
        assert tmdb_id == 94997
        return {
            "status": "ok",
            "source": "emby_sync_index",
            "existing_episodes": {(2, 1)},
        }

    async def fail_live_emby_lookup(tmdb_id: int):
        raise AssertionError("不应绕过本地 Emby 索引调用旧查询入口")

    async def fake_get_share_files(
        share_code: str,
        receive_code: str = "",
        cid: str = "0",
        visited_cids=None,
        path_prefix: str = "",
    ) -> list[dict]:
        return [
            {
                "fid": "episode-1",
                "name": "House.of.the.Dragon.S02E01.2160p.mkv",
                "size": 8_000,
            }
        ]

    async def fake_collect_existing(*, target_cid: str, show_title: str = ""):
        assert target_cid == "target-folder"
        return set()

    async def fake_save(*args, **kwargs):
        nonlocal save_called
        save_called = True
        return {"state": True}

    async def fake_log_background_event(**kwargs) -> None:
        actions.append(str(kwargs.get("action") or ""))

    monkeypatch.setattr(
        "app.services.sync_service.emby_service.get_tv_episode_status_by_tmdb",
        fake_get_tv_status,
    )
    monkeypatch.setattr(
        "app.services.sync_service.emby_service.get_downloaded_episodes",
        fail_live_emby_lookup,
    )
    monkeypatch.setattr(
        "app.services.sync_service.pan115_service.get_share_all_files_recursive",
        fake_get_share_files,
    )
    monkeypatch.setattr(
        "app.services.sync_service.pan115_service._collect_tv_existing_episodes_for_transfer",
        fake_collect_existing,
    )
    monkeypatch.setattr(
        "app.services.sync_service.pan115_service.save_share_files",
        fake_save,
    )
    monkeypatch.setattr(
        "app.services.sync_service.operation_log_service.log_background_event",
        fake_log_background_event,
    )

    result = await service.sync_tv_show(
        94997,
        "https://115.com/s/abcd1234",
        "target-folder",
        show_title="House of the Dragon (2022) S02",
    )

    assert result["success"] is True
    assert result["saved_count"] == 0
    assert save_called is False
    assert "sync.tv_show.stage.emby_lookup" in actions
    assert "sync.tv_show.stage.share_scan" in actions
    assert "sync.tv_show.stage.library_dedupe" in actions
    assert "sync.tv_show.success" in actions
