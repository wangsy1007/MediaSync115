import asyncio
import base64
import io
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.hdhive_service import hdhive_service
from app.services.nullbr_service import nullbr_service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.subscription_scheduler_service import subscription_scheduler_service
from app.services.emby_sync_index_service import emby_sync_index_service
from app.services.emby_sync_scheduler_service import emby_sync_scheduler_service
from app.services.tg_sync_service import tg_sync_service
from app.services.tg_service import tg_service
from app.services.tmdb_service import tmdb_service
from app.services.emby_service import emby_service
from app.utils.proxy import proxy_manager

try:
    import qrcode

    QRCODE_AVAILABLE = True
except Exception:
    qrcode = None  # type: ignore[assignment]
    QRCODE_AVAILABLE = False


router = APIRouter(prefix="/settings", tags=["settings"])


class RuntimeSettingsRequest(BaseModel):
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    all_proxy: Optional[str] = None
    socks_proxy: Optional[str] = None
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
    tg_index_enabled: Optional[bool] = None
    tg_index_realtime_fallback_enabled: Optional[bool] = None
    tg_index_query_limit_per_channel: Optional[int] = None
    tg_backfill_batch_size: Optional[int] = None
    tg_incremental_interval_minutes: Optional[int] = None
    tmdb_api_key: Optional[str] = None
    tmdb_base_url: Optional[str] = None
    tmdb_image_base_url: Optional[str] = None
    tmdb_language: Optional[str] = None
    tmdb_region: Optional[str] = None
    emby_url: Optional[str] = None
    emby_api_key: Optional[str] = None
    emby_sync_enabled: Optional[bool] = None
    emby_sync_interval_hours: Optional[int] = None
    subscription_nullbr_enabled: Optional[bool] = None
    subscription_nullbr_interval_hours: Optional[int] = None
    subscription_nullbr_run_time: Optional[str] = None
    subscription_hdhive_enabled: Optional[bool] = None
    subscription_hdhive_interval_hours: Optional[int] = None
    subscription_hdhive_run_time: Optional[str] = None
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


class TgVerifyPasswordRequest(BaseModel):
    password: str
    session: str


class TgQrStatusRequest(BaseModel):
    token: str


class TgImportSessionRequest(BaseModel):
    session: str


class TgIndexBackfillRequest(BaseModel):
    rebuild: Optional[bool] = False


def _build_qr_image_data_url(content: str) -> str:
    if not QRCODE_AVAILABLE:
        return ""
    value = str(content or "").strip()
    if not value:
        return ""
    try:
        image = qrcode.make(value)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


def _build_qr_image_url(content: str) -> str:
    value = str(content or "").strip()
    if not value:
        return ""
    return f"https://api.qrserver.com/v1/create-qr-code/?size=320x320&data={quote(value, safe='')}"


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


def _validate_emby_sync_settings(merged_settings: dict) -> None:
    enabled = bool(merged_settings.get("emby_sync_enabled", False))
    if not enabled:
        return
    emby_url = str(merged_settings.get("emby_url") or "").strip()
    emby_api_key = str(merged_settings.get("emby_api_key") or "").strip()
    if not emby_url or not emby_api_key:
        raise HTTPException(status_code=400, detail="启用 Emby 定时同步前必须先配置 Emby URL 和 API Key")
    try:
        interval_hours = int(merged_settings.get("emby_sync_interval_hours", 24) or 24)
    except Exception:
        interval_hours = 0
    if interval_hours < 1:
        raise HTTPException(status_code=400, detail="Emby 同步间隔必须大于等于 1 小时")


@router.get("/runtime")
async def get_runtime_settings():
    return runtime_settings_service.get_all()


@router.put("/runtime")
async def update_runtime_settings(request: RuntimeSettingsRequest):
    payload = request.model_dump(exclude_unset=True)
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
    if any(key in payload for key in {"emby_url", "emby_api_key", "emby_sync_enabled", "emby_sync_interval_hours"}):
        _validate_emby_sync_settings(merged_settings)
    try:
        updated = runtime_settings_service.update_bulk(payload)
        await subscription_scheduler_service.ensure_subscription_tasks()
        await emby_sync_scheduler_service.ensure_sync_task()
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


