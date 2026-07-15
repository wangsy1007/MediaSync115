import asyncio
from datetime import datetime
from typing import Any, Callable

from app.services.emby_service import emby_service
from app.services.emby_sync_index_service import emby_sync_index_service
from app.services.feiniu_sync_index_service import feiniu_sync_index_service
from app.core.database import async_session_maker
from app.services.hdhive_service import hdhive_service
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.subscription_service import subscription_service
from app.services.archive_service import archive_service
from app.services.offline_monitor_service import offline_monitor_service

from app.core.timezone_utils import beijing_now


class JobRegistry:
    def __init__(self):
        self._subscription_lock = asyncio.Lock()
        self._running_channels: dict[str, str] = {}
        self._registry: dict[str, Callable[..., Any]] = {
            "system.refresh_emby": self._refresh_emby,
            "system.sync_emby_index": self._sync_emby_index,
            "system.sync_feiniu_index": self._sync_feiniu_index,
            "system.cleanup_runtime_cache": self._cleanup_runtime_cache,
            "system.noop": self._noop,
            "system.archive_scan": self._archive_scan,
            "system.offline_monitor": self._offline_monitor,
            "system.generate_strm_incremental": self._generate_strm_incremental,
            "system.generate_strm_full": self._generate_strm_full,
            "hdhive.cookie_renew": self._hdhive_cookie_renew,
            "hdhive.checkin": self._hdhive_checkin,
            "subscription.check": self._check_subscription,
            "chart_subscription.sync": self._chart_subscription_sync,
            "person_follow.sync": self._person_follow_sync,
            "tg.index.incremental": self._tg_index_incremental,
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
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        deferred, result = await defer_if_save_queue_busy(
            "scheduler:sync_emby_index",
            lambda: emby_sync_index_service.sync_index(
                trigger="scheduler",
                respect_save_queue=False,
            ),
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，Emby 媒体库同步已延迟至队列空闲",
            }
        return result

    async def _sync_feiniu_index(self, **kwargs) -> dict[str, Any]:
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        deferred, result = await defer_if_save_queue_busy(
            "scheduler:sync_feiniu_index",
            lambda: feiniu_sync_index_service.sync_index(
                trigger="scheduler",
                respect_save_queue=False,
            ),
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，飞牛媒体库同步已延迟至队列空闲",
            }
        return result

    async def _cleanup_runtime_cache(self, **kwargs) -> dict[str, Any]:
        from app.api import search as search_api
        from app.services import douban_explore_service, tmdb_explore_service

        search_api._movie_pan115_cache.clear()
        search_api._tv_pan115_cache.clear()
        search_api._emby_badge_cache.clear()
        search_api._feiniu_badge_cache.clear()
        for cache_item in search_api._popular_sections_cache.values():
            cache_item["payload"] = None
            cache_item["expires_at"] = 0.0
        search_api._popular_movies_cache["payload"] = None
        search_api._popular_movies_cache["expires_at"] = 0.0
        douban_explore_service._douban_sections_cache.clear()
        tmdb_explore_service._tmdb_sections_cache.clear()
        return {"success": True, "message": "runtime cache cleared"}

    async def _noop(self, **kwargs) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {
            "success": True,
            "message": f"noop executed at {beijing_now().isoformat()}",
        }

    async def _archive_scan(self, **kwargs) -> dict[str, Any]:
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        deferred, result = await defer_if_save_queue_busy(
            "scheduler:archive_scan",
            lambda: archive_service.start_scan(
                trigger="scheduler",
                respect_save_queue=False,
            ),
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，归档扫描已延迟至队列空闲",
            }
        return result

    async def _offline_monitor(self, **kwargs) -> dict[str, Any]:
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        deferred, result = await defer_if_save_queue_busy(
            "scheduler:offline_monitor",
            offline_monitor_service.check_and_trigger,
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，离线监控已延迟至队列空闲",
            }
        return result

    async def _generate_strm_incremental(self, **kwargs) -> dict[str, Any]:
        from app.services.strm_service import strm_service
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        deferred, result = await defer_if_save_queue_busy(
            "scheduler:strm_incremental",
            lambda: strm_service.generate_library(
                trigger="scheduler",
                mode="incremental",
                respect_save_queue=False,
            ),
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，STRM 生成已延迟至队列空闲",
            }
        return result

    async def _generate_strm_full(self, **kwargs) -> dict[str, Any]:
        from app.services.strm_service import strm_service
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        deferred, result = await defer_if_save_queue_busy(
            "scheduler:strm_full",
            lambda: strm_service.generate_library(
                trigger="scheduler",
                mode="full",
                respect_save_queue=False,
            ),
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，STRM 全量生成已延迟至队列空闲",
            }
        return result

    async def _hdhive_checkin(self, **kwargs) -> dict[str, Any]:
        gamble = runtime_settings_service.get_hdhive_auto_checkin_mode() == "gamble"
        method = runtime_settings_service.get_hdhive_auto_checkin_method()
        method_label = "Cookie" if method == "cookie" else "网页"
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
        points_earned = result.get("points_earned")
        points_msg = f"，获得 {points_earned} 积分" if points_earned is not None else ""
        await operation_log_service.log_background_event(
            source_type="scheduler",
            module="hdhive",
            action="hdhive.checkin.success",
            status="success",
            message=f"HDHive 签到成功（{method_label}）：{result.get('message') or ''}{points_msg}",
            extra={"method": method, "gamble": gamble, "result": result},
        )
        return result

    async def _hdhive_cookie_renew(self, **kwargs) -> dict[str, Any]:
        try:
            result = await hdhive_service.renew_cookie()
        except Exception as exc:
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="hdhive",
                action="hdhive.cookie_renew.failed",
                status="failed",
                message=f"HDHive Cookie 自动续期失败：{exc}",
            )
            raise

        if bool(result.get("renewed")):
            await operation_log_service.log_background_event(
                source_type="scheduler",
                module="hdhive",
                action="hdhive.cookie_renew.success",
                status="success",
                message="HDHive Cookie 已自动续期并持久化",
            )
        return result

    async def _check_subscription_channel(self, channel: str) -> dict[str, Any]:
        from app.services.subscription_run_task_service import subscription_run_task_service
        from app.services.transfer_queue_guard import defer_if_save_queue_busy

        running_task = await subscription_run_task_service.get_running_channel(channel)
        if running_task:
            return {
                "success": False,
                "message": f"channel {channel} is already running via background task",
                "already_running": True,
                "running_task": running_task,
            }

        async def _run_channel() -> dict[str, Any]:
            async with self._subscription_lock:
                if channel in self._running_channels:
                    return {
                        "success": False,
                        "message": f"channel {channel} is already running via scheduler",
                        "already_running": True,
                    }
                self._running_channels[channel] = "running"
            try:
                async with async_session_maker() as db:
                    return await subscription_service.run_channel_check(db, channel)
            finally:
                async with self._subscription_lock:
                    self._running_channels.pop(channel, None)

        deferred, result = await defer_if_save_queue_busy(
            f"scheduler:subscription_check:{channel}",
            _run_channel,
        )
        if deferred:
            return {
                "success": True,
                "deferred": True,
                "message": "转存队列执行中，订阅检查已延迟至队列空闲",
            }
        return result

    async def _check_subscription(self, **kwargs) -> dict[str, Any]:
        return await self._check_subscription_channel("all")

    async def _chart_subscription_sync(self, **kwargs) -> dict[str, Any]:
        from app.services.chart_subscription_service import run_chart_subscription

        return await run_chart_subscription()

    async def _person_follow_sync(self, **kwargs) -> dict[str, Any]:
        from app.services.person_follow_service import run_person_follow_sync

        return await run_person_follow_sync()

    async def _tg_index_incremental(self, **kwargs) -> dict[str, Any]:
        from app.services.tg_sync_service import tg_sync_service

        return await tg_sync_service.run_incremental_once()


job_registry = JobRegistry()
