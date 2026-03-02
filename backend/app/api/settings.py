import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.hdhive_service import hdhive_service
from app.services.nullbr_service import nullbr_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.subscription_scheduler_service import subscription_scheduler_service
from app.services.tg_service import tg_service


router = APIRouter(prefix="/settings", tags=["settings"])


class RuntimeSettingsRequest(BaseModel):
    hdhive_cookie: Optional[str] = None
    hdhive_base_url: Optional[str] = None
    pansou_base_url: Optional[str] = None
    nullbr_app_id: Optional[str] = None
    nullbr_api_key: Optional[str] = None
    nullbr_base_url: Optional[str] = None
    tg_api_id: Optional[str] = None
    tg_api_hash: Optional[str] = None
    tg_phone: Optional[str] = None
    tg_session: Optional[str] = None
    tg_proxy: Optional[str] = None
    tg_channel_usernames: Optional[list[str]] = None
    tg_search_days: Optional[int] = None
    tg_max_messages_per_channel: Optional[int] = None
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
    subscription_tg_enabled: Optional[bool] = None
    subscription_tg_interval_hours: Optional[int] = None
    subscription_tg_run_time: Optional[str] = None
    subscription_resource_priority: Optional[list[str]] = None
    subscription_hdhive_auto_unlock_enabled: Optional[bool] = None
    subscription_hdhive_unlock_max_points_per_item: Optional[int] = None
    subscription_hdhive_unlock_budget_points_per_run: Optional[int] = None
    subscription_hdhive_unlock_threshold_inclusive: Optional[bool] = None


class TgSendCodeRequest(BaseModel):
    phone: Optional[str] = None


class TgVerifyCodeRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: str
    session: str


class TgVerifyPasswordRequest(BaseModel):
    password: str
    session: str


def _normalize_subscription_priority(raw: object) -> list[str]:
    allowed = {"nullbr", "hdhive", "pansou", "tg"}
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
        elif source == "hdhive":
            cookie = str(merged_settings.get("hdhive_cookie") or "").strip()
            base_url = str(merged_settings.get("hdhive_base_url") or "").strip()
            if not cookie or not base_url:
                errors.append("HDHive 优先级已启用，但缺少 Cookie 或 Base URL 配置")
        elif source == "pansou":
            base_url = str(merged_settings.get("pansou_base_url") or "").strip()
            if not base_url:
                errors.append("Pansou 优先级已启用，但缺少服务地址配置")
        elif source == "tg":
            tg_enabled = bool(merged_settings.get("subscription_tg_enabled", False))
            if not tg_enabled:
                continue
            tg_api_id = str(merged_settings.get("tg_api_id") or "").strip()
            tg_api_hash = str(merged_settings.get("tg_api_hash") or "").strip()
            tg_session = str(merged_settings.get("tg_session") or "").strip()
            channels = merged_settings.get("tg_channel_usernames") or []
            if not tg_api_id or not tg_api_hash:
                errors.append("Telegram 优先级已启用，但缺少 API ID / API HASH 配置")
            if not tg_session:
                errors.append("Telegram 优先级已启用，但账号尚未登录")
            if not channels:
                errors.append("Telegram 优先级已启用，但未配置频道列表")

    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))


def _validate_hdhive_unlock_settings(merged_settings: dict) -> None:
    enabled = bool(merged_settings.get("subscription_hdhive_auto_unlock_enabled", False))
    if not enabled:
        return

    cookie = str(merged_settings.get("hdhive_cookie") or "").strip()
    base_url = str(merged_settings.get("hdhive_base_url") or "").strip()
    if not cookie or not base_url:
        raise HTTPException(status_code=400, detail="启用 HDHive 自动解锁时必须配置 HDHive Cookie 和 Base URL")

    try:
        max_points_per_item = int(merged_settings.get("subscription_hdhive_unlock_max_points_per_item", 0) or 0)
    except Exception:
        max_points_per_item = 0
    if max_points_per_item < 1:
        raise HTTPException(status_code=400, detail="HDHive 自动解锁单条积分阈值必须大于等于 1")

    try:
        budget_points = int(merged_settings.get("subscription_hdhive_unlock_budget_points_per_run", 0) or 0)
    except Exception:
        budget_points = 0
    if budget_points < 1:
        raise HTTPException(status_code=400, detail="HDHive 自动解锁任务积分预算必须大于等于 1")


