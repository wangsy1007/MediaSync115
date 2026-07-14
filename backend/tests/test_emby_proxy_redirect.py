from pathlib import Path

import pytest
from fastapi import HTTPException

import app.api.emby_proxy as emby_proxy_module
from app.api.emby_proxy import (
    _map_emby_strm_path,
    _pick_media_source,
    _should_skip_stream_redirect,
    build_emby_style_direct_stream_url,
    resolve_local_strm_play_url,
    resolve_source_container,
    resolve_stream_redirect_url,
    rewrite_playback_info_for_strm,
)


class TestEmbyStreamRedirect:
    def test_map_emby_strm_path(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            emby_proxy_module.runtime_settings_service,
            "get_strm_output_dir",
            lambda: str(tmp_path),
        )
        target = tmp_path / "电影" / "a.strm"
        target.parent.mkdir(parents=True)
        target.write_text("http://example/play\n", encoding="utf-8")

        mapped = _map_emby_strm_path("/media/strm/电影/a.strm")
        assert mapped == target.resolve()
        assert resolve_local_strm_play_url("/media/strm/电影/a.strm") == (
            "http://example/play"
        )

    def test_pick_media_source_by_id(self) -> None:
        item = {
            "MediaSources": [
                {"Id": "mediasource_1", "Path": "http://a"},
                {"Id": "mediasource_95", "Path": "http://b/api/strm/play/token"},
            ]
        }
        selected = _pick_media_source(item, "mediasource_95")
        assert selected is not None
        assert selected["Path"].endswith("/token")

    @pytest.mark.asyncio
    async def test_resolve_uses_mediasource_http_path(self, monkeypatch) -> None:
        async def fake_fetch(item_id: str):
            assert item_id == "95"
            return {
                "Path": "/media/strm/x.strm",
                "MediaSources": [
                    {
                        "Id": "mediasource_95",
                        "Path": "http://172.16.100.2:8099/api/115/url/video.mkv?pickcode=abc",
                        "Protocol": "Http",
                    }
                ],
            }

        monkeypatch.setattr(emby_proxy_module, "_fetch_emby_item", fake_fetch)
        url = await resolve_stream_redirect_url("95", media_source_id="mediasource_95")
        assert url.endswith("pickcode=abc")

    @pytest.mark.asyncio
    async def test_resolve_non_strm_returns_empty(self, monkeypatch) -> None:
        async def fake_fetch(item_id: str):
            return {
                "Path": "/media/local/movie.mkv",
                "MediaSources": [
                    {"Id": "1", "Path": "/media/local/movie.mkv", "Protocol": "File"}
                ],
            }

        monkeypatch.setattr(emby_proxy_module, "_fetch_emby_item", fake_fetch)
        url = await resolve_stream_redirect_url("1")
        assert url == ""

    def test_build_emby_style_direct_stream_url_qmediasync(self) -> None:
        url = build_emby_style_direct_stream_url(
            item_id="12",
            media_source_id="mediasource_12",
            container="iso",
            extra_query={"api_key": "k1"},
        )
        assert url.startswith("/Videos/12/stream?")
        assert "stream.iso" not in url
        assert "MediaSourceId=mediasource_12" in url
        assert "Static=true" in url

    def test_rewrite_playback_info_forces_direct_play(self) -> None:
        payload = {
            "MediaSources": [
                {
                    "Id": "mediasource_11",
                    "Path": "http://172.16.100.2:8099/api/115/url/video.mkv?pickcode=abc",
                    "SupportsDirectPlay": False,
                    "SupportsDirectStream": False,
                    "SupportsTranscoding": True,
                    "DirectStreamUrl": (
                        "/videos/11/stream?api_key=k1&TranscodeReasons=ContainerBitrateExceedsLimit"
                    ),
                    "TranscodingUrl": "/videos/11/stream?x=1",
                }
            ]
        }
        assert rewrite_playback_info_for_strm(payload, item_id="11") is True
        ms = payload["MediaSources"][0]
        assert ms["SupportsDirectPlay"] is True
        assert ms["SupportsDirectStream"] is True
        assert ms["SupportsTranscoding"] is False
        assert ms["DirectStreamUrl"].startswith("/Videos/11/stream?")
        assert "MediaSourceId=mediasource_11" in ms["DirectStreamUrl"]
        assert "Static=true" in ms["DirectStreamUrl"]
        assert "api_key=k1" in ms["DirectStreamUrl"]
        assert ms["TranscodingUrl"] is None
        assert "stream.iso" not in ms["DirectStreamUrl"]

    def test_rewrite_playback_info_sets_iso_container_without_url_suffix(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            emby_proxy_module,
            "extract_filename_from_play_token",
            lambda _url: "115Zootopia.22025RepackUSAsGnbCHDBits.iso",
        )
        payload = {
            "MediaSources": [
                {
                    "Id": "mediasource_12",
                    "Path": "http://172.16.100.2:8099/api/115/url/video.iso?pickcode=abc",
                    "Container": "mkv",
                    "SupportsDirectPlay": False,
                    "SupportsTranscoding": True,
                }
            ]
        }
        assert rewrite_playback_info_for_strm(payload, item_id="12") is True
        ms = payload["MediaSources"][0]
        assert ms["Container"] == "iso"
        assert ms["SupportsDirectPlay"] is True
        assert ms["SupportsTranscoding"] is False
        assert ms["DirectStreamUrl"].startswith("/Videos/12/stream?")
        assert "stream.iso" not in ms["DirectStreamUrl"]

    def test_resolve_source_container_prefers_real_filename(self) -> None:
        assert (
            resolve_source_container(
                {"Container": "mkv"},
                resolved_filename="Movie.2160p.mkv",
            )
            == "mkv"
        )
        assert (
            resolve_source_container(
                {"Container": "mkv"},
                resolved_filename="115Zootopia.22025Repack.iso",
            )
            == "iso"
        )

    @pytest.mark.asyncio
    async def test_get_final_redirect_link_appends_force(self, monkeypatch) -> None:
        seen = {}

        class FakeResponse:
            status_code = 200
            url = "https://cdn.115.com/movie.iso"

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def head(self, url, headers=None):
                seen["url"] = url
                seen["headers"] = headers
                return FakeResponse()

        monkeypatch.setattr(emby_proxy_module.httpx, "AsyncClient", FakeClient)
        emby_proxy_module._final_link_cache.clear()
        final = await emby_proxy_module.get_final_redirect_link(
            "http://172.16.100.2:8099/api/115/url/video.iso?pickcode=abc",
            {"User-Agent": "HosPlayer/1.0"},
        )
        assert final == "https://cdn.115.com/movie.iso"
        assert "force=1" in seen["url"]

    @pytest.mark.asyncio
    async def test_get_final_redirect_link_binds_player_ua(self, monkeypatch) -> None:
        """申请 115 直链时必须带播放器真实 UA（否则 f=1 绑定错 UA 被限速）。"""
        seen = {}

        class FakeResponse:
            status_code = 200
            url = "https://cdn.115.com/movie.iso"

        class FakeClient:
            def __init__(self, *args, **kwargs):
                seen["trust_env"] = kwargs.get("trust_env")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def head(self, url, headers=None):
                seen["headers"] = headers or {}
                return FakeResponse()

        monkeypatch.setattr(emby_proxy_module.httpx, "AsyncClient", FakeClient)
        emby_proxy_module._final_link_cache.clear()
        # 显式 player_ua 优先，且透传 header 中大小写混合也应被覆盖为该 UA
        await emby_proxy_module.get_final_redirect_link(
            "http://172.16.100.2:8099/api/115/url/video.iso?pickcode=abc",
            {"user-agent": "python-httpx/0.27", "Range": "bytes=0-1"},
            player_ua="HosPlayer/0.10.3",
        )
        assert seen["headers"].get("User-Agent") == "HosPlayer/0.10.3"
        assert seen["headers"].get("Range") == "bytes=0-1"
        assert seen["trust_env"] is False

    @pytest.mark.asyncio
    async def test_final_link_cache_not_shared_across_ua(self, monkeypatch) -> None:
        """不同播放器 UA 绑定不同直链，缓存不得串用。"""
        calls = {"n": 0}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def head(self, url, headers=None):
                calls["n"] += 1
                ua = (headers or {}).get("User-Agent", "")

                class _Resp:
                    status_code = 200
                    # 直链按 UA 区分，模拟 115 为不同 UA 下发不同绑定直链
                    url = f"https://cdn.115.com/movie.iso?ua={ua}"

                return _Resp()

        monkeypatch.setattr(emby_proxy_module.httpx, "AsyncClient", FakeClient)
        emby_proxy_module._final_link_cache.clear()
        origin = "http://172.16.100.2:8099/api/115/url/video.iso?pickcode=abc"

        first = await emby_proxy_module.get_final_redirect_link(
            origin, {}, player_ua="HosPlayer/0.10.3"
        )
        second = await emby_proxy_module.get_final_redirect_link(
            origin, {}, player_ua="Infuse/7.0"
        )
        # 同一 UA 第二次命中缓存，不再发起请求
        first_again = await emby_proxy_module.get_final_redirect_link(
            origin, {}, player_ua="HosPlayer/0.10.3"
        )
        assert first != second
        assert first == first_again
        assert calls["n"] == 2  # 两个不同 UA 各一次，重复 UA 命中缓存

    def test_no_ua_skips_stream_redirect_by_default(self) -> None:
        assert _should_skip_stream_redirect("HosPlayer/0.10.3") is False
        assert _should_skip_stream_redirect("Infuse/7.0") is False
        assert _should_skip_stream_redirect("") is False

    @pytest.mark.asyncio
    async def test_endpoint_307_to_cdn(self, monkeypatch) -> None:
        # 非 ISO（mkv）走通用直跳 CDN 路径
        async def fake_context(item_id: str, *, media_source_id=None):
            return {
                "play_url": "http://172.16.100.2:8099/api/115/url/video.mkv?pickcode=abc",
                "item_id": item_id,
                "title": "Test MKV",
                "media_type": "Movie",
                "series_name": "",
                "container": "mkv",
            }

        async def fake_final(play_url: str, headers=None, *, player_ua=""):
            return "https://cdn.115.com/movie.mkv"

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            fake_context,
        )
        monkeypatch.setattr(
            emby_proxy_module,
            "get_final_redirect_link",
            fake_final,
        )
        from fastapi import Request

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/emby/stream-redirect/12",
            "raw_path": b"/api/emby/stream-redirect/12",
            "query_string": b"MediaSourceId=mediasource_12",
            "headers": [(b"user-agent", b"HosPlayer/1.0"), (b"range", b"bytes=0-1")],
            "client": ("127.0.0.1", 123),
            "server": ("127.0.0.1", 80),
        }
        request = Request(scope)
        response = await emby_proxy_module.emby_stream_redirect("12", request)
        assert response.status_code == 307
        assert response.headers["location"] == "https://cdn.115.com/movie.mkv"

    @pytest.mark.asyncio
    async def test_endpoint_proxy115_falls_back_origin(self, monkeypatch) -> None:
        async def fake_context(item_id: str, *, media_source_id=None):
            return {
                "play_url": "http://172.16.100.2:8099/api/115/url/video.mkv?pickcode=abc",
                "item_id": item_id,
                "title": "Test",
                "media_type": "Movie",
                "series_name": "",
                "container": "mkv",
            }

        async def fake_final(play_url: str, headers=None, *, player_ua=""):
            return "/api/proxy-115?url=https%3A%2F%2Fcdn.115.com%2Fa.mkv"

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            fake_context,
        )
        monkeypatch.setattr(
            emby_proxy_module,
            "get_final_redirect_link",
            fake_final,
        )
        from fastapi import Request

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/emby/stream-redirect/12",
            "raw_path": b"/api/emby/stream-redirect/12",
            "query_string": b"",
            "headers": [(b"user-agent", b"SenPlayer/1.0")],
            "client": ("127.0.0.1", 123),
            "server": ("127.0.0.1", 80),
        }
        request = Request(scope)
        with pytest.raises(HTTPException) as exc:
            await emby_proxy_module.emby_stream_redirect("12", request)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_endpoint_returns_404_for_non_strm(self, monkeypatch) -> None:
        async def fake_resolve(item_id: str, *, media_source_id=None):
            return {
                "play_url": "",
                "item_id": item_id,
                "title": "",
                "media_type": "",
                "series_name": "",
                "container": "",
            }

        monkeypatch.setattr(
            emby_proxy_module, "resolve_stream_play_context_cached", fake_resolve
        )
        from fastapi import Request

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/emby/stream-redirect/1",
            "raw_path": b"/api/emby/stream-redirect/1",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("127.0.0.1", 80),
        }
        request = Request(scope)
        with pytest.raises(HTTPException) as exc:
            await emby_proxy_module.emby_stream_redirect("1", request)
        assert exc.value.status_code == 404


