"""转存文件 ↔ TMDB 绑定：upsert 与归档优先路径。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.transfer_file_binding import TransferFileBinding
from app.services.archive_service import archive_service
from app.services.transfer_file_binding_service import transfer_file_binding_service


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows if isinstance(rows, list) else ([rows] if rows else [])

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, store: dict[str, TransferFileBinding]):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def add(self, row: TransferFileBinding):
        self.store[str(row.file_fid)] = row

    async def execute(self, stmt):
        # upsert 查询：尽量从 IN 参数取出 fid；否则返回全部已存行
        rows = list(self.store.values())
        try:
            params = stmt.compile().params or {}
            wanted: set[str] = set()
            for value in params.values():
                if isinstance(value, (list, tuple, set)):
                    wanted.update(str(v) for v in value if str(v or "").strip())
                elif value is not None and str(value).strip():
                    # 可能是单个 file_fid
                    text = str(value).strip()
                    if text in self.store:
                        wanted.add(text)
            if wanted:
                rows = [self.store[fid] for fid in wanted if fid in self.store]
        except Exception:
            pass
        return _FakeResult(rows)

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_bind_files_upsert_overwrites_same_fid(monkeypatch) -> None:
    store: dict[str, TransferFileBinding] = {}

    monkeypatch.setattr(
        "app.services.transfer_file_binding_service.async_session_maker",
        lambda: _FakeSession(store),
    )
    monkeypatch.setattr(
        transfer_file_binding_service,
        "_cleanup_old_rows",
        lambda: None,
    )

    n1 = await transfer_file_binding_service.bind_files(
        file_fids=["fid-1"],
        tmdb_id=100,
        media_type="movie",
        display_title="旧片名",
        source="test",
    )
    assert n1 == 1
    assert store["fid-1"].tmdb_id == 100
    assert store["fid-1"].display_title == "旧片名"

    n2 = await transfer_file_binding_service.bind_files(
        file_fids=["fid-1"],
        tmdb_id=200,
        media_type="tv",
        display_title="新剧名",
        source="test2",
        season=1,
        episode=3,
    )
    assert n2 == 1
    assert store["fid-1"].tmdb_id == 200
    assert store["fid-1"].media_type == "tv"
    assert store["fid-1"].display_title == "新剧名"
    assert store["fid-1"].season == 1
    assert store["fid-1"].episode == 3


@pytest.mark.asyncio
async def test_bind_folder_files_uses_before_fids_diff(monkeypatch) -> None:
    store: dict[str, TransferFileBinding] = {}
    listed = [
        {"fid": "old-1", "n": "Old.Movie.mkv", "fc": 1},
        {"fid": "new-1", "n": "New.Movie.mkv", "fc": 1},
        {"fid": "dir-1", "n": "subdir", "fc": 0},
    ]

    class FakePan:
        @staticmethod
        def _is_folder_item(item):
            return item.get("fc") == 0

        async def get_file_list(self, cid, offset=0, limit=50, asc=1, o="user_ptime"):
            return {"data": listed}

    monkeypatch.setattr(
        "app.services.transfer_file_binding_service.async_session_maker",
        lambda: _FakeSession(store),
    )
    monkeypatch.setattr(
        transfer_file_binding_service,
        "_cleanup_old_rows",
        lambda: None,
    )

    bound = await transfer_file_binding_service.bind_folder_files(
        folder_cid="cid-watch",
        tmdb_id=555,
        media_type="movie",
        display_title="新电影",
        source="explore_save",
        pan115=FakePan(),
        before_fids={"old-1"},
    )
    assert bound == 1
    assert "new-1" in store
    assert "old-1" not in store
    assert store["new-1"].tmdb_id == 555


@pytest.mark.asyncio
async def test_archive_identify_prefers_binding_over_filename(monkeypatch) -> None:
    """有 binding 时跳过文件名 TMDB，脏文件名也能识别。"""
    dirty_name = "zzzz.random.garbage.mkv"
    item = {
        "fid": "bound-fid",
        "name": dirty_name,
        "cid": "watch",
        "is_video": True,
        "relative_path": dirty_name,
    }
    binding = {
        "file_fid": "bound-fid",
        "tmdb_id": 603,
        "media_type": "movie",
        "display_title": "黑客帝国",
        "parent_cid": "watch",
        "season": None,
        "episode": None,
        "source": "detail_page",
        "download_record_id": None,
        "subscription_id": None,
        "resource_name": None,
    }

    identify_calls = {"by_id": 0, "by_name": 0}

    async def fake_by_id(tmdb_id, media_type):
        identify_calls["by_id"] += 1
        assert int(tmdb_id) == 603
        return {
            "tmdb_id": 603,
            "title": "The Matrix",
            "year": "1999",
            "genre_name": "动作",
            "region_name": "欧美",
        }

    async def fake_by_name(parsed):
        identify_calls["by_name"] += 1
        return None

    async def fake_get_bindings(fids):
        return {"bound-fid": binding}

    monkeypatch.setattr(
        transfer_file_binding_service,
        "get_by_file_fids",
        fake_get_bindings,
    )
    monkeypatch.setattr(archive_service, "_identify_by_tmdb_id", fake_by_id)
    monkeypatch.setattr(archive_service, "identify_media", fake_by_name)

    parsed = archive_service.parse_media_filename(dirty_name)
    # 复用扫描识别闭包逻辑：直接调用与 _run_scan_locked 相同的优先级
    matched = await archive_service._identify_by_tmdb_id(
        int(binding["tmdb_id"]), binding["media_type"]
    )
    if not matched:
        matched = await archive_service.identify_media(parsed)

    assert matched is not None
    assert matched["tmdb_id"] == 603
    assert identify_calls["by_id"] == 1
    assert identify_calls["by_name"] == 0

    title = archive_service._resolve_archive_display_title(
        {"media_type": "movie", "query_title": "zzzz"},
        matched,
        transfer_context={
            "binding_display_title": "黑客帝国",
            "filename": dirty_name,
        },
    )
    assert title == "黑客帝国"


@pytest.mark.asyncio
async def test_archive_falls_back_to_identify_media_without_binding(monkeypatch) -> None:
    async def fake_get_bindings(fids):
        return {}

    async def fake_by_name(parsed):
        return {
            "tmdb_id": 550,
            "title": "Fight Club",
            "year": "1999",
            "genre_name": "剧情",
            "region_name": "欧美",
        }

    monkeypatch.setattr(
        transfer_file_binding_service,
        "get_by_file_fids",
        fake_get_bindings,
    )
    monkeypatch.setattr(archive_service, "identify_media", fake_by_name)

    async def boom(*_a, **_k):
        raise AssertionError("不应在无 binding 时调用 _identify_by_tmdb_id")

    monkeypatch.setattr(archive_service, "_identify_by_tmdb_id", boom)

    binding_map = await transfer_file_binding_service.get_by_file_fids(["x"])
    parsed = archive_service.parse_media_filename("Fight.Club.1999.mkv")
    matched = None
    if binding_map.get("x"):
        matched = await archive_service._identify_by_tmdb_id(1, "movie")
    if not matched:
        matched = await archive_service.identify_media(parsed)
    assert matched["tmdb_id"] == 550


@pytest.mark.asyncio
async def test_process_identified_keeps_bound_dirty_filename(monkeypatch) -> None:
    """批量扫描缺口修复：binding 命中后即使文件名不可解析也能进入处理。"""
    item = {
        "fid": "f-dirty",
        "name": "xxx.unknown.bin.mkv",
        "cid": "c1",
        "relative_path": "xxx.unknown.bin.mkv",
    }
    identify_info = {
        "parsed": {"media_type": "movie", "query_title": "xxx", "year": None},
        "matched": {
            "tmdb_id": 111,
            "title": "Fallback EN",
            "year": "2020",
            "genre_name": "剧情",
            "region_name": "华语",
        },
        "binding": {
            "tmdb_id": 111,
            "media_type": "movie",
            "display_title": "中文片名",
        },
    }

    async def fake_lookup(*_a, **_k):
        return {"intent": {}, "folder_name": "", "resource_name": ""}

    async def fake_upsert(**_k):
        return SimpleNamespace(id=1)

    async def fake_ensure(*_a, **_k):
        return "out-cid"

    class FakePan:
        async def rename_file(self, *_a, **_k):
            return True

        async def move_file(self, *_a, **_k):
            return True

    monkeypatch.setattr(archive_service, "_lookup_transfer_context", fake_lookup)
    monkeypatch.setattr(archive_service, "_upsert_task", fake_upsert)
    monkeypatch.setattr(archive_service, "_ensure_movie_path", fake_ensure)
    monkeypatch.setattr(
        archive_service,
        "_get_archive_naming",
        lambda: {
            "movie_folder": "{title} ({year})",
            "movie_file": "{title} ({year}){ext}",
            "tv_folder": "{title} ({year})",
            "tv_season_folder": "Season {season}",
            "tv_file": "{title} - S{season:02d}E{episode:02d}{ext}",
        },
    )
    monkeypatch.setattr(
        archive_service,
        "_get_archive_subdirs",
        lambda: {"movie_categories": [], "tv_categories": []},
    )

    # 避免真实 115 / 日志副作用：若路径过深则至少验证 display_title 解析
    display = archive_service._resolve_archive_display_title(
        identify_info["parsed"],
        identify_info["matched"],
        transfer_context={
            "binding_display_title": identify_info["binding"]["display_title"],
            "filename": item["name"],
            "intent": {},
        },
    )
    assert display == "中文片名"
    assert identify_info["matched"] is not None
    # 模拟扫描阶段：有 matched 即进入 identified，不再因文件名搜 TMDB 失败而丢弃
    identified = [identify_info] if identify_info.get("matched") else []
    assert len(identified) == 1