@router.get("/tmdb/check")
async def check_tmdb_credentials():
    """检查 TMDB API 配置是否有效"""
    try:
        # 尝试搜索一个常见电影来验证 API 密钥
        result = await tmdb_service.search_multi("Inception", page=1)
        items = result.get("items", [])
        return {
            "valid": True,
            "message": "TMDB API 配置可用",
            "search_results_count": len(items),
            "sample_result": items[0] if items else None,
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "search_results_count": 0,
            "sample_result": None,
        }


@router.get("/pansou/check")
async def check_pansou_credentials():
    """检查 Pansou 服务是否可用"""
    try:
        health = await pansou_service.health_check()
        is_healthy = health.get("status") == "healthy"
        return {
            "valid": is_healthy,
            "message": "Pansou 服务可用" if is_healthy else f"Pansou 服务异常: {health.get('error', '未知错误')}",
            "health": health,
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "health": None,
        }


@router.get("/emby/check")
async def check_emby_credentials(
    emby_url: Optional[str] = None,
    emby_api_key: Optional[str] = None,
):
    custom_url = str(emby_url or "").strip()
    custom_key = str(emby_api_key or "").strip()
    if custom_url and custom_key:
        payload = await emby_service.check_connection_with_config(custom_url, custom_key)
    else:
        payload = await emby_service.check_connection()
    return payload


@router.get("/emby/sync/status")
async def get_emby_sync_status():
    status = await emby_sync_index_service.get_status()
    return {
        **status,
        "configured": bool(runtime_settings_service.get_emby_url() and runtime_settings_service.get_emby_api_key()),
    }


@router.post("/emby/sync/run")
async def run_emby_sync():
    result = await emby_sync_index_service.start_background_sync(trigger="manual")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "Emby 同步启动失败")
    return result


@router.get("/proxy")
async def get_proxy_config():
    """获取当前代理配置。"""
    config = proxy_manager.get_current_config()
    return {
        "http_proxy": config.get("http_proxy") or "",
        "https_proxy": config.get("https_proxy") or "",
        "all_proxy": config.get("all_proxy") or "",
        "socks_proxy": config.get("socks_proxy") or "",
        "has_proxy": any([
            config.get("http_proxy"),
            config.get("https_proxy"),
            config.get("all_proxy"),
            config.get("socks_proxy"),
        ]),
    }


@router.get("/health/all")
async def check_all_services_health():
    """统一检查所有服务的健康状态"""
    results = {
        "nullbr": {"checking": True},
        "hdhive": {"checking": True},
        "tg": {"checking": True},
        "tmdb": {"checking": True},
        "pansou": {"checking": True},
        "emby": {"checking": True},
    }

    # 检查 Nullbr
    try:
        nullbr_info = await asyncio.to_thread(nullbr_service.get_user_info)
        results["nullbr"] = {
            "valid": True,
            "message": "Nullbr 凭证可用",
            "user": nullbr_info,
        }
    except Exception as exc:
        results["nullbr"] = {
            "valid": False,
            "message": str(exc),
            "user": None,
        }

    # 检查 HDHive
    try:
        hdhive_info = await hdhive_service.get_user_info()
        results["hdhive"] = {
            "valid": True,
            "message": "HDHive 凭证可用",
            "user": hdhive_info,
        }
    except Exception as exc:
        results["hdhive"] = {
            "valid": False,
            "message": str(exc),
            "user": None,
        }

    # 检查 Telegram
    try:
        tg_payload = await tg_service.check_connection()
        tg_authorized = bool(tg_payload.get("authorized"))
        results["tg"] = {
            "valid": tg_authorized,
            "message": str(tg_payload.get("message") or ("Telegram 凭证可用" if tg_authorized else "Telegram 未登录")),
            "user": tg_payload.get("user"),
            "channels": tg_payload.get("channels") or [],
        }
    except Exception as exc:
        results["tg"] = {
            "valid": False,
            "message": str(exc),
            "user": None,
            "channels": [],
        }

    # 检查 TMDB
    try:
        tmdb_result = await tmdb_service.search_multi("Inception", page=1)
        tmdb_items = tmdb_result.get("items", [])
        results["tmdb"] = {
            "valid": True,
            "message": "TMDB API 配置可用",
            "search_results_count": len(tmdb_items),
        }
    except Exception as exc:
        results["tmdb"] = {
            "valid": False,
            "message": str(exc),
            "search_results_count": 0,
        }

    # 检查 Pansou
    try:
        pansou_health = await pansou_service.health_check()
        pansou_healthy = pansou_health.get("status") == "healthy"
        results["pansou"] = {
            "valid": pansou_healthy,
            "message": "Pansou 服务可用" if pansou_healthy else f"Pansou 服务异常",
            "health": pansou_health,
        }
    except Exception as exc:
        results["pansou"] = {
            "valid": False,
            "message": str(exc),
            "health": None,
        }

    # 检查 Emby
    try:
        emby_payload = await emby_service.check_connection()
        results["emby"] = {
            "valid": bool(emby_payload.get("valid")),
            "message": str(emby_payload.get("message") or ""),
            "user": emby_payload.get("user"),
        }
    except Exception as exc:
        results["emby"] = {
            "valid": False,
            "message": str(exc),
            "user": None,
        }

    # 计算整体状态
    all_valid = all(r.get("valid") for r in results.values())
    valid_count = sum(1 for r in results.values() if r.get("valid"))

    return {
        "all_valid": all_valid,
        "valid_count": valid_count,
        "total_count": len(results),
        "services": results,
        "proxy": await get_proxy_config(),
    }


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


