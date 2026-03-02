import asyncio
from datetime import datetime
from typing import Any, Callable

from app.services.emby_service import emby_service
from app.core.database import async_session_maker
from app.services.subscription_service import subscription_service


class JobRegistry:
    def __init__(self):
        self._registry: dict[str, Callable[..., Any]] = {
            "system.refresh_emby": self._refresh_emby,
            "system.cleanup_runtime_cache": self._cleanup_runtime_cache,
            "system.noop": self._noop,
            "subscription.check_nullbr": self._check_subscription_nullbr,
            "subscription.check_pansou": self._check_subscription_pansou,
            "subscription.check_tg": self._check_subscription_tg,
        }

    def get(self, job_key: str) -> Callable[..., Any] | None:
        return self._registry.get(job_key)

    def register(self, job_key: str, func: Callable[..., Any]) -> None:
        self._registry[job_key] = func

    def list_keys(self) -> list[str]:
        return sorted(self._registry.keys())

    async def _refresh_emby(self, **kwargs) -> dict[str, Any]:
        await emby_service.refresh_library()
        return {"success": True, "message": "emby refresh triggered"}

    async def _cleanup_runtime_cache(self, **kwargs) -> dict[str, Any]:
        from app.api import search as search_api

        search_api._movie_pan115_cache.clear()
        search_api._tv_pan115_cache.clear()
        for cache_item in search_api._popular_sections_cache.values():
            cache_item["payload"] = None
            cache_item["expires_at"] = 0.0
        search_api._popular_movies_cache["payload"] = None
        search_api._popular_movies_cache["expires_at"] = 0.0
        return {"success": True, "message": "runtime cache cleared"}

    async def _noop(self, **kwargs) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"success": True, "message": f"noop executed at {datetime.utcnow().isoformat()}"}

    async def _check_subscription_nullbr(self, **kwargs) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await subscription_service.run_channel_check(db, "nullbr")

    async def _check_subscription_pansou(self, **kwargs) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await subscription_service.run_channel_check(db, "pansou")

    async def _check_subscription_tg(self, **kwargs) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await subscription_service.run_channel_check(db, "tg")


job_registry = JobRegistry()
