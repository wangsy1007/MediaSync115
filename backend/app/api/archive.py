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
    try:
        pan115 = Pan115Service()
        result = await pan115.get_file_list(cid=cid, limit=1000)
        items = result.get("data") or []
        folders = []
        for it in items:
            if not isinstance(it, dict):
                continue
            fid = str(it.get("fid") or "")
            cid_val = str(it.get("cid") or "")
            folder_id = fid or cid_val
            if not folder_id:
                continue
            if not pan115._is_folder_item(it):
                continue
            # 尝试多种可能的字段名获取文件夹名称
            name = (
                it.get("n")
                or it.get("name")
                or it.get("file_name")
                or it.get("fn")
                or it.get("title")
                or it.get("cid", "")[:8]  # 兜底显示 CID 前 8 位
            )
            folders.append(
                {
                    "cid": folder_id,
                    "name": name,
                }
            )
        folders.sort(key=lambda x: x["name"].lower())
        return {"cid": cid, "folders": folders}
    except Exception as exc:
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
