import asyncio
from datetime import datetime
from typing import Any, Callable

from app.services.emby_service import emby_service
from app.services.emby_sync_index_service import emby_sync_index_service
from app.services.feiniu_sync_index_service import feiniu_sync_index_service
from app.services.explore_home_warmup_service import explore_home_warmup_service
from app.core.database import async_session_maker
from app.services.hdhive_service import hdhive_service
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.subscription_service import subscription_service
from app.services.archive_service import archive_service
from app.services.offline_monitor_service import offline_monitor_service


class JobRegistry:
    def __init__(self):
        self._registry: dict[str, Callable[..., Any]] = {
            "system.refresh_emby": self._refresh_emby,
            "system.sync_emby_index": self._sync_emby_index,
            "system.sync_feiniu_index": self._sync_feiniu_index,
            "system.cleanup_runtime_cache": self._cleanup_runtime_cache,
            "system.warmup_explore_home_cache": self._warmup_explore_home_cache,
            "system.noop": self._noop,
            "system.archive_scan": self._archive_scan,
            "system.offline_monitor": self._offline_monitor,
            "hdhive.checkin": self._hdhive_checkin,
            "subscription.check_hdhive": self._check_subscription_hdhive,
            "subscription.check_pansou": self._check_subscription_pansou,
            "subscription.check_tg": self._check_subscription_tg,
            "chart_subscription.sync": self._chart_subscription_sync,
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

    async def _sync_emby_index(self, **kwargs) -> dict[str, Any]:
        return await emby_sync_index_service.sync_index(trigger="scheduler")

    async def _sync_feiniu_index(self, **kwargs) -> dict[str, Any]:
        return await feiniu_sync_index_service.sync_index(trigger="scheduler")

    async def _cleanup_runtime_cache(self, **kwargs) -> dict[str, Any]:
        from app.api import search as search_api
        from app.services import douban_explore_service, tmdb_explore_service

        search_api._movie_pan115_cache.clear()
        search_api._tv_pan115_cache.clear()
        search_api._emby_badge_cache.clear()
        search_api._feiniu_badge_cache.clear()
        explore_home_warmup_service.clear_snapshots()
        for cache_item in search_api._popular_sections_cache.values():
            cache_item["payload"] = None
            cache_item["expires_at"] = 0.0
        search_api._popular_movies_cache["payload"] = None
        search_api._popular_movies_cache["expires_at"] = 0.0
        douban_explore_service._douban_sections_cache.clear()
        tmdb_explore_service._tmdb_sections_cache.clear()
        return {"success": True, "message": "runtime cache cleared"}

    async def _warmup_explore_home_cache(self, **kwargs) -> dict[str, Any]:
        return await explore_home_warmup_service.warmup(force_refresh=False)

    async def _noop(self, **kwargs) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {
            "success": True,
            "message": f"noop executed at {datetime.utcnow().isoformat()}",
        }

    async def _archive_scan(self, **kwargs) -> dict[str, Any]:
        return await archive_service.start_scan(trigger="scheduler")

    async def _offline_monitor(self, **kwargs) -> dict[str, Any]:
        return await offline_monitor_service.check_and_trigger()

    async def _hdhive_checkin(self, **kwargs) -> dict[str, Any]:
        gamble = runtime_settings_service.get_hdhive_auto_checkin_mode() == "gamble"
        method = runtime_settings_service.get_hdhive_auto_checkin_method()
        method_label = "Cookie" if method == "cookie" else "API Key"
        await operation_log_service.log_background_event(
            source_type="scheduler",
            module="hdhive",
            action="hdhive.checkin.start",
            status="info",
            message=f"HDHive 自动签到开始（方式：{method_label}，模式：{'赌博' if gamble else '普通'}）",
        )
        if method == "cookie":
            result = await hdhive_service.check_in_by_cookie(gamble=gamble)
        else:
            result = await hdhive_service.check_in(gamble=gamble)
        if str(result.get("status") or "") == "already_checked_in":
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="hdhive",
                action="hdhive.checkin.skipped",
                status="info",
                message=f"HDHive 今日已签到（{method_label}）：{result.get('message') or ''}",
                extra={"method": method, "gamble": gamble, "result": result},
            )
            return result
        if not bool(result.get("success")):
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="hdhive",
                action="hdhive.checkin.failed",
                status="failed",
                message=f"HDHive 签到失败：{result.get('message') or '未知错误'}",
                extra={"method": method, "gamble": gamble},
            )
            raise ValueError(str(result.get("message") or "HDHive 自动签到失败"))
        await operation_log_service.log_background_event(
            source_type="scheduler",
            module="hdhive",
            action="hdhive.checkin.success",
            status="success",
            message=f"HDHive 签到成功（{method_label}）：{result.get('message') or ''}",
            extra={"method": method, "gamble": gamble, "result": result},
        )
        return result

    async def _check_subscription_pansou(self, **kwargs) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await subscription_service.run_channel_check(db, "pansou")

    async def _check_subscription_hdhive(self, **kwargs) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await subscription_service.run_channel_check(db, "hdhive")

    async def _check_subscription_tg(self, **kwargs) -> dict[str, Any]:
        async with async_session_maker() as db:
            return await subscription_service.run_channel_check(db, "tg")

    async def _chart_subscription_sync(self, **kwargs) -> dict[str, Any]:
        from app.services.chart_subscription_service import run_chart_subscription

        return await run_chart_subscription()


job_registry = JobRegistry()
