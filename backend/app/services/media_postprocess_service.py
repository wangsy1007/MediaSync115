import logging
from typing import Any

from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)


class MediaPostprocessService:
    """媒体转存后的统一后处理服务"""

    @staticmethod
    def _build_archive_scopes(
        summary: dict[str, Any],
    ) -> list[dict[str, str]] | None:
        items = summary.get("items")
        if not isinstance(items, list):
            return None

        scopes: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") not in {"success", "skipped"}:
                continue

            source_fid = str(item.get("source_fid") or "").strip()
            target_cid = str(item.get("target_cid") or "").strip()
            relative_prefix = str(item.get("target_desc") or "").strip()
            if not source_fid or not target_cid or not relative_prefix:
                continue

            scope_key = (source_fid, target_cid, relative_prefix)
            if scope_key in seen:
                continue
            seen.add(scope_key)
            scopes.append(
                {
                    "fid": source_fid,
                    "target_cid": target_cid,
                    "relative_prefix": relative_prefix,
                }
            )
        return scopes or None

    async def trigger_archive_after_transfer(
        self,
        trigger: str = "transfer",
        *,
        respect_save_queue: bool = True,
    ) -> dict[str, Any]:
        if not runtime_settings_service.get_archive_enabled():
            return {"triggered": False, "reason": "archive_disabled"}
        if not runtime_settings_service.get_archive_auto_on_transfer():
            return {"triggered": False, "reason": "archive_auto_on_transfer_disabled"}
        if not runtime_settings_service.get_archive_watch_cid():
            return {"triggered": False, "reason": "archive_watch_cid_missing"}

        if respect_save_queue:
            from app.services.explore_action_queue_service import (
                explore_action_queue_service,
            )

            deferred = await explore_action_queue_service.defer_until_save_queue_idle(
                f"archive:{trigger}",
                lambda: self.trigger_archive_after_transfer(
                    trigger=trigger,
                    respect_save_queue=False,
                ),
            )
            if deferred:
                return {
                    "triggered": False,
                    "deferred": True,
                    "reason": "save_queue_busy",
                }

        try:
            from app.services.archive_service import archive_service

            result = await archive_service.start_scan(
                trigger=trigger,
                respect_save_queue=respect_save_queue,
            )
            return {"triggered": True, "result": result}
        except Exception as exc:
            logger.warning("Failed to trigger archive scan after transfer: %s", exc)
            return {"triggered": False, "reason": str(exc)[:300]}

    async def trigger_strm_after_archive(
        self,
        summary: dict[str, Any] | None,
        *,
        trigger: str = "archive_completed",
    ) -> dict[str, Any]:
        if not runtime_settings_service.get_strm_enabled():
            return {"triggered": False, "reason": "strm_disabled"}
        if not runtime_settings_service.get_strm_auto_after_archive():
            return {"triggered": False, "reason": "strm_auto_after_archive_disabled"}

        payload = summary if isinstance(summary, dict) else {}
        processed_count = int(payload.get("success", 0) or 0) + int(
            payload.get("skipped", 0) or 0
        )
        if processed_count <= 0:
            return {"triggered": False, "reason": "no_processed_items"}

        from app.services.explore_action_queue_service import (
            explore_action_queue_service,
        )

        deferred = await explore_action_queue_service.defer_until_save_queue_idle(
            f"strm:{trigger}",
            lambda: self._trigger_strm_after_archive_now(
                payload,
                trigger=trigger,
            ),
        )
        if deferred:
            return {
                "triggered": False,
                "deferred": True,
                "reason": "save_queue_busy",
            }

        return await self._trigger_strm_after_archive_now(payload, trigger=trigger)

    async def _trigger_strm_after_archive_now(
        self,
        payload: dict[str, Any],
        *,
        trigger: str = "archive_completed",
    ) -> dict[str, Any]:
        try:
            from app.services.strm_service import strm_service

            scopes = self._build_archive_scopes(payload)
            result = await strm_service.start_generate_library(
                trigger=trigger,
                mode="incremental",
                scopes=scopes,
                respect_save_queue=False,
            )
            logger.info(
                "Triggered STRM after archive: trigger=%s success=%s skipped=%s scopes=%s",
                trigger,
                payload.get("success"),
                payload.get("skipped"),
                len(scopes or []),
            )
            return {"triggered": True, "result": result}
        except Exception as exc:
            logger.warning("Failed to trigger STRM generation after archive: %s", exc)
            return {"triggered": False, "reason": str(exc)[:300]}


    async def trigger_media_library_sync_after_subscription_transfer(
        self,
        *,
        transfer_count: int = 0,
        respect_save_queue: bool = True,
    ) -> dict[str, Any]:
        """订阅转存完成后触发 Emby/飞牛媒体库索引同步。"""
        if transfer_count <= 0:
            return {"triggered": False, "reason": "no_transfers"}
        if not runtime_settings_service.get_subscription_auto_sync_after_transfer():
            return {
                "triggered": False,
                "reason": "subscription_auto_sync_after_transfer_disabled",
            }

        if respect_save_queue:
            from app.services.explore_action_queue_service import (
                explore_action_queue_service,
            )

            deferred = await explore_action_queue_service.defer_until_save_queue_idle(
                "media_sync:subscription_transfer",
                lambda: self.trigger_media_library_sync_after_subscription_transfer(
                    transfer_count=transfer_count,
                    respect_save_queue=False,
                ),
            )
            if deferred:
                return {
                    "triggered": False,
                    "deferred": True,
                    "reason": "save_queue_busy",
                }

        results: dict[str, Any] = {}
        started_any = False
        deferred_any = False

        if runtime_settings_service.get_emby_sync_enabled():
            from app.services.emby_sync_index_service import emby_sync_index_service

            emby_result = await emby_sync_index_service.start_background_sync(
                trigger="subscription_transfer",
                respect_save_queue=False,
            )
            results["emby"] = emby_result
            started_any = started_any or bool(emby_result.get("started"))
            deferred_any = deferred_any or bool(emby_result.get("deferred"))

        if runtime_settings_service.get_feiniu_sync_enabled():
            from app.services.feiniu_sync_index_service import feiniu_sync_index_service

            feiniu_result = await feiniu_sync_index_service.start_background_sync(
                trigger="subscription_transfer",
                respect_save_queue=False,
            )
            results["feiniu"] = feiniu_result
            started_any = started_any or bool(feiniu_result.get("started"))
            deferred_any = deferred_any or bool(feiniu_result.get("deferred"))

        if not results:
            return {
                "triggered": False,
                "reason": "no_sync_target_enabled",
                "results": results,
            }

        return {
            "triggered": started_any or deferred_any,
            "started": started_any,
            "deferred": deferred_any,
            "results": results,
        }


media_postprocess_service = MediaPostprocessService()