def _build_stream_request(
    item_id: str = "12",
    *,
    method: str = "GET",
    user_agent: bytes = b"VidHub/2.0.5",
    query: bytes = b"MediaSourceId=mediasource_12",
):
    from fastapi import Request

    headers = []
    if user_agent is not None:
        headers.append((b"user-agent", user_agent))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": f"/api/emby/stream-redirect/{item_id}",
        "raw_path": f"/api/emby/stream-redirect/{item_id}".encode(),
        "query_string": query,
        "headers": headers,
        "client": ("127.0.0.1", 123),
        "server": ("127.0.0.1", 80),
    }
    return Request(scope)


class TestIsoLocalProxy:
    """ISO/IMG 原盘强制走本地 Range 反代（绕开 f=1 直链 UA 死结）。"""

    def _iso_context(self, container: str = "iso"):
        async def fake_context(item_id: str, *, media_source_id=None):
            return {
                "play_url": (
                    "http://172.16.100.2:8099/api/115/url/video."
                    f"{container}?pickcode=abc"
                ),
                "item_id": item_id,
                "title": "Test ISO",
                "media_type": "Movie",
                "series_name": "",
                "container": container,
            }

        return fake_context

    def test_extract_pickcode_from_play_url(self) -> None:
        f = emby_proxy_module._extract_pickcode_from_play_url
        assert (
            f("http://h:8099/api/115/url/video.iso?pickcode=abc123") == "abc123"
        )
        assert f("http://h:8099/api/115/url/video.iso") == ""
        assert f("https://cdn.115cdn.net/x/movie.iso?t=1") == ""

    @pytest.mark.asyncio
    async def test_iso_endpoint_307_to_local_proxy(self, monkeypatch) -> None:
        async def fake_fetch(pick_code, *, user_agent="", **kwargs):
            return {"download_url": "https://cdnx.115cdn.net/a/movie.iso?t=1&f=1"}

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            self._iso_context("iso"),
        )
        import app.services.strm_service as strm_module

        monkeypatch.setattr(
            strm_module.strm_service, "_fetch_pick_code_download_info", fake_fetch
        )
        response = await emby_proxy_module.emby_stream_redirect(
            "12", _build_stream_request()
        )
        assert response.status_code == 307
        assert response.headers["location"].startswith("/api/proxy-115?url=")
        # CDN 直链被编码进 url 参数
        assert "cdnx.115cdn.net" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_iso_uses_fixed_ua_not_player_ua(self, monkeypatch) -> None:
        """核心防回归：申请 ISO 直链必须用固定 UA，不用播放器 UA。"""
        seen = {}

        async def fake_fetch(pick_code, *, user_agent="", **kwargs):
            seen["ua"] = user_agent
            return {"download_url": "https://cdnx.115cdn.net/a/movie.iso?f=1"}

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            self._iso_context("iso"),
        )
        import app.services.strm_service as strm_module

        monkeypatch.setattr(
            strm_module.strm_service, "_fetch_pick_code_download_info", fake_fetch
        )
        # 播放器带会被 CDN 403 的 UA
        await emby_proxy_module.emby_stream_redirect(
            "12",
            _build_stream_request(user_agent=b"AppleCoreMedia/1.0 (iPhone)"),
        )
        from app.api.pan115_play import PROXY_115_DEFAULT_UA

        assert seen["ua"] == PROXY_115_DEFAULT_UA

    @pytest.mark.asyncio
    async def test_iso_ignores_strm_redirect_mode(self, monkeypatch) -> None:
        """ISO 无条件反代，不受全局 strm_redirect_mode 影响。"""
        async def fake_fetch(pick_code, *, user_agent="", **kwargs):
            return {"download_url": "https://cdnx.115cdn.net/a/movie.iso?f=1"}

        monkeypatch.setattr(
            emby_proxy_module.runtime_settings_service,
            "get_strm_redirect_mode",
            lambda: "redirect",
        )
        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            self._iso_context("iso"),
        )
        import app.services.strm_service as strm_module

        monkeypatch.setattr(
            strm_module.strm_service, "_fetch_pick_code_download_info", fake_fetch
        )
        response = await emby_proxy_module.emby_stream_redirect(
            "12", _build_stream_request()
        )
        assert response.status_code == 307
        assert response.headers["location"].startswith("/api/proxy-115?url=")

    @pytest.mark.asyncio
    async def test_iso_resolve_failure_falls_back_to_cdn_redirect(
        self, monkeypatch
    ) -> None:
        """ISO 申请直链失败 → 回退直跳，不 502。"""
        async def fake_fetch(pick_code, *, user_agent="", **kwargs):
            raise RuntimeError("115 unreachable")

        async def fake_final(play_url: str, headers=None, *, player_ua=""):
            return "https://cdn.115.com/fallback.iso"

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            self._iso_context("iso"),
        )
        monkeypatch.setattr(emby_proxy_module, "get_final_redirect_link", fake_final)
        import app.services.strm_service as strm_module

        monkeypatch.setattr(
            strm_module.strm_service, "_fetch_pick_code_download_info", fake_fetch
        )
        response = await emby_proxy_module.emby_stream_redirect(
            "12", _build_stream_request()
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://cdn.115.com/fallback.iso"

    @pytest.mark.asyncio
    async def test_iso_head_returns_307_to_local_proxy(self, monkeypatch) -> None:
        async def fake_fetch(pick_code, *, user_agent="", **kwargs):
            return {"download_url": "https://cdnx.115cdn.net/a/movie.iso?f=1"}

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            self._iso_context("iso"),
        )
        import app.services.strm_service as strm_module

        monkeypatch.setattr(
            strm_module.strm_service, "_fetch_pick_code_download_info", fake_fetch
        )
        response = await emby_proxy_module.emby_stream_redirect(
            "12", _build_stream_request(method="HEAD")
        )
        assert response.status_code == 307
        assert response.headers["location"].startswith("/api/proxy-115?url=")

    @pytest.mark.asyncio
    async def test_non_iso_does_not_use_fixed_ua_proxy(self, monkeypatch) -> None:
        """非 ISO（mkv）不触发本地反代，走 get_final_redirect_link 直跳。"""
        called = {"fetch": False}

        async def fake_fetch(pick_code, *, user_agent="", **kwargs):
            called["fetch"] = True
            return {"download_url": "https://cdnx.115cdn.net/a/movie.mkv"}

        async def fake_final(play_url: str, headers=None, *, player_ua=""):
            return "https://cdn.115.com/movie.mkv"

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            self._iso_context("mkv"),
        )
        monkeypatch.setattr(emby_proxy_module, "get_final_redirect_link", fake_final)
        import app.services.strm_service as strm_module

        monkeypatch.setattr(
            strm_module.strm_service, "_fetch_pick_code_download_info", fake_fetch
        )
        response = await emby_proxy_module.emby_stream_redirect(
            "12", _build_stream_request()
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://cdn.115.com/movie.mkv"
        assert called["fetch"] is False  # 非 ISO 不以固定 UA 申请直链

    @pytest.mark.asyncio
    async def test_iso_no_pickcode_falls_back(self, monkeypatch) -> None:
        """ISO 但 play_url 无 pickcode → 回退直跳。"""
        async def fake_context(item_id: str, *, media_source_id=None):
            return {
                "play_url": "http://172.16.100.2:8099/api/115/url/video.iso",
                "item_id": item_id,
                "title": "",
                "media_type": "Movie",
                "series_name": "",
                "container": "iso",
            }

        async def fake_final(play_url: str, headers=None, *, player_ua=""):
            return "https://cdn.115.com/nopick.iso"

        monkeypatch.setattr(
            emby_proxy_module, "resolve_stream_play_context_cached", fake_context
        )
        monkeypatch.setattr(emby_proxy_module, "get_final_redirect_link", fake_final)
        response = await emby_proxy_module.emby_stream_redirect(
            "12", _build_stream_request()
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://cdn.115.com/nopick.iso"
