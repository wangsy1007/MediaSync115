import pytest

from app.services.transfer_intent_service import (
    contains_cjk,
    extract_chinese_title_from_text,
    intent_matches_file,
    normalize_transfer_display_title,
    pick_preferred_chinese_title,
    transfer_intent_service,
)


class TestTransferIntentHelpers:
    def test_normalize_transfer_display_title_strips_year(self) -> None:
        assert normalize_transfer_display_title("浪浪山小妖怪 (2025)") == "浪浪山小妖怪"

    def test_extract_chinese_title_from_release_name(self) -> None:
        title = extract_chinese_title_from_text(
            "浪浪山小妖怪.2025.2160p.WEB-DL.H265.mkv"
        )
        assert title == "浪浪山小妖怪"

    def test_pick_preferred_chinese_title(self) -> None:
        assert (
            pick_preferred_chinese_title("The Monkey King", "浪浪山小妖怪")
            == "浪浪山小妖怪"
        )

    def test_contains_cjk(self) -> None:
        assert contains_cjk("浪浪山")
        assert not contains_cjk("Monkey King")


class TestIntentMatchesFile:
    def test_matches_by_tmdb_id(self) -> None:
        intent = {"display_title": "野狗骨头", "tmdb_id": 291392}
        assert intent_matches_file(
            intent,
            filename="百花杀.2026.S01E01.mkv",
            tmdb_id=291392,
        )

    def test_rejects_cross_show_by_filename(self) -> None:
        intent = {"display_title": "野狗骨头", "tmdb_id": 291392}
        assert not intent_matches_file(
            intent,
            filename="百花杀.2026.S01E01.mkv",
        )

    def test_matches_by_filename_title(self) -> None:
        intent = {
            "display_title": "百花杀",
            "resource_name": "📺 电视剧：百花杀 (2026) 更新至8集 4K",
        }
        assert intent_matches_file(
            intent,
            filename="百花杀.2026.S01E08.2160p.mp4",
        )


@pytest.mark.asyncio
async def test_register_and_find_by_folder(monkeypatch) -> None:
    stored: list[dict] = []

    class FakeIntent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

        def scalars(self):
            return self

        def all(self):
            return [self._row] if self._row else []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def add(self, row):
            stored.append(row.__dict__)

        async def execute(self, stmt):
            if stored:
                latest = FakeIntent(**stored[-1])
                return FakeResult(latest)
            return FakeResult(None)

        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.transfer_intent_service.async_session_maker",
        lambda: FakeSession(),
    )
    monkeypatch.setattr(
        transfer_intent_service,
        "_cleanup_old_rows",
        lambda: None,
    )

    await transfer_intent_service.register_intent(
        display_title="浪浪山小妖怪 (2025)",
        tmdb_id=12345,
        media_type="movie",
        target_folder_id="folder-abc",
        source="test",
    )
    matched = await transfer_intent_service.find_best_match(
        parent_cid="folder-abc",
        media_type="movie",
        filename="浪浪山小妖怪.2025.2160p.mkv",
    )
    assert matched is not None
    assert matched["display_title"] == "浪浪山小妖怪"
    assert matched["tmdb_id"] == 12345


@pytest.mark.asyncio
async def test_find_best_match_avoids_latest_wrong_show_in_shared_parent(
    monkeypatch,
) -> None:
    rows = [
        {
            "display_title": "野狗骨头",
            "tmdb_id": 291392,
            "douban_id": None,
            "media_type": "tv",
            "target_folder_id": None,
            "target_parent_id": "watch-folder",
            "resource_name": "📺 电视剧：野狗骨头 (2026) 更新至15集 4K",
            "source": "subscription",
        },
        {
            "display_title": "百花杀",
            "tmdb_id": 286506,
            "douban_id": None,
            "media_type": "tv",
            "target_folder_id": None,
            "target_parent_id": "watch-folder",
            "resource_name": "📺 电视剧：百花杀 (2026) 更新至8集 4K",
            "source": "subscription",
        },
    ]

    class FakeIntent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        def __init__(self, items):
            self._items = items

        def scalar_one_or_none(self):
            return self._items[0] if len(self._items) == 1 else None

        def scalars(self):
            return self

        def all(self):
            return [FakeIntent(**item) for item in self._items]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            sql = str(stmt)
            if "target_folder_id" in sql and "==" in sql:
                return FakeResult([])
            if "tmdb_id" in sql:
                return FakeResult(rows)
            if "target_parent_id" in sql:
                return FakeResult(rows)
            return FakeResult([])

        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.transfer_intent_service.async_session_maker",
        lambda: FakeSession(),
    )

    matched = await transfer_intent_service.find_best_match(
        parent_cid="watch-folder",
        media_type="tv",
        filename="百花杀.2026.S01E08.2160p.mp4",
        tmdb_id=286506,
    )
    assert matched is not None
    assert matched["display_title"] == "百花杀"
    assert matched["tmdb_id"] == 286506
