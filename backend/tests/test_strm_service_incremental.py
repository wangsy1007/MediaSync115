import asyncio
import json
import os
from unittest.mock import AsyncMock

import pytest

from app.models.strm_index import StrmFileIndex, StrmFolderIndex
from app.services.runtime_settings_service import runtime_settings_service
from app.services.strm_service import StrmService


class _FakePan:
    @staticmethod
    def _is_folder_item(item: dict) -> bool:
        return item.get("ico") == "folder"

    @staticmethod
    def _extract_folder_id(item: dict) -> str:
        return str(item.get("fid") or "")


class _DeepTreePan(_FakePan):
    def __init__(self, depth: int = 8) -> None:
        self.depth = depth

    async def get_file_list(
        self, cid: str, offset: int = 0, limit: int = 200
    ) -> dict:
        if cid == "root":
            items = [{"fid": "d1", "n": "d1", "ico": "folder"}]
        elif cid.startswith("d") and int(cid[1:]) < self.depth:
            level = int(cid[1:]) + 1
            items = [{"fid": f"d{level}", "n": f"d{level}", "ico": "folder"}]
        else:
            items = [{"fid": "video", "n": "movie.mkv", "pc": "pick-code"}]
        return {"data": items[offset : offset + limit], "count": len(items)}


def _indexed(fid: str, path: str, parent_cid: str = "") -> StrmFileIndex:
    return StrmFileIndex(
        output_cid="root",
        fid=fid,
        pick_code=f"pc-{fid}",
        relative_path=path,
        parent_cid=parent_cid,
        content_hash="hash",
        config_fingerprint="config",
    )


def test_snapshot_hash_is_sorted_and_ignores_folder_utime() -> None:
    pan = _FakePan()
    first = [
        {"fid": "2", "n": "B", "ico": "folder", "utime": "1"},
        {"fid": "1", "n": "A.mkv", "pc": "pc1", "sha1": "sha", "utime": "1"},
    ]
    second = [
        {"fid": "1", "n": "A.mkv", "pc": "pc1", "sha1": "sha", "utime": "9"},
        {"fid": "2", "n": "B", "ico": "folder", "utime": "999"},
    ]

    assert StrmService._snapshot_hash(first, pan) == StrmService._snapshot_hash(
        second, pan
    )


def test_scoped_reconcile_only_removes_complete_prefix() -> None:
    existing = [
        _indexed("a", "Movies/A.mkv"),
        _indexed("b", "Movies/B.mkv"),
        _indexed("c", "Shows/C.mkv"),
    ]

    stale = StrmService._select_stale_fids(
        existing_files=existing,
        scanned_fids={"a"},
        complete_prefixes=["Movies"],
        exact_fids=set(),
        parent_cids=set(),
    )

    assert stale == {"b"}


def test_fid_reconcile_detects_move_without_deleting_other_files() -> None:
    existing = [_indexed("a", "Old/A.mkv"), _indexed("b", "Keep/B.mkv")]

    stale = StrmService._select_stale_fids(
        existing_files=existing,
        scanned_fids={"a"},
        complete_prefixes=[],
        exact_fids={"a"},
        parent_cids=set(),
    )

    assert stale == set()
    assert StrmService._record_content_hash(
        {"pick_code": "pc-a", "relative_path": "Old/A.mkv", "sha1": ""}
    ) != StrmService._record_content_hash(
        {"pick_code": "pc-a", "relative_path": "New/A.mkv", "sha1": ""}
    )


def test_scope_normalization_deduplicates_and_rejects_empty_entries() -> None:
    scopes = StrmService._normalize_scopes(
        [
            {"fid": " 1 ", "target_cid": "2", "relative_prefix": "/Movies/Test/"},
            {"fid": "1", "target_cid": "2", "relative_prefix": "Movies/Test"},
            {"relative_prefix": "ignored"},
        ]
    )

    assert scopes == [
        {"fid": "1", "target_cid": "2", "relative_prefix": "Movies/Test"}
    ]


def test_scope_normalization_accepts_archive_source_fid_alias() -> None:
    assert StrmService._normalize_scopes(
        [{"source_fid": "1", "target_cid": "2", "relative_prefix": "TV/Test"}]
    ) == [{"fid": "1", "target_cid": "2", "relative_prefix": "TV/Test"}]


def test_manifest_rejects_wrong_owner_and_unsafe_paths(tmp_path) -> None:
    manifest = tmp_path / ".mediasync115-strm-manifest.json"
    manifest.write_text(
        '{"output_cid":"other","generated_files":["safe.strm","../escape.strm"]}',
        encoding="utf-8",
    )
    assert StrmService._load_manifest_files(
        manifest, expected_output_cid="current"
    ) == set()

    manifest.write_text(
        '{"output_cid":"current","generated_files":["safe.strm","../escape.strm"]}',
        encoding="utf-8",
    )
    assert StrmService._load_manifest_files(
        manifest, expected_output_cid="current"
    ) == {"safe.strm"}


