import pytest

from app.services.pan115_service import Pan115Service


class DummyClient:
    calls: list[tuple[str, tuple]] = []

    def fs_rename(self, payload, /, *, async_=False, **kwargs):
        self.__class__.calls.append(("fs_rename", payload))
        return {"state": True, "data": {}}

    def fs_rename_app(self, payload, /, *, async_=False, **kwargs):
        self.__class__.calls.append(("fs_rename_app", payload))
        return {"state": True, "data": {}}


@pytest.mark.asyncio
async def test_rename_file_uses_tuple_payload(monkeypatch) -> None:
    DummyClient.calls = []
    service = Pan115Service("dummy-cookie")
    service._client = DummyClient()

    async def fake_async_call(method_name, *args, **kwargs):
        method = getattr(service._client, method_name)
        return method(*args, async_=True, **kwargs)

    monkeypatch.setattr(service, "_async_call", fake_async_call)

    await service.rename_file("abc123", "黑客帝国 (1999).mkv")

    assert DummyClient.calls == [("fs_rename", ("abc123", "黑客帝国 (1999).mkv"))]
