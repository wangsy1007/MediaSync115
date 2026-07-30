from app.services.media_postprocess_service import MediaPostprocessService
from app.services.strm_service import StrmService


def test_build_archive_scopes_dedupes_season_folder() -> None:
    scopes = MediaPostprocessService._build_archive_scopes(
        {
            "items": [
                {
                    "status": "success",
                    "source_fid": "a",
                    "target_cid": "season1",
                    "target_desc": "剧集/华语剧集/Show (2026)/第1季",
                    "new_filename": "Show (2026) - S01E01.mp4",
                },
                {
                    "status": "success",
                    "source_fid": "b",
                    "target_cid": "season1",
                    "target_desc": "剧集/华语剧集/Show (2026)/第1季",
                    "new_filename": "Show (2026) - S01E02.mp4",
                },
            ]
        }
    )
    assert scopes is not None
    assert len(scopes) == 1
    assert scopes[0]["target_cid"] == "season1"
    assert scopes[0]["expected_name"] == "Show (2026) - S01E01.mp4"


def test_normalize_scopes_merges_same_target() -> None:
    scopes = StrmService._normalize_scopes(
        [
            {
                "fid": "a",
                "target_cid": "season1",
                "relative_prefix": "剧集/Show/Season 01",
                "expected_name": "A.mp4",
            },
            {
                "fid": "b",
                "target_cid": "season1",
                "relative_prefix": "剧集/Show/Season 01",
                "expected_name": "B.mp4",
            },
        ]
    )
    assert len(scopes) == 1
    assert scopes[0]["expected_name"] == ""
