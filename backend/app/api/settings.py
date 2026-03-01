import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.runtime_settings_service import runtime_settings_service
from app.services.hdhive_service import hdhive_service
from app.services.nullbr_service import nullbr_service
from app.services.pansou_service import pansou_service
from app.services.subscription_scheduler_service import subscription_scheduler_service


router = APIRouter(prefix="/settings", tags=["settings"])


class RuntimeSettingsRequest(BaseModel):
    hdhive_cookie: Optional[str] = None
    hdhive_base_url: Optional[str] = None
    pansou_base_url: Optional[str] = None
    nullbr_app_id: Optional[str] = None
    nullbr_api_key: Optional[str] = None
    nullbr_base_url: Optional[str] = None
    tmdb_api_key: Optional[str] = None
    tmdb_base_url: Optional[str] = None
    tmdb_image_base_url: Optional[str] = None
    tmdb_language: Optional[str] = None
    tmdb_region: Optional[str] = None
    subscription_nullbr_enabled: Optional[bool] = None
    subscription_nullbr_interval_hours: Optional[int] = None
    subscription_nullbr_run_time: Optional[str] = None
    subscription_pansou_enabled: Optional[bool] = None
    subscription_pansou_interval_hours: Optional[int] = None
    subscription_pansou_run_time: Optional[str] = None
    subscription_resource_priority: Optional[list[str]] = None


def _normalize_subscription_priority(raw: object) -> list[str]:
    allowed = {"nullbr", "hdhive", "pansou"}
    source_items: list[str] = []
    if isinstance(raw, list):
        source_items = [str(item or "").strip().lower() for item in raw]
    elif isinstance(raw, str):
        source_items = [part.strip().lower() for part in raw.split(",")]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in source_items:
        if item in allowed and item not in seen:
            normalized.append(item)
            seen.add(item)

    return normalized or list(runtime_settings_service.get_subscription_resource_priority())


async def _validate_priority_source_config(merged_settings: dict) -> None:
    priority = _normalize_subscription_priority(merged_settings.get("subscription_resource_priority"))
    errors: list[str] = []

    for source in priority:
        if source == "nullbr":
            app_id = str(merged_settings.get("nullbr_app_id") or "").strip()
            api_key = str(merged_settings.get("nullbr_api_key") or "").strip()
            base_url = str(merged_settings.get("nullbr_base_url") or "").strip()
            if not app_id or not api_key or not base_url:
                errors.append("Nullbr 优先级已启用，但缺少 APP ID / API Key / Base URL 配置")
                continue
            try:
                await asyncio.to_thread(nullbr_service.get_user_info)
            except Exception as exc:
                errors.append(f"Nullbr 连通性检测失败: {str(exc)[:200]}")
        elif source == "hdhive":
            cookie = str(merged_settings.get("hdhive_cookie") or "").strip()
            base_url = str(merged_settings.get("hdhive_base_url") or "").strip()
            if not cookie or not base_url:
                errors.append("HDHive 优先级已启用，但缺少 Cookie 或 Base URL 配置")
                continue
            try:
                await hdhive_service.get_user_info()
            except Exception as exc:
                errors.append(f"HDHive 连通性检测失败: {str(exc)[:200]}")
        elif source == "pansou":
            base_url = str(merged_settings.get("pansou_base_url") or "").strip()
            if not base_url:
                errors.append("Pansou 优先级已启用，但缺少服务地址配置")
                continue
            try:
                health = await pansou_service.health_check()
                status = str(health.get("status") or "")
                if status != "healthy":
                    errors.append(f"Pansou 连通性检测失败: {status or 'unknown'}")
            except Exception as exc:
                errors.append(f"Pansou 连通性检测失败: {str(exc)[:200]}")

    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))


@router.get("/runtime")
async def get_runtime_settings():
    return runtime_settings_service.get_all()


@router.put("/runtime")
async def update_runtime_settings(request: RuntimeSettingsRequest):
    payload = request.model_dump(exclude_none=True)
    if "subscription_resource_priority" in payload:
        merged_settings = runtime_settings_service.get_all()
        merged_settings.update(payload)
        await _validate_priority_source_config(merged_settings)
    try:
        updated = runtime_settings_service.update_bulk(payload)
        await subscription_scheduler_service.ensure_subscription_tasks()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "success": True,
        "settings": updated,
    }


@router.get("/nullbr/check")
async def check_nullbr_credentials():
    try:
        info = await asyncio.to_thread(nullbr_service.get_user_info)
        return {
            "valid": True,
            "message": "Nullbr 凭证可用",
            "user": info,
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "user": None,
        }


@router.get("/hdhive/check")
async def check_hdhive_credentials():
    try:
        info = await hdhive_service.get_user_info()
        return {
            "valid": True,
            "message": "HDHive 凭证可用",
            "user": info,
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "user": None,
        }
