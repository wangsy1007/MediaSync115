import pytest

from app.services.transfer_intent_service import (
    contains_cjk,
    extract_chinese_title_from_text,
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
    )
    assert matched is not None
    assert matched["display_title"] == "浪浪山小妖怪"
    assert matched["tmdb_id"] == 12345
