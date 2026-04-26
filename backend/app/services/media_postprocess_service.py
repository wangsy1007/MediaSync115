import logging
from typing import Any

from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)


class MediaPostprocessService:
    """媒体转存后的统一后处理服务"""

    async def trigger_archive_after_transfer(
        self, trigger: str = "transfer"
    ) -> dict[str, Any]:
        if not runtime_settings_service.get_archive_enabled():
            return {"triggered": False, "reason": "archive_disabled"}
        if not runtime_settings_service.get_archive_auto_on_transfer():
            return {"triggered": False, "reason": "archive_auto_on_transfer_disabled"}
        if not runtime_settings_service.get_archive_watch_cid():
            return {"triggered": False, "reason": "archive_watch_cid_missing"}

        try:
            from app.services.archive_service import archive_service

            result = await archive_service.start_scan(trigger=trigger)
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

        payload = summary if isinstance(summary, dict) else {}
        processed_count = int(payload.get("success", 0) or 0) + int(
            payload.get("skipped", 0) or 0
        )
        if processed_count <= 0:
            return {"triggered": False, "reason": "no_processed_items"}

        try:
            from app.services.strm_service import strm_service

            result = await strm_service.start_generate_library(trigger=trigger)
            return {"triggered": True, "result": result}
        except Exception as exc:
            logger.warning("Failed to trigger STRM generation after archive: %s", exc)
            return {"triggered": False, "reason": str(exc)[:300]}


media_postprocess_service = MediaPostprocessService()
