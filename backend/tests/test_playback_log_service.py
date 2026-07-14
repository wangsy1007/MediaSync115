import pytest

from app.services.playback_log_service import PlaybackLogService, playback_log_service


class TestPlaybackLogService:
    def setup_method(self) -> None:
        self.service = PlaybackLogService()

    def test_skip_probe_user_agent(self) -> None:
        assert self.service._is_probe_user_agent("Lavf/59.27.100") is True
        assert self.service._is_probe_user_agent("HosPlayer/0.11.1") is False

    def test_extract_player_name(self) -> None:
        assert (
            self.service._extract_player_name("HosPlayer/0.11.1 CFNetwork/1408.0.4")
            == "HosPlayer/0.11.1"
        )
        assert self.service._extract_player_name("VidHub/2.0.5") == "VidHub/2.0.5"

    def test_format_episode_title(self) -> None:
        title = self.service._format_media_title(
            title="第 1 集",
            media_type="Episode",
            series_name="某某剧",
        )
        assert title == "某某剧 - 第 1 集"

    def test_dedup_within_ttl(self) -> None:
        assert self.service._should_log("11:172.16.100.2:HosPlayer/0.11.1") is True
        assert self.service._should_log("11:172.16.100.2:HosPlayer/0.11.1") is False

    @pytest.mark.asyncio
    async def test_log_playback_writes_operation_log(self, monkeypatch) -> None:
        calls: list[dict] = []

        async def fake_log(**kwargs):
            calls.append(kwargs)

        import app.services.playback_log_service as mod

        monkeypatch.setattr(mod.operation_log_service, "log", fake_log)

        await self.service.log_playback(
            source="emby_proxy",
            title="火遮眼",
            player="HosPlayer/0.11.1",
            client_ip="172.16.100.2",
            play_mode="redirect",
            item_id="11",
            path="/api/emby/stream-redirect/11",
        )

        assert len(calls) == 1
        assert calls[0]["source_type"] == "playback"
        assert calls[0]["module"] == "play"
        assert "火遮眼" in calls[0]["message"]
        assert calls[0]["extra"]["play_mode"] == "redirect"

        await self.service.log_playback(
            source="emby_proxy",
            title="火遮眼",
            player="HosPlayer/0.11.1",
            client_ip="172.16.100.2",
            play_mode="redirect",
            item_id="11",
        )
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_skip_lavf_probe(self, monkeypatch) -> None:
        calls: list[dict] = []

        import app.services.playback_log_service as mod

        async def fake_log(**kwargs):
            calls.append(kwargs)

        import app.services.playback_log_service as mod

        monkeypatch.setattr(mod.operation_log_service, "log", fake_log)

        await self.service.log_playback(
            source="strm_gateway",
            title="test.mkv",
            player="Lavf/59.27.100",
            client_ip="172.19.0.1",
            play_mode="redirect",
            pick_code="abc",
        )
        assert calls == []
