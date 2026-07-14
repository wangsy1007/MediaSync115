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
                        "Path": "http://172.16.100.2:8099/api/strm/play/abc",
                        "Protocol": "Http",
                    }
                ],
            }

        monkeypatch.setattr(emby_proxy_module, "_fetch_emby_item", fake_fetch)
        url = await resolve_stream_redirect_url("95", media_source_id="mediasource_95")
        assert url == "http://172.16.100.2:8099/api/strm/play/abc"

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

    def test_build_emby_style_direct_stream_url_with_iso_container(self) -> None:
        url = build_emby_style_direct_stream_url(
            item_id="12",
            media_source_id="mediasource_12",
            container="iso",
            extra_query={"api_key": "k1"},
        )
        assert url.startswith("/Videos/12/stream.iso?")
        assert "MediaSourceId=mediasource_12" in url
        assert "Static=true" in url

    def test_rewrite_playback_info_forces_direct_play(self) -> None:
        payload = {
            "MediaSources": [
                {
                    "Id": "mediasource_11",
                    "Path": "http://172.16.100.2:8099/api/strm/play/abc",
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
        assert ms["Path"] == "http://172.16.100.2:8099/api/strm/play/abc"
        assert ms["DirectStreamUrl"].startswith("/Videos/11/stream?")
        assert "MediaSourceId=mediasource_11" in ms["DirectStreamUrl"]
        assert "Static=true" in ms["DirectStreamUrl"]
        assert "api_key=k1" in ms["DirectStreamUrl"]
        assert "/api/strm/play/" not in ms["DirectStreamUrl"]
        assert ms["TranscodingUrl"] is None

    def test_rewrite_playback_info_sets_iso_container(self, monkeypatch) -> None:
        monkeypatch.setattr(
            emby_proxy_module,
            "extract_filename_from_play_token",
            lambda _url: "115Zootopia.22025RepackUSAsGnbCHDBits.iso",
        )
        payload = {
            "MediaSources": [
                {
                    "Id": "mediasource_12",
                    "Path": "http://172.16.100.2:8099/api/strm/play/abc",
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
        assert ms["DirectStreamUrl"].startswith("/Videos/12/stream.iso?")

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
    async def test_resolve_final_redirect_uses_cdn(self, monkeypatch) -> None:
        class FakeStrm:
            @staticmethod
            def _extract_token_from_url(url: str) -> str:
                return "abc.token"

            @staticmethod
            async def resolve_download_url_with_ua(token: str, *, user_agent: str = ""):
                assert token == "abc.token"
                assert "VidHub" in user_agent
                return {
                    "download_url": "https://cdn.115.com/video.mp4",
                    "mode": "redirect",
                }

        monkeypatch.setattr(
            "app.services.strm_service.strm_service",
            FakeStrm(),
        )
        url = await emby_proxy_module._resolve_final_redirect_url(
            "http://172.16.100.2:8099/api/strm/play/abc.token",
            user_agent="VidHub/1.0",
        )
        assert url == "https://cdn.115.com/video.mp4"

    def test_no_ua_skips_stream_redirect_by_default(self) -> None:
        assert _should_skip_stream_redirect("HosPlayer/0.10.3") is False
        assert _should_skip_stream_redirect("Infuse/7.0") is False
        assert _should_skip_stream_redirect("") is False

    @pytest.mark.asyncio
    async def test_endpoint_redirects_iso_with_cached_cdn(self, monkeypatch) -> None:
        async def fake_context(item_id: str, *, media_source_id=None):
            return {
                "play_url": "http://172.16.100.2:8099/api/strm/play/abc.token",
                "item_id": item_id,
                "title": "Test ISO",
                "media_type": "Movie",
                "series_name": "",
                "container": "iso",
            }

        async def fake_redirect(play_url: str, *, user_agent: str):
            assert "SenPlayer" in user_agent
            return "https://cdn.115.com/movie.iso", "redirect"

        monkeypatch.setattr(
            emby_proxy_module,
            "resolve_stream_play_context_cached",
            fake_context,
        )
        monkeypatch.setattr(
            emby_proxy_module,
            "_resolve_final_redirect_info",
            fake_redirect,
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
            "headers": [(b"user-agent", b"SenPlayer/1.0"), (b"range", b"bytes=0-1")],
            "client": ("127.0.0.1", 123),
            "server": ("127.0.0.1", 80),
        }
        request = Request(scope)
        response = await emby_proxy_module.emby_stream_redirect("12", request)
        assert response.status_code == 302
        assert response.headers["location"] == "https://cdn.115.com/movie.iso"

    @pytest.mark.asyncio
    async def test_endpoint_returns_404_for_non_strm(self, monkeypatch) -> None:
        async def fake_resolve(item_id: str, *, media_source_id=None):
            return ""

        monkeypatch.setattr(
            emby_proxy_module, "resolve_stream_redirect_url", fake_resolve
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
