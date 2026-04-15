import asyncio
import logging
from typing import Any

from app.services.pan115_service import Pan115Service
from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)


class OfflineMonitorService:
    """离线下载完成监控服务 — 检测到新完成的离线任务时自动触发归档扫描"""

    def __init__(self) -> None:
        self._known_tasks: dict[str, str] = {}

    async def check_and_trigger(self) -> dict[str, Any]:
        if not runtime_settings_service.get_archive_enabled():
            return {"triggered": False, "reason": "归档未启用"}
        if not runtime_settings_service.get_archive_auto_on_offline():
            return {"triggered": False, "reason": "离线完成后自动归档未启用"}
        if not runtime_settings_service.get_archive_watch_cid():
            return {"triggered": False, "reason": "未配置归档监听目录"}

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

        if not newly_completed:
            return {
                "triggered": False,
                "reason": "无新完成的离线任务",
                "known": len(current_hashes),
            }

        from app.services.archive_service import archive_service

        if archive_service.is_scan_running():
            return {
                "triggered": False,
                "reason": "归档扫描正在执行中",
                "newly_completed": len(newly_completed),
            }

        logger.info("检测到 %d 个离线任务新完成，触发归档扫描", len(newly_completed))
        scan_result = await archive_service.start_scan(trigger="offline_completed")
        return {
            "triggered": True,
            "newly_completed": len(newly_completed),
            "scan_result": scan_result,
        }

    def reset(self) -> None:
        self._known_tasks.clear()


offline_monitor_service = OfflineMonitorService()
