import logging
from datetime import datetime
from typing import Any

from app.core.database import async_session_maker
from app.models.models import DownloadRecord, MediaStatus
from app.services.pan115_service import Pan115Service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.subscription_service import subscription_service
from sqlalchemy import select

logger = logging.getLogger(__name__)


class OfflineMonitorService:
    """离线下载完成监控服务 — 检测到新完成的离线任务时自动触发归档扫描和订阅清理"""

    def __init__(self) -> None:
        self._known_tasks: dict[str, str] = {}

    async def check_and_trigger(self) -> dict[str, Any]:
        archive_skip_reason = ""
        if not runtime_settings_service.get_archive_enabled():
            archive_skip_reason = "归档未启用"
        elif not runtime_settings_service.get_archive_auto_on_offline():
            archive_skip_reason = "离线完成后自动归档未启用"
        elif not runtime_settings_service.get_archive_watch_cid():
            archive_skip_reason = "未配置归档监听目录"

        pan115 = Pan115Service(runtime_settings_service.get_pan115_cookie())

        try:
            result = await pan115.offline_task_list(1)
        except Exception:
            logger.debug("离线任务列表获取失败，跳过本次检查")
            return {"triggered": False, "reason": "离线任务列表获取失败"}

        tasks = result.get("tasks") or []
        current_hashes: dict[str, str] = {}
        for task in tasks:
            if not isinstance(task, dict):
                continue
            info_hash = str(task.get("info_hash") or task.get("hash") or "").strip()
            status_str = str(task.get("status") or task.get("state") or "").strip()
            if info_hash:
                current_hashes[info_hash] = status_str

        newly_completed: list[str] = []
        for info_hash, status in current_hashes.items():
            if status in ("-1", "1", "2", "3"):
                continue
            if info_hash in self._known_tasks:
                prev = self._known_tasks[info_hash]
                if prev in ("-1", "1", "2", "3") and status not in (
                    "-1",
                    "1",
                    "2",
                    "3",
                ):
                    newly_completed.append(info_hash)

        self._known_tasks = current_hashes

        offline_record_result = None
        try:
            async with async_session_maker() as db:
                offline_record_result = await self._sync_download_records(
                    db,
                    current_hashes=current_hashes,
                    newly_completed=newly_completed,
                )
        except Exception:
            logger.exception("离线任务状态同步到订阅记录失败")

        if not newly_completed and not int(
            (offline_record_result or {}).get("completed_count") or 0
        ):
            return {
                "triggered": False,
                "reason": "无新完成的离线任务",
                "known": len(current_hashes),
                "offline_record_result": offline_record_result,
            }

        scan_result = None
        if archive_skip_reason:
            scan_result = {"triggered": False, "reason": archive_skip_reason}
        else:
            from app.services.archive_service import archive_service

            if archive_service.is_scan_running():
                scan_result = {"triggered": False, "reason": "归档扫描正在执行中"}
            else:
                logger.info(
                    "检测到 %d 个离线任务新完成，触发归档扫描", len(newly_completed)
                )
                scan_result = await archive_service.start_scan(
                    trigger="offline_completed"
                )

        cleanup_result = None
        try:
            async with async_session_maker() as db:
                cleanup_result = (
                    await subscription_service.cleanup_completed_subscriptions(db)
                )
        except Exception:
            logger.exception("离线完成触发订阅清理失败")

        return {
            "triggered": True,
            "newly_completed": len(newly_completed),
            "scan_result": scan_result,
            "offline_record_result": offline_record_result,
            "cleanup_result": cleanup_result,
        }

    async def _sync_download_records(
        self,
        db,
        *,
        current_hashes: dict[str, str],
        newly_completed: list[str],
    ) -> dict[str, Any]:
        normalized_status = {
            str(key or "").upper(): str(value or "")
            for key, value in current_hashes.items()
            if str(key or "").strip()
        }
        completed_hashes = {str(item or "").upper() for item in newly_completed}
        if not normalized_status:
            return {"matched_count": 0, "completed_count": 0}

        result = await db.execute(
            select(DownloadRecord).where(
                DownloadRecord.offline_info_hash.in_(list(normalized_status.keys()))
            )
        )
        records = result.scalars().all()
        completed_count = 0
        now = datetime.utcnow()
        active_statuses = {"-1", "1", "2", "3"}
        for record in records:
            info_hash = str(record.offline_info_hash or "").upper()
            current_status = normalized_status.get(info_hash)
            record.offline_status = current_status
            is_completed = info_hash in completed_hashes or (
                current_status not in active_statuses
                and record.status == MediaStatus.OFFLINE_SUBMITTED
            )
            if is_completed:
                record.status = MediaStatus.OFFLINE_COMPLETED
                record.offline_completed_at = now
                record.completed_at = now
                record.error_message = None
                completed_count += 1
        if records:
            await db.commit()
        return {"matched_count": len(records), "completed_count": completed_count}

    def reset(self) -> None:
        self._known_tasks.clear()


offline_monitor_service = OfflineMonitorService()
