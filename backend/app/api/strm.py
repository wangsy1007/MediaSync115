from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.pan115_service import Pan115Service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.strm_service import strm_service

router = APIRouter(prefix="/strm", tags=["strm"])


class StrmConfigRequest(BaseModel):
    strm_enabled: Optional[bool] = None
    strm_output_dir: Optional[str] = None
    strm_base_url: Optional[str] = None
    strm_redirect_mode: Optional[str] = None
    strm_refresh_emby_after_generate: Optional[bool] = None
    strm_refresh_feiniu_after_generate: Optional[bool] = None


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
    enabled = bool(
        payload.get("strm_enabled", runtime_settings_service.get_strm_enabled())
    )
    output_dir = str(
        payload.get("strm_output_dir", runtime_settings_service.get_strm_output_dir())
        or ""
    ).strip()
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

    if redirect_mode not in {"auto", "redirect", "proxy"}:
        raise HTTPException(
            status_code=400, detail="STRM 播放模式仅支持 auto / redirect / proxy"
        )
    if not enabled:
        return
    if not runtime_settings_service.get_archive_output_cid():
        raise HTTPException(status_code=400, detail="启用 STRM 前请先配置归档输出目录")
    if not output_dir:
        raise HTTPException(status_code=400, detail="启用 STRM 前必须配置输出目录")
    if not base_url:
        raise HTTPException(status_code=400, detail="启用 STRM 前必须配置播放根地址")
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
        "runtime": strm_service.get_runtime_status(),
    }


@router.put("/config")
async def update_strm_config(payload: StrmConfigRequest):
    updates = payload.model_dump(exclude_unset=True)
    _validate_strm_settings(updates)
    config = runtime_settings_service.update_strm_config(updates)
    return {
        **config,
        "archive_output_cid": runtime_settings_service.get_archive_output_cid(),
        "archive_output_name": runtime_settings_service.get_archive_output_name(),
        "mount_paths": strm_service.detect_mount_paths(),
        "suggested_base_url": f"http://{strm_service.detect_local_ip()}:9008",
        "runtime": strm_service.get_runtime_status(),
    }


@router.post("/generate")
async def generate_strm_files():
    try:
        return await strm_service.start_generate_library(trigger="manual")
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
        return await strm_service.resolve_play_response_with_headers(
            token=token,
            method=request.method,
            request_headers=dict(request.headers),
        )
    except Exception as exc:
        _raise_strm_error(exc)