@router.get("/runtime")
async def get_runtime_settings():
    return runtime_settings_service.get_all()


@router.put("/runtime")
async def update_runtime_settings(request: RuntimeSettingsRequest):
    payload = request.model_dump(exclude_none=True)
    merged_settings = runtime_settings_service.get_all()
    merged_settings.update(payload)
    if "subscription_resource_priority" in payload:
        await _validate_priority_source_config(merged_settings)
    unlock_keys = {
        "subscription_hdhive_auto_unlock_enabled",
        "subscription_hdhive_unlock_max_points_per_item",
        "subscription_hdhive_unlock_budget_points_per_run",
        "subscription_hdhive_unlock_threshold_inclusive",
    }
    if any(key in payload for key in unlock_keys) or payload.get("hdhive_cookie") is not None:
        _validate_hdhive_unlock_settings(merged_settings)
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


@router.get("/tg/check")
async def check_tg_credentials():
    try:
        payload = await tg_service.check_connection()
        authorized = bool(payload.get("authorized"))
        return {
            "valid": authorized,
            "message": str(payload.get("message") or ("Telegram 凭证可用" if authorized else "Telegram 未登录")),
            "user": payload.get("user"),
            "channels": payload.get("channels") or [],
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "user": None,
            "channels": [],
        }


@router.post("/tg/login/send-code")
async def send_tg_login_code(payload: TgSendCodeRequest):
    phone = str(payload.phone or runtime_settings_service.get_tg_phone() or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请先配置手机号")
    try:
        result = await tg_service.send_login_code(phone)
        return {
            "success": True,
            "phone": result.get("phone"),
            "phone_code_hash": result.get("phone_code_hash"),
            "session": result.get("session"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/login/verify-code")
async def verify_tg_login_code(payload: TgVerifyCodeRequest):
    phone = str(payload.phone or "").strip()
    code = str(payload.code or "").strip()
    phone_code_hash = str(payload.phone_code_hash or "").strip()
    session = str(payload.session or "").strip()
    if not phone or not code or not phone_code_hash or not session:
        raise HTTPException(status_code=400, detail="手机号、验证码、会话信息不能为空")

    try:
        result = await tg_service.verify_login_code(
            phone=phone,
            code=code,
            phone_code_hash=phone_code_hash,
            session=session,
        )
        response = {
            "success": True,
            "need_password": bool(result.get("need_password", False)),
            "session": str(result.get("session") or ""),
            "user": result.get("user"),
        }
        if not response["need_password"] and response["session"]:
            runtime_settings_service.update_tg_session(response["session"])
        return response
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/login/verify-password")
async def verify_tg_login_password(payload: TgVerifyPasswordRequest):
    password = str(payload.password or "").strip()
    session = str(payload.session or "").strip()
    if not password or not session:
        raise HTTPException(status_code=400, detail="密码和会话信息不能为空")
    try:
        result = await tg_service.verify_login_password(password=password, session=session)
        final_session = str(result.get("session") or "").strip()
        if final_session:
            runtime_settings_service.update_tg_session(final_session)
        return {
            "success": True,
            "need_password": False,
            "session": final_session,
            "user": result.get("user"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/logout")
async def logout_tg():
    try:
        await tg_service.logout()
    except Exception:
        # Ignore remote logout failures and clear local session anyway.
        pass
    runtime_settings_service.clear_tg_session()
    return {"success": True}
