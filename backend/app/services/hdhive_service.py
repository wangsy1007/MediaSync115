"""HDHive 门面：Cookie + 网页解析，支持自动登录续期。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.services.hdhive_web_client import HDHiveWebClient


class HDHiveApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str = "",
        message: str = "",
        description: str = "",
    ) -> None:
        self.status_code = int(status_code or 500)
        self.code = str(code or "").strip()
        self.message = str(message or "").strip()
        self.description = str(description or "").strip()
        parts: list[str] = []
        if self.message:
            parts.append(self.message)
        if self.description and self.description != self.message:
            parts.append(self.description)
        if self.code and self.code not in parts:
            parts.append(self.code)
        final_message = "；".join(parts) if parts else f"HTTP {self.status_code}"
        super().__init__(final_message)


class HDHiveService:
    """HDHive 服务门面，委托 Web 客户端完成资源抓取与解锁。"""

    def __init__(
        self,
        base_url: str | None = None,
        cookie: str | None = None,
    ) -> None:
        self._base_url = str(base_url or settings.HDHIVE_BASE_URL or "https://hdhive.com/").strip().rstrip("/")
        self._cookie = str(cookie or settings.HDHIVE_COOKIE or "").strip()
        self._web = HDHiveWebClient(base_url=self._base_url, cookie=self._cookie)
        self._auth_lock = asyncio.Lock()

    def set_base_url(self, base_url: str | None) -> None:
        value = str(base_url or "").strip()
        if not value:
            return
        self._base_url = value.rstrip("/")
        self._web.set_base_url(self._base_url)

    def set_cookie(self, cookie: str | None) -> None:
        self._cookie = str(cookie or "").strip()
        self._web.set_cookie(self._cookie)

    @property
    def cookie(self) -> str:
        return self._cookie

    @staticmethod
    def _extract_first_int(raw_value: Any) -> int | None:
        return HDHiveWebClient._extract_first_int(raw_value)

    @staticmethod
    def _extract_current_user(raw: str) -> dict[str, Any]:
        return HDHiveWebClient._extract_current_user(raw)

    @staticmethod
    def _extract_server_action_id_from_chunk(raw: str, action_name: str) -> str:
        return HDHiveWebClient._extract_server_action_id_from_chunk(raw, action_name)

    @staticmethod
    def _extract_next_static_chunk_paths(raw: str) -> list[str]:
        return HDHiveWebClient._extract_next_static_chunk_paths(raw)

    @staticmethod
    def _normalize_slug(slug: str) -> str:
        return HDHiveWebClient._normalize_slug(slug)

    @staticmethod
    def _normalize_pan_type(raw_value: Any) -> str:
        return HDHiveWebClient._normalize_pan_type(raw_value)

    @classmethod
    def _is_pan115(cls, raw_value: Any) -> bool:
        return cls._normalize_pan_type(raw_value) == "115"

    def _map_resource_row(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        return self._web._map_resource_row(row, index)

    async def ensure_authenticated(self, *, persist_cookie: bool = True) -> None:
        """确保 Cookie 有效。不支持账密登录——请在设置中配置有效 Cookie。"""
        if not self._cookie:
            raise ValueError("HDHive 未登录，请在设置中配置有效的 Cookie，或从浏览器手动获取后填入")

    async def check_connection(self) -> dict[str, Any]:
        if not self._cookie:
            from app.services.runtime_settings_service import runtime_settings_service

            if runtime_settings_service.has_hdhive_credentials():
                await self.ensure_authenticated(persist_cookie=True)
            else:
                raise ValueError("未配置 HDHive Cookie 或账号密码")

        return await self._web.check_connection()

    async def get_user_info(self) -> dict[str, Any]:
        await self.ensure_authenticated()
        user = await self._web.get_user_info()
        return {
            "id": None,
            "username": str(user.get("username") or "").strip(),
            "nickname": str(user.get("nickname") or "").strip(),
            "email": "",
            "avatar_url": "",
            "is_vip": bool(user.get("is_vip")),
            "vip_expiration_date": "",
            "last_active_at": "",
            "points": self._extract_first_int(user.get("points")),
            "user_meta": {},
            "telegram_user": None,
            "created_at": "",
        }

    async def check_in(self, gamble: bool = False) -> dict[str, Any]:
        await self.ensure_authenticated()
        return await self._web.check_in(gamble=gamble)

    async def check_in_by_cookie(self, gamble: bool = False) -> dict[str, Any]:
        await self.ensure_authenticated()
        try:
            return await self._web.check_in_by_cookie(gamble=gamble)
        except ValueError as exc:
            raise HDHiveApiError(status_code=502, message=str(exc)) from exc

    async def unlock_resource(self, slug: str) -> dict[str, Any]:
        await self.ensure_authenticated()
        return await self._web.unlock_resource(slug)

    async def get_pan115_by_keyword(self, keyword: str, media_type: str = "movie") -> list[dict[str, Any]]:
        await self.ensure_authenticated()
        return await self._web.get_pan115_by_keyword(keyword, media_type)

    async def get_movie_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        await self.ensure_authenticated()
        return await self._web.get_movie_pan115(tmdb_id)

    async def get_tv_pan115(self, tmdb_id: int) -> list[dict[str, Any]]:
        await self.ensure_authenticated()
        return await self._web.get_tv_pan115(tmdb_id)

    async def get_movie_pan115_result(self, tmdb_id: int) -> dict[str, Any]:
        await self.ensure_authenticated()
        return await self._web.get_movie_pan115_result(tmdb_id)

    async def get_tv_pan115_result(self, tmdb_id: int) -> dict[str, Any]:
        await self.ensure_authenticated()
        return await self._web.get_tv_pan115_result(tmdb_id)

    async def get_movie_quark_result(self, tmdb_id: int) -> dict[str, Any]:
        await self.ensure_authenticated()
        return await self._web.get_movie_quark_result(tmdb_id)

    async def get_tv_quark_result(self, tmdb_id: int) -> dict[str, Any]:
        await self.ensure_authenticated()
        return await self._web.get_tv_quark_result(tmdb_id)

    @staticmethod
    def sort_free_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return HDHiveWebClient.sort_free_first(items)


hdhive_service = HDHiveService()
