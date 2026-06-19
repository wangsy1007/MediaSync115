import pytest

from app.services import pan115_service as pan115_module
from app.services.pan115_service import Pan115Service


class TestPan115ShareSnapFallback:
    """分享目录 snap 接口多路回退测试"""

    @pytest.mark.asyncio
    async def test_get_share_file_list_tries_proapi_before_webapi_get(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = Pan115Service(cookie="test-cookie")
        calls: list[str] = []

        async def fake_fetch(payload: dict, *, mode: str):
            calls.append(mode)
            if mode == "webapi_get":
                raise RuntimeError("code=405 method='GET' Method Not Allowed")
            return {"list": [{"fid": "1", "n": "demo.mkv"}]}

        monkeypatch.setattr(service, "_fetch_share_snap_raw", fake_fetch)

        result = await service.get_share_file_list(
            "sww4ua436dh", receive_code="xd19", cid="0", offset=0, limit=100
        )

        assert calls[0] == "proapi"
        assert "webapi_get" not in calls or calls.index("proapi") < calls.index(
            "webapi_get"
        ) if "webapi_get" in calls else True
        assert result["list"][0]["fid"] == "1"

    @pytest.mark.asyncio
    async def test_get_share_file_list_falls_back_to_webapi_post_on_405(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = Pan115Service(cookie="test-cookie")

        async def fake_fetch(payload: dict, *, mode: str):
            if mode == "proapi":
                raise RuntimeError("code=405 method='GET'")
            if mode == "webapi_post":
                return {"list": [{"fid": "2", "n": "ok.mkv"}]}
            raise AssertionError(f"unexpected mode {mode}")

        monkeypatch.setattr(service, "_fetch_share_snap_raw", fake_fetch)

        result = await service.get_share_file_list("code", receive_code="pwd")

        assert result["list"][0]["fid"] == "2"

    def test_is_method_not_allowed_error_matches_115_message(self) -> None:
        text = (
            "code=405 method='GET' "
            "message='Specified method is invalid for this resource'"
        )
        assert Pan115Service._is_method_not_allowed_error(text) is True

    @pytest.mark.asyncio
    async def test_get_share_all_files_recursive_descends_nested_folders_with_fid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = Pan115Service(cookie="test-cookie")

        async def fake_get_share_file_list(
            share_code: str,
            receive_code: str = "",
            cid: str = "0",
            offset: int = 0,
            limit: int = 50,
        ):
            if cid == "0":
                return {
                    "list": [
                        {"fid": "folder-fid", "cid": "100", "n": "顶层目录", "s": 0, "is_dir": 1}
                    ]
                }
            if cid == "100":
                return {
                    "list": [
                        {"fid": "sub-folder-fid", "cid": "200", "n": "二级目录", "s": 0, "is_dir": 1}
                    ]
                }
            if cid == "200":
                return {"list": [{"fid": "video-1", "n": "Episode.S01E01.mkv", "s": 1024}]}
            return {"list": []}

        monkeypatch.setattr(service, "get_share_file_list", fake_get_share_file_list)

        result = await service.get_share_all_files_recursive("share-code", "pwd")

        assert result == [{"fid": "video-1", "name": "Episode.S01E01.mkv", "size": 1024}]
