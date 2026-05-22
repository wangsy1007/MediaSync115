"""夸克网盘 API 路由

提供：
- Cookie 配置（更新 / 状态查询 / 连通性检查）
- 默认转存目录选择（目录浏览 / 持久化）
- 分享转存（一键转存到指定目录）
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from app.services.operation_log_service import operation_log_service
from app.services.quark_service import quark_service
from app.services.runtime_settings_service import runtime_settings_service

router = APIRouter(prefix="/quark", tags=["quark"])
logger = logging.getLogger(__name__)


# ───── 请求/响应模型 ─────


class QuarkCookieUpdateRequest(BaseModel):
    cookie: str


class QuarkDefaultFolderRequest(BaseModel):
    folder_id: str
    folder_name: str = ""


class QuarkSaveShareRequest(BaseModel):
    share_url: str
    folder_name: Optional[str] = None
    target_folder_id: Optional[str] = None
    receive_code: Optional[str] = ""
    tmdb_id: Optional[int] = None


# ───── Helper ─────


def _mask_cookie(cookie: str) -> str:
    """脱敏 cookie，仅保留首尾 4 字符"""
    raw = str(cookie or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "***"
    return f"{raw[:4]}***{raw[-4:]}"


def _shorten_share_url(share_url: str) -> str:
    """脱敏分享链接（保留 share_id）"""
    raw = str(share_url or "").strip()
    if "/s/" in raw:
        return raw[: raw.find("/s/") + 16] + "..."
    return raw[:60]


# ───── Cookie & 连通性 ─────


@router.get("/cookie")
async def get_cookie_info() -> dict[str, Any]:
    """获取 cookie 状态（脱敏）"""
    cookie = runtime_settings_service.get_quark_cookie()
    return {
        "is_configured": bool(cookie),
        "preview": _mask_cookie(cookie),
    }


@router.post("/cookie/update")
async def update_cookie(payload: QuarkCookieUpdateRequest) -> dict[str, Any]:
    """更新夸克 Cookie"""
    try:
        runtime_settings_service.update_quark_cookie(payload.cookie)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await operation_log_service.log_background_event(
        source_type="api",
        module="quark",
        action="quark_cookie_updated",
        status="success",
        message="夸克 Cookie 已更新",
    )
    return {"success": True, "message": "夸克 Cookie 已更新"}


@router.get("/cookie/check")
async def check_cookie() -> dict[str, Any]:
    """连通性检查"""
    if not quark_service.is_configured():
        raise HTTPException(
            status_code=412,
            detail={"code": "quark_cookie_missing", "message": "请先配置夸克 Cookie"},
        )
    try:
        result = await quark_service.check_cookie_valid()
    except Exception as exc:
        await operation_log_service.log_background_event(
            source_type="api",
            module="quark",
            action="quark_connectivity_check",
            status="failed",
            message=f"连通性检查失败: {str(exc)[:120]}",
        )
        raise HTTPException(status_code=502, detail=f"连接夸克失败: {str(exc)[:120]}")

    if not result.get("valid"):
        await operation_log_service.log_background_event(
            source_type="api",
            module="quark",
            action="quark_connectivity_check",
            status="failed",
            message=str(result.get("message") or "Cookie 无效"),
        )
        raise HTTPException(
            status_code=401,
            detail={
                "code": "quark_cookie_invalid",
                "message": result.get("message") or "夸克 Cookie 无效或已过期",
            },
        )

    await operation_log_service.log_background_event(
        source_type="api",
        module="quark",
        action="quark_connectivity_check",
        status="success",
        message="连通性检查成功",
    )
    return {
        "success": True,
        "valid": True,
        "user_info": result.get("user_info") or {},
        "message": result.get("message") or "连接成功",
    }


@router.get("/connectivity/check")
async def connectivity_check_alias() -> dict[str, Any]:
    """连通性检查的别名（设置页用）"""
    return await check_cookie()


# ───── 目录浏览 / 默认目录 ─────


@router.get("/folders")
async def list_folders(
    parent_fid: str = Query("0", description="父目录 fid"),
    page: int = Query(1, ge=1),
    size: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """列出夸克网盘指定目录下的子目录"""
    if not quark_service.is_configured():
        raise HTTPException(
            status_code=412,
            detail={"code": "quark_cookie_missing", "message": "请先配置夸克 Cookie"},
        )
    try:
        result = await quark_service.list_folders(parent_fid, page=page, size=size)
        return result
    except ValueError as exc:
        reason = str(exc)
        if reason == "quark_cookie_invalid":
            raise HTTPException(
                status_code=401,
                detail={"code": reason, "message": "夸克 Cookie 已过期，请重新获取"},
            )
        raise HTTPException(status_code=400, detail=reason)
    except Exception as exc:
        logger.exception("list_folders failed")
        raise HTTPException(status_code=502, detail=f"夸克目录加载失败: {str(exc)[:120]}")


@router.get("/default-folder")
async def get_default_folder() -> dict[str, Any]:
    """获取默认转存目录"""
    return runtime_settings_service.get_quark_default_folder()


@router.post("/default-folder")
async def update_default_folder(payload: QuarkDefaultFolderRequest) -> dict[str, Any]:
    """更新默认转存目录"""
    result = runtime_settings_service.update_quark_default_folder(
        payload.folder_id, payload.folder_name
    )
    return result


# ───── 分享转存 ─────


@router.post("/share/save-to-folder")
async def save_share_to_folder(payload: QuarkSaveShareRequest) -> dict[str, Any]:
    """一键转存夸克分享到默认目录或指定目录"""
    if not quark_service.is_configured():
        raise HTTPException(
            status_code=412,
            detail={"code": "quark_cookie_missing", "message": "请先在设置页配置夸克 Cookie"},
        )

    target_fid = (payload.target_folder_id or "").strip()
    if not target_fid:
        default = runtime_settings_service.get_quark_default_folder()
        target_fid = str(default.get("folder_id") or "").strip()

    if not target_fid:
        raise HTTPException(
            status_code=412,
            detail={
                "code": "quark_default_dir_missing",
                "message": "请先在设置页选择夸克默认转存目录",
            },
        )

    try:
        result = await quark_service.save_share_to_folder(
            share_url=payload.share_url,
            target_folder_fid=target_fid,
            folder_name=payload.folder_name,
            passcode=payload.receive_code or "",
            tmdb_id=payload.tmdb_id,
        )
    except ValueError as exc:
        reason = str(exc)
        if reason == "quark_cookie_missing":
            raise HTTPException(
                status_code=412,
                detail={"code": reason, "message": "请先配置夸克 Cookie"},
            )
        if reason == "quark_cookie_invalid":
            await operation_log_service.log_background_event(
                source_type="api",
                module="quark",
                action="quark_error",
                status="failed",
                message=f"转存失败：Cookie 无效 | {_shorten_share_url(payload.share_url)}",
            )
            raise HTTPException(
                status_code=401,
                detail={"code": reason, "message": "夸克 Cookie 已过期，请重新获取"},
            )
        if reason == "quark_rate_limited":
            raise HTTPException(
                status_code=429,
                detail={"code": reason, "message": "夸克网盘繁忙，请稍后重试"},
            )
        raise HTTPException(status_code=400, detail=reason)
    except Exception as exc:
        logger.exception("quark save_share_to_folder failed")
        await operation_log_service.log_background_event(
            source_type="api",
            module="quark",
            action="quark_error",
            status="failed",
            message=f"转存失败：{str(exc)[:120]} | {_shorten_share_url(payload.share_url)}",
        )
        raise HTTPException(status_code=502, detail=f"夸克转存失败: {str(exc)[:120]}")

    if result.get("success"):
        await operation_log_service.log_background_event(
            source_type="api",
            module="quark",
            action="quark_save",
            status="success",
            message=(
                f"夸克转存成功：{result.get('item_count', 0)} 个文件 → "
                f"{(payload.folder_name or '默认目录')}"
            ),
            extra={
                "share_url": _shorten_share_url(payload.share_url),
                "target_folder_id": target_fid,
                "folder_name": payload.folder_name,
                "item_count": result.get("item_count"),
                "tmdb_id": payload.tmdb_id,
            },
        )

    return result
