from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.pan115_service import Pan115Service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.strm_scheduler_service import strm_scheduler_service
from app.services.strm_service import strm_service
from app.utils.request_utils import get_client_ip

router = APIRouter(prefix="/strm", tags=["strm"])


class StrmConfigRequest(BaseModel):
    strm_enabled: Optional[bool] = None
    strm_output_dir: Optional[str] = None
    strm_base_url: Optional[str] = None
    strm_redirect_mode: Optional[str] = None
    strm_auto_after_archive: Optional[bool] = None
    strm_refresh_emby_after_generate: Optional[bool] = None
    strm_refresh_feiniu_after_generate: Optional[bool] = None
    strm_proxy_enabled: Optional[bool] = None
    strm_proxy_port: Optional[int] = None
    strm_schedule_enabled: Optional[bool] = None
    strm_incremental_interval_minutes: Optional[int] = None
    strm_full_schedule_enabled: Optional[bool] = None
    strm_full_schedule_day: Optional[str] = None
    strm_full_schedule_time: Optional[str] = None


class StrmGenerateRequest(BaseModel):
    mode: Optional[str] = None


def _raise_strm_error(exc: Exception) -> None:
    error_msg = str(exc or "")
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=error_msg)
    if Pan115Service._is_auth_related_error(error_msg):
        raise HTTPException(status_code=401, detail="115 登录已失效，请先重新扫码登录")
    if Pan115Service._is_method_not_allowed_error(error_msg) or "频繁" in error_msg:
        raise HTTPException(status_code=429, detail="115 接口临时受限，请稍后再试")
    raise HTTPException(status_code=500, detail=error_msg or "STRM 操作失败")


def _validate_strm_settings(payload: dict[str, object]) -> None:
    base_url = str(
        payload.get("strm_base_url", runtime_settings_service.get_strm_base_url()) or ""
    ).strip()
    redirect_mode = (
        str(
            payload.get(
                "strm_redirect_mode", runtime_settings_service.get_strm_redirect_mode()
            )
            or "auto"
        )
        .strip()
        .lower()
    )
    schedule_enabled = bool(
        payload.get(
            "strm_schedule_enabled",
            runtime_settings_service.get_strm_schedule_enabled(),
        )
    )
    full_schedule_enabled = bool(
        payload.get(
            "strm_full_schedule_enabled",
            runtime_settings_service.get_strm_full_schedule_enabled(),
        )
    )
    strm_enabled = bool(
        payload.get("strm_enabled", runtime_settings_service.get_strm_enabled())
    )
    output_dir = str(
        payload.get(
            "strm_output_dir", runtime_settings_service.get_strm_output_dir()
        )
        or ""
    ).strip()

    if redirect_mode not in {"auto", "redirect", "proxy"}:
        raise HTTPException(
            status_code=400, detail="STRM 播放模式仅支持 auto / redirect / proxy"
        )
    if schedule_enabled or full_schedule_enabled:
        if not strm_enabled:
            raise HTTPException(status_code=400, detail="启用 STRM 定时任务前请先启用 STRM")
        if not output_dir or not base_url:
            raise HTTPException(
                status_code=400,
                detail="启用 STRM 定时任务前请先配置输出目录和播放根地址",
            )
        if not runtime_settings_service.get_archive_output_cid():
            raise HTTPException(
                status_code=400,
                detail="启用 STRM 定时任务前请先配置归档输出目录",
            )
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400, detail="STRM 播放根地址必须是合法的 HTTP(S) 地址"
        )


@router.get("/config")
async def get_strm_config():
    return {
        **runtime_settings_service.get_strm_config(),
        "archive_output_cid": runtime_settings_service.get_archive_output_cid(),
        "archive_output_name": runtime_settings_service.get_archive_output_name(),
        "mount_paths": strm_service.detect_mount_paths(),
        "suggested_base_url": f"http://{strm_service.detect_local_ip()}:9008",
        "runtime": await strm_service.get_runtime_status_async(),
    }


@router.put("/config")
async def update_strm_config(payload: StrmConfigRequest):
    updates = payload.model_dump(exclude_unset=True)
    _validate_strm_settings(updates)
    try:
        config = runtime_settings_service.update_strm_config(updates)
        await strm_scheduler_service.ensure_tasks()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        **config,
        "archive_output_cid": runtime_settings_service.get_archive_output_cid(),
        "archive_output_name": runtime_settings_service.get_archive_output_name(),
        "mount_paths": strm_service.detect_mount_paths(),
        "suggested_base_url": f"http://{strm_service.detect_local_ip()}:9008",
        "runtime": await strm_service.get_runtime_status_async(),
    }


@router.post("/generate")
async def generate_strm_files(
    payload: StrmGenerateRequest | None = Body(default=None),
    mode: str | None = Query(default=None),
):
    selected_mode = str((payload.mode if payload and payload.mode is not None else mode) or "incremental")
    selected_mode = selected_mode.strip().lower()
    if selected_mode not in {"incremental", "full"}:
        raise HTTPException(
            status_code=400,
            detail="STRM 生成模式仅支持 incremental / full",
        )
    try:
        return await strm_service.start_generate_library(
            trigger="manual",
            mode=selected_mode,
        )
    except Exception as exc:
        _raise_strm_error(exc)


@router.get("/diagnose")
async def diagnose_strm(request: Request):
    try:
        return await strm_service.diagnose_sample(request_headers=dict(request.headers))
    except Exception as exc:
        _raise_strm_error(exc)


@router.api_route("/play/{token}", methods=["GET", "HEAD"])
async def play_strm(token: str, request: Request):
    try:
        ua = request.headers.get("user-agent") or ""
        force_proxy = False
        try:
            payload = strm_service._decode_token(token)
            filename = str(payload.get("fn") or "").strip().lower()
            if "hosplayer" in ua.lower() and (
                filename.endswith(".iso") or filename.endswith(".img")
            ):
                force_proxy = True
        except Exception:
            force_proxy = False
        return await strm_service.resolve_play_response_with_headers(
            token=token,
            method=request.method,
            request_headers=dict(request.headers),
            client_ip=get_client_ip(request),
            request_path=request.url.path,
            force_proxy=force_proxy,
        )
    except Exception as exc:
        _raise_strm_error(exc)