@router.post("/tg/login/qr/start")
async def start_tg_qr_login():
    try:
        result = await tg_service.start_qr_login()
        qr_url = str(result.get("url") or "")
        qr_image_data_url = _build_qr_image_data_url(qr_url)
        return {
            "success": True,
            "token": result.get("token"),
            "url": qr_url,
            "qr_image_data_url": qr_image_data_url,
            "qr_image_url": "" if qr_image_data_url else _build_qr_image_url(qr_url),
            "expires_at": result.get("expires_at"),
            "expire_seconds": result.get("expire_seconds"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/login/qr/status")
async def check_tg_qr_login_status(payload: TgQrStatusRequest):
    token = str(payload.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="二维码会话标识不能为空")
    try:
        result = await tg_service.check_qr_login_status(token)
        if result.get("authorized") and result.get("session"):
            runtime_settings_service.update_tg_session(str(result.get("session")))
        return {
            "success": True,
            "authorized": bool(result.get("authorized", False)),
            "pending": bool(result.get("pending", False)),
            "need_password": bool(result.get("need_password", False)),
            "session": str(result.get("session") or ""),
            "message": str(result.get("message") or ""),
            "user": result.get("user"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/login/session/import")
async def import_tg_session(payload: TgImportSessionRequest):
    session = str(payload.session or "").strip()
    if not session:
        raise HTTPException(status_code=400, detail="会话串不能为空")
    try:
        result = await tg_service.import_session(session)
        final_session = str(result.get("session") or "").strip()
        if final_session:
            runtime_settings_service.update_tg_session(final_session)
        return {
            "success": True,
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


@router.get("/tg/index/status")
async def get_tg_index_status():
    try:
        payload = await tg_sync_service.get_status()
        return {
            "success": True,
            "status": payload,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/index/backfill/start")
async def start_tg_index_backfill(payload: TgIndexBackfillRequest):
    try:
        job = await tg_sync_service.start_backfill(rebuild=bool(payload.rebuild))
        return {
            "success": True,
            "job": job,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/index/incremental/run")
async def run_tg_index_incremental():
    try:
        job = await tg_sync_service.run_incremental_once()
        return {
            "success": True,
            "job": job,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/tg/index/jobs/{job_id}")
async def get_tg_index_job(job_id: str):
    normalized = str(job_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="job_id 不能为空")
    try:
        job = await tg_sync_service.get_job(normalized)
        return {
            "success": True,
            "job": job,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tg/index/rebuild")
async def rebuild_tg_index():
    try:
        job = await tg_sync_service.start_backfill(rebuild=True)
        return {
            "success": True,
            "job": job,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
