from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.archive_scheduler_service import archive_scheduler_service
from app.services.archive_service import archive_service
from app.services.pan115_service import Pan115Service
from app.services.runtime_settings_service import runtime_settings_service

router = APIRouter(prefix="/archive", tags=["archive"])


class ArchiveConfigRequest(BaseModel):
    archive_enabled: Optional[bool] = None
    archive_watch_cid: Optional[str] = None
    archive_watch_name: Optional[str] = None
    archive_output_cid: Optional[str] = None
    archive_output_name: Optional[str] = None
    archive_interval_minutes: Optional[int] = None

    class Config:
        extra = "allow"


@router.get("/config")
async def get_archive_config():
    return {
        **runtime_settings_service.get_archive_config(),
        "runtime": archive_service.get_runtime_status(),
    }


@router.put("/config")
async def update_archive_config(payload: ArchiveConfigRequest):
    updates = payload.model_dump(exclude_unset=True)
    next_enabled = updates.get(
        "archive_enabled",
        runtime_settings_service.get_archive_enabled(),
    )
    next_watch_cid = str(
        updates.get(
            "archive_watch_cid", runtime_settings_service.get_archive_watch_cid()
        )
        or ""
    ).strip()
    next_output_cid = str(
        updates.get(
            "archive_output_cid", runtime_settings_service.get_archive_output_cid()
        )
        or ""
    ).strip()

    if next_enabled and not next_watch_cid:
        raise HTTPException(
            status_code=400, detail="启用归档前必须配置 115 监听目录 ID"
        )
    if next_enabled and not next_output_cid:
        raise HTTPException(
            status_code=400, detail="启用归档前必须配置 115 输出目录 ID"
        )

    config = runtime_settings_service.update_archive_config(updates)
    await archive_scheduler_service.ensure_scan_task()
    return {
        **config,
        "runtime": archive_service.get_runtime_status(),
    }


@router.get("/folders")
async def list_folders(cid: str = "0"):
    """列出 115 网盘指定目录下的子文件夹（用于目录选择器）"""
    import logging
    logger = logging.getLogger(__name__)
    try:
        pan115 = Pan115Service()
        result = await pan115.get_file_list(cid=cid, limit=1000)
        items = result.get("data") or []
        logger.info(f"[list_folders] cid={cid}, items count={len(items)}")
        if items:
            logger.info(f"[list_folders] first item keys={list(items[0].keys()) if isinstance(items[0], dict) else 'N/A'}")
            logger.info(f"[list_folders] first item sample={items[0] if isinstance(items[0], dict) else 'N/A'}")
        folders = []
        for it in items:
            if not isinstance(it, dict):
                continue
            # 115 文件夹使用 cid 作为标识，fid 通常是 None 或空
            cid_val = str(it.get("cid") or "")
            fid_val = str(it.get("fid") or "")
            # 优先使用 cid（文件夹ID），如果没有则使用 fid
            folder_id = cid_val or fid_val
            if not folder_id:
                continue
            # 判断是否为文件夹：检查 ico 字段或没有 fid 的情况
            ico = str(it.get("ico") or "").lower()
            is_folder = ico == "folder" or not fid_val
            if not is_folder:
                continue
            # 尝试多种可能的字段名获取文件夹名称
            name = (
                it.get("n")
                or it.get("name")
                or it.get("file_name")
                or it.get("fn")
                or it.get("title")
                or folder_id[:8]  # 兜底显示 ID 前 8 位
            )
            folders.append(
                {
                    "cid": folder_id,
                    "name": name,
                }
            )
        folders.sort(key=lambda x: x["name"].lower())
        logger.info(f"[list_folders] folders count={len(folders)}")
        return {"cid": cid, "folders": folders}
    except Exception as exc:
        import traceback
        logger.error(f"[list_folders] error: {exc}\n{traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/tasks")
async def list_archive_tasks(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
):
    try:
        return await archive_service.list_tasks(
            status=status, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/scan")
async def run_archive_scan():
    try:
        return await archive_service.run_scan(trigger="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tasks/{task_id}/retry")
async def retry_archive_task(task_id: int):
    try:
        return await archive_service.retry_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/tasks/clear")
async def clear_archive_tasks(include_failed: bool = False):
    removed = await archive_service.clear_tasks(include_failed=include_failed)
    return {"success": True, "removed": removed}
