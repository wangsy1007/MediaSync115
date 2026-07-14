"""影视库播放日志：写入 operation_logs，供日志中心展示。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from uuid import uuid4

from app.services.operation_log_service import operation_log_service

logger = logging.getLogger(__name__)

_PROBE_UA = re.compile(
    r"Lavf/|ffmpeg|libcurl|python-requests|Go-http-client|urllib|httpx/",
    re.IGNORECASE,
)
_PLAYER_UA = re.compile(
    r"(HosPlayer/[\d.]+|VidHub/[\d.]+|Infuse/[\d.]+|SenPlayer/[\d.]+|"
    r"Fileball/[\d.]+|Yamby/[\d.]+|Emby/[\d.]+|AppleCoreMedia/[\d.]+|"
    r"Conflux/[\d.]+|Yamby/[\d.]+)",
    re.IGNORECASE,
)


class PlaybackLogService:
    def __init__(self) -> None:
        self._recent: dict[str, float] = {}
        self._dedup_ttl_seconds = 45.0

    @staticmethod
    def _extract_player_name(user_agent: str) -> str:
        ua = str(user_agent or "").strip()
        if not ua:
            return "未知客户端"
        match = _PLAYER_UA.search(ua)
        if match:
            return match.group(1)
        return ua[:80]

    @staticmethod
    def _is_probe_user_agent(user_agent: str) -> bool:
        return bool(_PROBE_UA.search(str(user_agent or "")))

    @staticmethod
    def _format_media_title(
        *,
        title: str = "",
        media_type: str = "",
        series_name: str = "",
    ) -> str:
        name = str(title or "").strip() or "未知"
        if str(media_type or "").strip() == "Episode":
            series = str(series_name or "").strip()
            if series:
                return f"{series} - {name}"
        return name

    def _should_log(self, dedup_key: str) -> bool:
        now = time.monotonic()
        expired = [
            key
            for key, seen_at in self._recent.items()
            if now - seen_at > self._dedup_ttl_seconds
        ]
        for key in expired:
            self._recent.pop(key, None)
        if dedup_key in self._recent:
            return False
        self._recent[dedup_key] = now
        return True

    async def log_playback(
        self,
        *,
        source: str,
        title: str,
        player: str,
        client_ip: str,
        play_mode: str,
        item_id: str = "",
        media_type: str = "",
        series_name: str = "",
        pick_code: str = "",
        http_method: str = "GET",
        path: str = "",
        status: str = "success",
        message: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        user_agent = player
        if self._is_probe_user_agent(user_agent):
            return

        player_name = self._extract_player_name(user_agent)
        media_title = self._format_media_title(
            title=title,
            media_type=media_type,
            series_name=series_name,
        )
        dedup_key = ":".join(
            part
            for part in (
                item_id or pick_code or media_title,
                client_ip,
                player_name,
            )
            if part
        )
        if not self._should_log(dedup_key):
            return

        mode_label = "302 直链" if play_mode == "redirect" else "服务端代理"
        final_message = message or (
            f"影视播放：《{media_title}》— {player_name}（{client_ip or 'unknown'}，{mode_label}）"
        )
        payload = {
            "source": source,
            "title": media_title,
            "item_id": item_id,
            "media_type": media_type,
            "series_name": series_name,
            "pick_code": pick_code,
            "player": player_name,
            "client_ip": client_ip,
            "play_mode": play_mode,
        }
        if extra:
            payload.update(extra)

        await operation_log_service.log(
            trace_id=uuid4().hex,
            source_type="playback",
            module="play",
            action="media.play",
            status=status,
            message=final_message,
            http_method=http_method,
            path=path,
            extra=payload,
        )


playback_log_service = PlaybackLogService()