def test_config_fingerprint_changes_with_output_dir(monkeypatch) -> None:
    service = StrmService()
    monkeypatch.setattr(
        runtime_settings_service, "get_strm_base_url", lambda: "http://localhost:9008"
    )
    monkeypatch.setattr(
        runtime_settings_service, "get_strm_proxy_enabled", lambda: False
    )
    monkeypatch.setattr(
        runtime_settings_service, "get_strm_proxy_port", lambda: 8099
    )
    monkeypatch.setattr(service, "_get_token_secret", lambda: "secret")
    monkeypatch.setattr(
        runtime_settings_service, "get_strm_output_dir", lambda: "/tmp/strm-a"
    )
    first = service._config_fingerprint()
    monkeypatch.setattr(
        runtime_settings_service, "get_strm_output_dir", lambda: "/tmp/strm-b"
    )
    assert service._config_fingerprint() != first


@pytest.mark.asyncio
async def test_scan_tree_does_not_deadlock_when_depth_exceeds_concurrency() -> None:
    service = StrmService()

    files, folders = await asyncio.wait_for(
        service._scan_tree(_DeepTreePan(depth=8), "root", "", ""),
        timeout=1,
    )

    assert [item["fid"] for item in files] == ["video"]
    assert len(folders) == 9


@pytest.mark.asyncio
async def test_cancelled_generate_marks_persistent_state_failed(
    monkeypatch, tmp_path
) -> None:
    service = StrmService()
    entered = asyncio.Event()

    async def _blocked_generate(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_generate", _blocked_generate)
    mark_failed = AsyncMock()
    log_step = AsyncMock()
    monkeypatch.setattr(service, "_mark_state_failed", mark_failed)
    monkeypatch.setattr(service, "_log_strm_step", log_step)

    task = asyncio.create_task(
        service._run_generate_task(
            trigger="scheduler",
            output_cid="root",
            output_dir=tmp_path,
            mode="incremental",
            scopes=[],
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    mark_failed.assert_awaited_once()
    assert "取消或执行超时" in str(mark_failed.await_args.kwargs["error"])
    assert service._last_generate_finished_at
    assert "取消或执行超时" in service._last_generate_error


@pytest.mark.asyncio
async def test_cancel_generate_stops_running_incremental(monkeypatch, tmp_path) -> None:
    service = StrmService()
    entered = asyncio.Event()

    async def _blocked_generate(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_generate", _blocked_generate)
    monkeypatch.setattr(service, "_mark_state_failed", AsyncMock())
    monkeypatch.setattr(service, "_log_strm_step", AsyncMock())
    monkeypatch.setattr(service, "reconcile_stale_running_state", AsyncMock(return_value=False))
    monkeypatch.setattr(
        service,
        "get_runtime_status_async",
        AsyncMock(return_value={"generate_running": False}),
    )
    monkeypatch.setattr(
        runtime_settings_service, "get_archive_output_cid", lambda: "root"
    )
    monkeypatch.setattr(
        runtime_settings_service, "get_strm_output_dir", lambda: str(tmp_path)
    )

    task = asyncio.create_task(
        service._run_generate_task(
            trigger="manual",
            output_cid="root",
            output_dir=tmp_path,
            mode="incremental",
            scopes=[],
        )
    )
    service._generate_task = task
    await entered.wait()

    result = await service.cancel_generate()

    assert result["cancelled"] is True
    assert result["running"] is False
    assert "停止" in result["message"]
    assert service._pending_mode is None
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "手动停止" in service._last_generate_error


def test_write_text_atomic_creates_nested_file(tmp_path) -> None:
    target = tmp_path / "剧集" / "示例 (2026)" / "第1季" / "示例 (2026) - S01E02.strm"
    StrmService._write_text_atomic(target, "http://example/play\n")
    assert target.read_text(encoding="utf-8") == "http://example/play\n"
    assert list(tmp_path.rglob("*.tmp")) == []


def test_write_text_atomic_retries_transient_enoent(tmp_path, monkeypatch) -> None:
    target = tmp_path / "Movies" / "A.strm"
    calls = {"n": 0}
    real_replace = os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FileNotFoundError(2, "No such file or directory", str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(
        "app.services.strm_service.os.replace", flaky_replace
    )
    monkeypatch.setattr("app.services.strm_service.time.sleep", lambda *_: None)

    StrmService._write_text_atomic(target, "url\n")
    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8") == "url\n"


@pytest.mark.asyncio
async def test_flush_strm_writes_deduplicates_same_path(tmp_path) -> None:
    service = StrmService()
    target = tmp_path / "A.strm"
    pending = [
        (target, "old\n"),
        (target, "new\n"),
    ]
    written, errors = await service._flush_strm_writes({tmp_path}, pending)
    assert written == 1
    assert errors == []
    assert pending == []
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_flush_strm_writes_continues_after_single_failure(
    tmp_path, monkeypatch
) -> None:
    service = StrmService()
    ok_path = tmp_path / "ok.strm"
    bad_path = tmp_path / "bad.strm"
    real_atomic = StrmService._write_text_atomic

    def flaky_atomic(path, content):
        if path == bad_path:
            raise OSError("boom")
        return real_atomic(path, content)

    monkeypatch.setattr(StrmService, "_write_text_atomic", staticmethod(flaky_atomic))
    written, errors = await service._flush_strm_writes(
        {tmp_path},
        [(bad_path, "x\n"), (ok_path, "y\n")],
    )
    assert written == 1
    assert len(errors) == 1
    assert ok_path.read_text(encoding="utf-8") == "y\n"
    assert not bad_path.exists()


@pytest.mark.asyncio
async def test_collect_missing_local_records_detects_deleted_strm(tmp_path) -> None:
    service = StrmService()
    existing = [
        _indexed("keep", "Movies/Keep.mkv"),
        _indexed("gone", "Movies/Gone.mkv"),
    ]
    keep_strm = tmp_path.joinpath("Movies", "Keep.strm")
    keep_strm.parent.mkdir(parents=True, exist_ok=True)
    keep_strm.write_text("url\n", encoding="utf-8")

    missing = await service._collect_missing_local_records(
        output_dir=tmp_path,
        existing_files=existing,
        already_scanned_fids=set(),
    )
    assert [item["fid"] for item in missing] == ["gone"]


@pytest.mark.asyncio
async def test_scan_tree_reuses_list_cache_without_extra_api_calls() -> None:
    service = StrmService()
    calls = {"count": 0}

    class _CountingPan(_FakePan):
        async def get_file_list(
            self, cid: str, offset: int = 0, limit: int = 200
        ) -> dict:
            calls["count"] += 1
            if cid == "root":
                items = [{"fid": "d1", "n": "d1", "ico": "folder"}]
            else:
                items = [{"fid": "video", "n": "movie.mkv", "pc": "pick"}]
            return {"data": items[offset : offset + limit], "count": len(items)}

    pan = _CountingPan()
    list_cache: dict[str, list] = {}
    files1, folders1 = await service._scan_tree(
        pan, "root", "", "", list_cache=list_cache
    )
    first_calls = calls["count"]
    assert first_calls >= 2
    assert [item["fid"] for item in files1] == ["video"]
    assert "root" in list_cache and "d1" in list_cache

    files2, folders2 = await service._scan_tree(
        pan, "root", "", "", list_cache=list_cache
    )
    assert calls["count"] == first_calls
    assert [item["fid"] for item in files2] == ["video"]
    assert len(folders2) == len(folders1)


@pytest.mark.asyncio
async def test_folder_tree_changed_checks_siblings_in_parallel() -> None:
    service = StrmService()
    in_flight = 0
    max_in_flight = 0
    gate = asyncio.Event()
    started = 0

    class _WidePan(_FakePan):
        async def get_file_list(
            self, cid: str, offset: int = 0, limit: int = 200
        ) -> dict:
            nonlocal in_flight, max_in_flight, started
            if cid == "root":
                items = [
                    {"fid": "a", "n": "a", "ico": "folder"},
                    {"fid": "b", "n": "b", "ico": "folder"},
                    {"fid": "c", "n": "c", "ico": "folder"},
                ]
            else:
                items = [{"fid": f"{cid}-v", "n": f"{cid}.mkv", "pc": f"pc-{cid}"}]
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                started += 1
                if started >= 3:
                    gate.set()
                await gate.wait()
                in_flight -= 1
            return {"data": items[offset : offset + limit], "count": len(items)}

    indexed = {
        "root": StrmFolderIndex(
            output_cid="out",
            fid="root",
            relative_path="",
            parent_cid="",
            snapshot_hash=service._snapshot_hash(
                [
                    {"fid": "a", "n": "a", "ico": "folder"},
                    {"fid": "b", "n": "b", "ico": "folder"},
                    {"fid": "c", "n": "c", "ico": "folder"},
                ],
                _WidePan(),
            ),
        ),
        "a": StrmFolderIndex(
            output_cid="out",
            fid="a",
            relative_path="a",
            parent_cid="root",
            snapshot_hash="stale",
        ),
        "b": StrmFolderIndex(
            output_cid="out",
            fid="b",
            relative_path="b",
            parent_cid="root",
            snapshot_hash="stale",
        ),
        "c": StrmFolderIndex(
            output_cid="out",
            fid="c",
            relative_path="c",
            parent_cid="root",
            snapshot_hash="stale",
        ),
    }
    # root hash will match after listing; children are stale → changed
    list_cache: dict[str, list] = {}
    changed = await asyncio.wait_for(
        service._folder_tree_changed(_WidePan(), "root", indexed, list_cache),
        timeout=2,
    )
    assert changed is True
    assert max_in_flight >= 2


def test_save_manifest_always_writes_index_file(tmp_path) -> None:
    manifest = tmp_path / ".mediasync115-strm-manifest.json"
    StrmService._save_manifest(
        manifest,
        {"Movies/A.strm", "TV/B.strm"},
        output_cid="cid-1",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["output_cid"] == "cid-1"
    assert payload["generated_files"] == ["Movies/A.strm", "TV/B.strm"]
