import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.runtime_settings_service import runtime_settings_service
from app.services.hdhive_service import hdhive_service
from app.services.nullbr_service import nullbr_service
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


@router.get("/runtime")
async def get_runtime_settings():
    return runtime_settings_service.get_all()


@router.put("/runtime")
async def update_runtime_settings(request: RuntimeSettingsRequest):
    try:
        updated = runtime_settings_service.update_bulk(request.model_dump(exclude_none=True))
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
