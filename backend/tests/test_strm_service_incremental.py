from app.models.strm_index import StrmFileIndex
from app.services.strm_service import StrmService


class _FakePan:
    @staticmethod
    def _is_folder_item(item: dict) -> bool:
        return item.get("ico") == "folder"

    @staticmethod
    def _extract_folder_id(item: dict) -> str:
        return str(item.get("fid") or "")


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
