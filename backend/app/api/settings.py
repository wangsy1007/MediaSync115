import asyncio
import base64
import io
import re
import time
from urllib.parse import quote, urlparse
from typing import Any, Optional

import httpx

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.services.hdhive_service import hdhive_service
from app.services.operation_log_service import operation_log_service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.app_metadata_service import app_metadata_service
from app.services.subscription_scheduler_service import subscription_scheduler_service
from app.services.hdhive_checkin_scheduler_service import (
    hdhive_checkin_scheduler_service,
)
from app.services.emby_sync_index_service import emby_sync_index_service
from app.services.emby_sync_scheduler_service import emby_sync_scheduler_service
from app.services.feiniu_sync_index_service import feiniu_sync_index_service
from app.services.feiniu_sync_scheduler_service import feiniu_sync_scheduler_service
from app.services.tg_sync_service import tg_sync_service
from app.services.tg_service import tg_service
from app.services.tmdb_service import tmdb_service
from app.services.update_check_service import update_check_service
from app.services.emby_service import emby_service
from app.services.feiniu_service import feiniu_service
from app.utils.proxy import proxy_manager

_SETTINGS_CHECK_CACHE_TTL_SECONDS = 300
_settings_check_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_settings_check_cache_lock = asyncio.Lock()

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
    hdhive_login_username: Optional[str] = None
    hdhive_auto_checkin_enabled: Optional[bool] = None
    hdhive_auto_checkin_mode: Optional[str] = None
    hdhive_auto_checkin_method: Optional[str] = None
    hdhive_auto_checkin_run_time: Optional[str] = None
    pansou_base_url: Optional[str] = None
    tg_api_id: Optional[str] = None
    tg_api_hash: Optional[str] = None
    tg_phone: Optional[str] = None
    tg_session: Optional[str] = None
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
    emby_sync_interval_minutes: Optional[int] = None
    feiniu_url: Optional[str] = None
    feiniu_secret: Optional[str] = None
    feiniu_api_key: Optional[str] = None
    feiniu_session_token: Optional[str] = None
    feiniu_sync_enabled: Optional[bool] = None
    feiniu_sync_interval_hours: Optional[int] = None
    feiniu_sync_interval_minutes: Optional[int] = None
    subscription_enabled: Optional[bool] = None
    subscription_interval_hours: Optional[int] = None
    subscription_resource_priority: Optional[list[str]] = None
    subscription_hdhive_auto_unlock_enabled: Optional[bool] = None
    subscription_hdhive_unlock_max_points_per_item: Optional[int] = None
    subscription_hdhive_unlock_budget_points_per_run: Optional[int] = None
    subscription_hdhive_unlock_threshold_inclusive: Optional[bool] = None
    subscription_hdhive_prefer_free: Optional[bool] = None
    resource_preferred_resolutions: Optional[list[str]] = None
    resource_preferred_hdr: Optional[list[str]] = None
    resource_preferred_codec: Optional[list[str]] = None
    resource_preferred_audio: Optional[list[str]] = None
    resource_preferred_subtitles: Optional[list[str]] = None
    resource_exclude_tags: Optional[list[str]] = None
    resource_min_size_gb: Optional[float] = None
    resource_max_size_gb: Optional[float] = None
    update_source_type: Optional[str] = None
    update_repository: Optional[str] = None
    tg_bot_token: Optional[str] = None
    tg_bot_enabled: Optional[bool] = None
    tg_bot_allowed_users: Optional[list] = None
    tg_bot_notify_chat_ids: Optional[list] = None
    tg_bot_hdhive_auto_unlock: Optional[bool] = None
    detail_visible_tabs: Optional[list[str]] = None
    license_key: Optional[str] = None
    subscription_offline_transfer_enabled: Optional[bool] = None
    chart_subscription_enabled: Optional[bool] = None
    chart_subscription_sources: Optional[list] = None
    chart_subscription_limit: Optional[int] = None
    chart_subscription_interval_hours: Optional[int] = None
    person_follow_enabled: Optional[bool] = None
    person_follow_interval_hours: Optional[int] = None
    person_follow_auto_subscribe: Optional[bool] = None


_SUBSCRIPTION_SCHEDULER_SETTING_KEYS = frozenset(
    {
        "subscription_enabled",
        "subscription_interval_hours",
        "subscription_resource_priority",
        "subscription_hdhive_auto_unlock_enabled",
        "subscription_hdhive_unlock_max_points_per_item",
        "subscription_hdhive_unlock_budget_points_per_run",
        "subscription_hdhive_unlock_threshold_inclusive",
        "subscription_hdhive_prefer_free",
        "subscription_offline_transfer_enabled",
    }
)
_CHART_SUBSCRIPTION_SETTING_KEYS = frozenset(
    {
        "chart_subscription_enabled",
        "chart_subscription_sources",
        "chart_subscription_limit",
        "chart_subscription_interval_hours",
    }
)
_PERSON_FOLLOW_SETTING_KEYS = frozenset(
    {
        "person_follow_enabled",
        "person_follow_interval_hours",
        "person_follow_auto_subscribe",
    }
)
_TG_INDEX_SETTING_KEYS = frozenset(
    {
        "tg_index_enabled",
        "tg_index_realtime_fallback_enabled",
        "tg_index_query_limit_per_channel",
        "tg_backfill_batch_size",
        "tg_incremental_interval_minutes",
        "tg_channel_usernames",
        "tg_search_days",
        "tg_max_messages_per_channel",
    }
)
_HDHIVE_CHECKIN_SETTING_KEYS = frozenset(
    {
        "hdhive_auto_checkin_enabled",
        "hdhive_auto_checkin_mode",
        "hdhive_auto_checkin_method",
        "hdhive_auto_checkin_run_time",
    }
)
_EMBY_SYNC_SETTING_KEYS = frozenset(
    {
        "emby_url",
        "emby_api_key",
        "emby_sync_enabled",
        "emby_sync_interval_hours",
        "emby_sync_interval_minutes",
    }
)
_FEINIU_SYNC_SETTING_KEYS = frozenset(
    {
        "feiniu_url",
        "feiniu_secret",
        "feiniu_api_key",
        "feiniu_session_token",
        "feiniu_sync_enabled",
        "feiniu_sync_interval_hours",
        "feiniu_sync_interval_minutes",
    }
)
_TG_BOT_SETTING_KEYS = frozenset(
    {
        "tg_bot_token",
        "tg_bot_enabled",
        "tg_bot_allowed_users",
        "tg_bot_notify_chat_ids",
        "tg_bot_hdhive_auto_unlock",
    }
)


class TgVerifyPasswordRequest(BaseModel):
    password: str
    session: str


class TgQrStatusRequest(BaseModel):
    token: str


class TgIndexBackfillRequest(BaseModel):
    rebuild: Optional[bool] = False


class TgIndexStopRequest(BaseModel):
    job_type: str


class HDHiveCheckinRequest(BaseModel):
    mode: Optional[str] = None
    method: Optional[str] = None
    cookie: Optional[str] = None
    base_url: Optional[str] = None


class HDHiveLoginRequest(BaseModel):
    username: str
    password: str
    base_url: Optional[str] = None


class FeiniuLoginRequest(BaseModel):
    username: str
    password: str
    url: Optional[str] = None


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
    allowed = {"hdhive", "pansou", "tg"}
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

    return normalized or list(
        runtime_settings_service.get_subscription_resource_priority()
    )


async def _validate_priority_source_config(merged_settings: dict) -> None:
    priority = _normalize_subscription_priority(
        merged_settings.get("subscription_resource_priority")
    )
    errors: list[str] = []

    for source in priority:
        if source == "hdhive":
            base_url = str(merged_settings.get("hdhive_base_url") or "").strip()
            if not base_url:
                errors.append("HDHive 优先级已启用，但缺少 Base URL 配置")
            elif not runtime_settings_service.has_hdhive_credentials(merged_settings):
                errors.append("HDHive 优先级已启用，但缺少 Cookie 或账号密码配置")
        elif source == "pansou":
            base_url = str(merged_settings.get("pansou_base_url") or "").strip()
            if not base_url:
                errors.append("Pansou 优先级已启用，但缺少服务地址配置")
        elif source == "tg":
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
    enabled = bool(
        merged_settings.get("subscription_hdhive_auto_unlock_enabled", False)
    )
    if not enabled:
        return

    base_url = str(merged_settings.get("hdhive_base_url") or "").strip()
    if not base_url or not runtime_settings_service.has_hdhive_credentials(merged_settings):
        raise HTTPException(
            status_code=400,
            detail="启用 HDHive 自动解锁时必须配置 Base URL，以及 Cookie 或账号密码",
        )

    try:
        max_points_per_item = int(
            merged_settings.get("subscription_hdhive_unlock_max_points_per_item", 0)
            or 0
        )
    except Exception:
        max_points_per_item = 0
    if max_points_per_item < 1:
        raise HTTPException(
            status_code=400, detail="HDHive 自动解锁单条积分阈值必须大于等于 1"
        )

    try:
        budget_points = int(
            merged_settings.get("subscription_hdhive_unlock_budget_points_per_run", 0)
            or 0
        )
    except Exception:
        budget_points = 0
    if budget_points < 1:
        raise HTTPException(
            status_code=400, detail="HDHive 自动解锁任务积分预算必须大于等于 1"
        )


def _validate_hdhive_checkin_settings(merged_settings: dict) -> None:
    enabled = bool(merged_settings.get("hdhive_auto_checkin_enabled", False))
    if not enabled:
        return

    method = (
        str(merged_settings.get("hdhive_auto_checkin_method") or "cookie").strip().lower()
    )
    base_url = str(merged_settings.get("hdhive_base_url") or "").strip()

    if method in {"api", "web"}:
        if not base_url or not runtime_settings_service.has_hdhive_credentials(merged_settings):
            raise HTTPException(
                status_code=400,
                detail="使用网页签到时必须配置 HDHive Base URL，以及 Cookie 或账号密码",
            )
    elif method == "cookie":
        if not base_url or not runtime_settings_service.has_hdhive_credentials(merged_settings):
            raise HTTPException(
                status_code=400,
                detail="使用 Cookie 签到时必须配置 HDHive Base URL，以及 Cookie 或账号密码",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="HDHive 自动签到方式仅支持 cookie 或 web",
        )

    mode = (
        str(merged_settings.get("hdhive_auto_checkin_mode") or "normal").strip().lower()
    )
    if mode not in {"normal", "gamble"}:
        raise HTTPException(
            status_code=400, detail="HDHive 自动签到模式仅支持 normal 或 gamble"
        )

    run_time = str(merged_settings.get("hdhive_auto_checkin_run_time") or "").strip()
    if not run_time or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", run_time):
        raise HTTPException(
            status_code=400, detail="HDHive 自动签到执行时间格式必须为 HH:mm"
        )


def _validate_emby_sync_settings(merged_settings: dict) -> None:
    enabled = bool(merged_settings.get("emby_sync_enabled", False))
    if not enabled:
        return
    emby_url = str(merged_settings.get("emby_url") or "").strip()
    emby_api_key = str(merged_settings.get("emby_api_key") or "").strip()
    if not emby_url or not emby_api_key:
        raise HTTPException(
            status_code=400, detail="启用 Emby 定时同步前必须先配置 Emby URL 和 API Key"
        )
    try:
        interval_minutes = int(merged_settings.get("emby_sync_interval_minutes", 1440) or merged_settings.get("emby_sync_interval_hours", 24) or 1440)
    except Exception:
        interval_minutes = 0
    # 兼容旧版 hours：如果值 <= 168 视为小时，转换为分钟
    if 0 < interval_minutes <= 168:
        interval_minutes = interval_minutes * 60
    if interval_minutes < 15:
        raise HTTPException(status_code=400, detail="Emby 同步间隔必须大于等于 15 分钟")


def _validate_feiniu_sync_settings(merged_settings: dict) -> None:
    enabled = bool(merged_settings.get("feiniu_sync_enabled", False))
    if not enabled:
        return
    if not runtime_settings_service.has_feiniu_sync_credentials(merged_settings):
        raise HTTPException(
            status_code=400,
            detail="启用飞牛定时同步前必须先配置 URL 并完成登录",
        )
    try:
        interval_minutes = int(
            merged_settings.get("feiniu_sync_interval_minutes", 1440) or merged_settings.get("feiniu_sync_interval_hours", 24) or 1440
        )
    except Exception:
        interval_minutes = 0
    # 兼容旧版 hours：如果值 <= 168 视为小时，转换为分钟
    if 0 < interval_minutes <= 168:
        interval_minutes = interval_minutes * 60
    if interval_minutes < 15:
        raise HTTPException(status_code=400, detail="飞牛同步间隔必须大于等于 15 分钟")


@router.get("/runtime")
async def get_runtime_settings():
    return runtime_settings_service.get_all()


def _build_health_service_payload(
    *,
    valid: bool,
    message: str,
    target: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": "ok" if valid else "error",
        "valid": bool(valid),
        "message": str(message or "").strip() or ("连接正常" if valid else "连接失败"),
        "target": target,
    }
    if extra:
        payload.update(extra)
    return payload


def _build_proxy_health_payload(
    *,
    status: str,
    valid: bool,
    message: str,
    target: str,
    applied_proxy: str = "",
    proxy_scheme: str = "",
    status_code: int | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "valid": bool(valid),
        "message": str(message or "").strip() or ("连接正常" if valid else "连接失败"),
        "target": str(target or "").strip(),
        "applied_proxy": str(applied_proxy or "").strip(),
        "proxy_scheme": str(proxy_scheme or "").strip(),
        "status_code": status_code,
        "latency_ms": latency_ms,
    }


def _extract_proxy_scheme(proxy_url: str) -> str:
    return str(urlparse(str(proxy_url or "").strip()).scheme or "").strip().lower()


def _resolve_health_probe_route(scheme: str) -> dict[str, str]:
    """解析健康检查实际走应用代理还是系统网络（含路由器全局代理）。"""
    configured_proxy = str(proxy_manager.get_proxy_for_scheme(scheme) or "").strip()
    uses_app_proxy = bool(configured_proxy) and proxy_manager._should_apply_proxy_mounts()
    if uses_app_proxy:
        return {
            "route_mode": "configured",
            "applied_proxy": configured_proxy,
            "proxy_scheme": _extract_proxy_scheme(configured_proxy),
            "route_hint": "应用代理",
        }
    if configured_proxy:
        return {
            "route_mode": "system",
            "applied_proxy": "",
            "proxy_scheme": "system",
            "route_hint": "系统网络（应用代理不可达，已改走系统路由）",
        }
    return {
        "route_mode": "system",
        "applied_proxy": "",
        "proxy_scheme": "system",
        "route_hint": "系统网络（未配置应用代理，含路由器全局代理）",
    }


async def _probe_target_health(
    *,
    target: str,
    not_configured_message: str,
) -> dict[str, Any]:
    normalized_target = str(target or "").strip()
    if not normalized_target:
        return _build_proxy_health_payload(
            status="not_configured",
            valid=False,
            message=not_configured_message,
            target="",
        )

    parsed_target = urlparse(normalized_target)
    scheme = str(parsed_target.scheme or "").strip().lower()
    if scheme not in {"http", "https"} or not parsed_target.netloc:
        return _build_proxy_health_payload(
            status="error",
            valid=False,
            message="目标地址无效",
            target=normalized_target,
        )

    route = _resolve_health_probe_route(scheme)
    applied_proxy = route["applied_proxy"]
    proxy_scheme = route["proxy_scheme"]
    route_hint = route["route_hint"]

    try:
        async with proxy_manager.create_httpx_client(
            timeout=10.0, follow_redirects=False
        ) as client:
            start = time.perf_counter()
            response = await client.get(normalized_target)
            latency_ms = int((time.perf_counter() - start) * 1000)
        status_code = int(response.status_code)
        if 200 <= status_code < 400:
            return _build_proxy_health_payload(
                status="ok",
                valid=True,
                message=f"连接正常 (HTTP {status_code}，{route_hint})",
                target=normalized_target,
                applied_proxy=applied_proxy,
                proxy_scheme=proxy_scheme,
                status_code=status_code,
                latency_ms=latency_ms,
            )
        return _build_proxy_health_payload(
            status="error",
            valid=False,
            message=f"连接异常 (HTTP {status_code}，{route_hint})",
            target=normalized_target,
            applied_proxy=applied_proxy,
            proxy_scheme=proxy_scheme,
            status_code=status_code,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        return _build_proxy_health_payload(
            status="error",
            valid=False,
            message=f"{str(exc) or '连接失败'}（{route_hint}）",
            target=normalized_target,
            applied_proxy=applied_proxy,
            proxy_scheme=proxy_scheme,
        )


async def _perform_hdhive_check_cached() -> dict[str, Any]:
    now = time.time()
    async with _settings_check_cache_lock:
        cached = _settings_check_cache.get("hdhive_check")
        if cached and cached[0] > now:
            return dict(cached[1])
    result = await _perform_hdhive_check()
    async with _settings_check_cache_lock:
        _settings_check_cache["hdhive_check"] = (
            time.time() + _SETTINGS_CHECK_CACHE_TTL_SECONDS,
            dict(result),
        )
    return result


async def _perform_tg_check_cached() -> dict[str, Any]:
    now = time.time()
    async with _settings_check_cache_lock:
        cached = _settings_check_cache.get("tg_check")
        if cached and cached[0] > now:
            return dict(cached[1])
    result = await _perform_tg_check()
    async with _settings_check_cache_lock:
        _settings_check_cache["tg_check"] = (
            time.time() + _SETTINGS_CHECK_CACHE_TTL_SECONDS,
            dict(result),
        )
    return result


def _invalidate_settings_check_cache() -> None:
    _settings_check_cache.clear()


async def _perform_hdhive_check() -> dict[str, Any]:
    try:
        payload = await hdhive_service.check_connection()
        return {
            "valid": True,
            "message": str(payload.get("message") or "HDHive 连接正常"),
            "user": payload.get("user"),
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "user": None,
        }


async def _perform_tg_check() -> dict[str, Any]:
    try:
        payload = await tg_service.check_connection()
        authorized = bool(payload.get("authorized"))
        return {
            "valid": authorized,
            "message": str(
                payload.get("message")
                or ("Telegram 凭证可用" if authorized else "Telegram 未登录")
            ),
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


async def _perform_tmdb_check() -> dict[str, Any]:
    try:
        result = await tmdb_service.check_connection()
        return {
            "valid": True,
            "message": "TMDB API 配置可用",
            "configuration": result.get("configuration"),
            "images_configured": bool(result.get("images_configured")),
            "change_keys_count": int(result.get("change_keys_count") or 0),
        }
    except Exception as exc:
        return {
            "valid": False,
            "message": str(exc),
            "configuration": None,
            "images_configured": False,
            "change_keys_count": 0,
        }


def _validate_update_source_settings(merged_settings: dict[str, Any]) -> None:
    source_type = (
        str(merged_settings.get("update_source_type") or "official").strip().lower()
    )
    repository = str(merged_settings.get("update_repository") or "").strip()
    try:
        update_check_service.normalize_repository(source_type, repository)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/runtime")
async def update_runtime_settings(
    request: RuntimeSettingsRequest,
    background_tasks: BackgroundTasks,
):
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
    if any(key in payload for key in unlock_keys):
        _validate_hdhive_unlock_settings(merged_settings)
    checkin_keys = {
        "hdhive_auto_checkin_enabled",
        "hdhive_auto_checkin_mode",
        "hdhive_auto_checkin_method",
        "hdhive_auto_checkin_run_time",
    }
    if any(key in payload for key in checkin_keys):
        _validate_hdhive_checkin_settings(merged_settings)
    if any(
        key in payload
        for key in {
            "emby_url",
            "emby_api_key",
            "emby_sync_enabled",
            "emby_sync_interval_hours",
            "emby_sync_interval_minutes",
        }
    ):
        _validate_emby_sync_settings(merged_settings)
    if any(
        key in payload
        for key in {
            "feiniu_url",
            "feiniu_session_token",
            "feiniu_sync_enabled",
            "feiniu_sync_interval_hours",
            "feiniu_sync_interval_minutes",
        }
    ):
        _validate_feiniu_sync_settings(merged_settings)
    if any(key in payload for key in {"update_source_type", "update_repository"}):
        _validate_update_source_settings(merged_settings)
    _invalidate_settings_check_cache()
    try:
        updated = runtime_settings_service.update_bulk(payload)
        payload_keys = set(payload.keys())
        # 仅同步与本次修改相关的调度任务，且不在保存时立即跑重任务（避免 504）
        if payload_keys & _SUBSCRIPTION_SCHEDULER_SETTING_KEYS:
            await subscription_scheduler_service.ensure_subscription_tasks(
                run_immediately=False
            )
        if payload_keys & _CHART_SUBSCRIPTION_SETTING_KEYS:
            await subscription_scheduler_service.ensure_chart_subscription_task(
                run_immediately=False
            )
        if payload_keys & _PERSON_FOLLOW_SETTING_KEYS:
            await subscription_scheduler_service.ensure_person_follow_task(
                run_immediately=False
            )
        if payload_keys & _TG_INDEX_SETTING_KEYS:
            await subscription_scheduler_service.ensure_tg_index_incremental_task()
        if payload_keys & _HDHIVE_CHECKIN_SETTING_KEYS:
            await hdhive_checkin_scheduler_service.ensure_checkin_task()
        if payload_keys & _EMBY_SYNC_SETTING_KEYS:
            await emby_sync_scheduler_service.ensure_sync_task()
        if payload_keys & _FEINIU_SYNC_SETTING_KEYS:
            await feiniu_sync_scheduler_service.ensure_sync_task()
        if payload_keys & _TG_BOT_SETTING_KEYS:
            background_tasks.add_task(_restart_tg_bot_background)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _secret_keys = {
        "hdhive_cookie",
        "hdhive_password_enc",
        "tg_session",
        "tg_api_hash",
        "tmdb_api_key",
        "emby_api_key",
        "feiniu_secret",
        "feiniu_api_key",
        "feiniu_session_token",
        "feiniu_password_enc",
        "tg_bot_token",
        "license_key",
    }
    safe_keys = [k for k in payload.keys() if k not in _secret_keys]
    redacted_keys = [k for k in payload.keys() if k in _secret_keys]
    summary_parts = safe_keys + [f"{k}(已脱敏)" for k in redacted_keys]
    await operation_log_service.log_background_event(
        source_type="api",
        module="settings",
        action="settings.update",
        status="success",
        message=f"运行时设置已更新：{', '.join(summary_parts[:10])}{'...' if len(summary_parts) > 10 else ''}",
        extra={"updated_keys": list(payload.keys())},
    )
    return {
        "success": True,
        "settings": updated,
    }


@router.get("/app-info")
async def get_app_info():
    metadata = app_metadata_service.get_current_metadata()
    return {
        **metadata,
        "update_source_type": runtime_settings_service.get_update_source_type(),
        "update_repository": runtime_settings_service.get_update_repository(),
    }


@router.get("/update-check")
async def check_updates():
    try:
        return await update_check_service.check(
            source_type=runtime_settings_service.get_update_source_type(),
            repository=runtime_settings_service.get_update_repository(),
        )
    except httpx.HTTPStatusError as exc:
        detail = f"DockerHub 检查失败 (HTTP {exc.response.status_code})"
        raise HTTPException(status_code=502, detail=detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"检查更新失败: {str(exc)}")


@router.get("/hdhive/check")
async def check_hdhive_credentials():
    return await _perform_hdhive_check_cached()


@router.post("/hdhive/login")
async def login_hdhive(payload: HDHiveLoginRequest):
    """登录 HDHive 并保存 Cookie 与加密密码。"""
    base_url = (
        str(payload.base_url or "").strip()
        or runtime_settings_service.get_hdhive_base_url()
    )
    username = str(payload.username or "").strip()
    password = str(payload.password or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入 HDHive 用户名和密码")

    from app.services.hdhive_service import HDHiveService
    from app.utils.credential_crypto import encrypt_credential

    service = HDHiveService(
        base_url=base_url,
        cookie=runtime_settings_service.get_hdhive_cookie(),
    )
    result = await service.login(username=username, password=password)
    if not result.get("success"):
        raise HTTPException(
            status_code=401,
            detail=str(result.get("message") or "HDHive 登录失败"),
        )

    cookie = str(result.get("cookie") or service.cookie or "").strip()
    updates: dict[str, str] = {
        "hdhive_login_username": username,
        "hdhive_password_enc": encrypt_credential(
            password,
            runtime_settings_service.get_auth_secret(),
        ),
    }
    if cookie:
        updates["hdhive_cookie"] = cookie
    if base_url:
        updates["hdhive_base_url"] = base_url

    runtime_settings_service.update_bulk(updates)
    user = result.get("user") if isinstance(result.get("user"), dict) else {}
    return {
        "success": True,
        "message": str(result.get("message") or "登录成功"),
        "user": user,
        "username": username,
    }


@router.post("/hdhive/checkin")
async def run_hdhive_checkin(payload: HDHiveCheckinRequest):
    mode = (
        str(payload.mode or runtime_settings_service.get_hdhive_auto_checkin_mode())
        .strip()
        .lower()
    )
    if mode not in {"normal", "gamble"}:
        raise HTTPException(
            status_code=400, detail="HDHive 手动签到模式仅支持 normal 或 gamble"
        )

    method = (
        str(payload.method or runtime_settings_service.get_hdhive_auto_checkin_method())
        .strip()
        .lower()
    )
    if method not in {"api", "cookie", "web"}:
        method = "cookie"
    if method == "api":
        method = "web"

    cookie = str(payload.cookie or "").strip()
    base_url = str(payload.base_url or "").strip()
    service = hdhive_service
    if cookie or base_url:
        from app.services.hdhive_service import HDHiveService

        service = HDHiveService(
            base_url=base_url or runtime_settings_service.get_hdhive_base_url(),
            cookie=cookie or runtime_settings_service.get_hdhive_cookie(),
        )

    try:
        if method == "cookie":
            return await service.check_in_by_cookie(gamble=(mode == "gamble"))
        return await service.check_in(gamble=(mode == "gamble"))
    except Exception as exc:
        from app.services.hdhive_service import HDHiveApiError

        if isinstance(exc, HDHiveApiError):
            status = int(exc.status_code or 500)
            detail = str(exc)
            if status in {400, 401, 402, 403, 404, 429}:
                raise HTTPException(status_code=status, detail=detail)
            raise HTTPException(
                status_code=502, detail=detail or f"HDHive 手动签到失败({status})"
            )
        raise HTTPException(status_code=500, detail=f"HDHive 手动签到失败: {str(exc)}")


@router.get("/tg/check")
async def check_tg_credentials():
    return await _perform_tg_check_cached()


@router.get("/tmdb/check")
async def check_tmdb_credentials():
    """检查 TMDB API 配置是否有效"""
    return await _perform_tmdb_check()


@router.get("/pansou/check")
async def check_pansou_credentials():
    """检查 Pansou 服务是否可用"""
    try:
        base_url = runtime_settings_service.get_pansou_base_url()
        health = await pansou_service.health_check(base_url=base_url)
        is_healthy = health.get("status") == "healthy"
        return {
            "valid": is_healthy,
            "message": "Pansou 服务可用"
            if is_healthy
            else f"Pansou 服务异常: {health.get('error', '未知错误')}",
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
        payload = await emby_service.check_connection_with_config(
            custom_url, custom_key
        )
    else:
        payload = await emby_service.check_connection()
    return payload


@router.get("/feiniu/check")
async def check_feiniu_credentials(
    feiniu_url: Optional[str] = None,
    feiniu_secret: Optional[str] = None,
    feiniu_api_key: Optional[str] = None,
):
    custom_url = str(feiniu_url or "").strip()
    custom_secret = str(feiniu_secret or "").strip()
    custom_key = str(feiniu_api_key or "").strip()
    if custom_url and custom_secret and custom_key:
        payload = await feiniu_service.check_connection_with_config(
            custom_url, custom_secret, custom_key
        )
    elif custom_url:
        feiniu_service.set_config(
            custom_url,
            runtime_settings_service.get_feiniu_secret(),
            runtime_settings_service.get_feiniu_api_key(),
        )
        payload = await feiniu_service.check_connection()
    else:
        payload = await feiniu_service.check_connection()
    return payload


@router.post("/feiniu/login")
async def login_feiniu(payload: FeiniuLoginRequest):
    """登录飞牛影视（HTTP v/api，nas-tools FnOSClient 模式）。"""
    feiniu_url = (
        str(payload.url or "").strip()
        if payload.url
        else runtime_settings_service.get_feiniu_url()
    )

    if not feiniu_url:
        raise HTTPException(
            status_code=400,
            detail="请先配置飞牛影视 URL",
        )

    username = str(payload.username or "").strip()
    password = str(payload.password or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入飞牛影视用户名和密码")

    feiniu_service.set_config(
        feiniu_url,
        runtime_settings_service.get_feiniu_secret(),
        runtime_settings_service.get_feiniu_api_key(),
    )
    result = await feiniu_service.login(username=username, password=password)

    if result.get("success") and result.get("token"):
        token = result["token"]
        user = result.get("user") if isinstance(result.get("user"), dict) else {}
        login_username = str(user.get("username") or username).strip()
        from app.utils.credential_crypto import encrypt_credential

        updates: dict[str, str] = {
            "feiniu_url": feiniu_url,
            "feiniu_session_token": token,
            "feiniu_login_username": login_username,
            "feiniu_password_enc": encrypt_credential(
                password,
                runtime_settings_service.get_auth_secret(),
            ),
        }
        runtime_settings_service.update_bulk(updates)
        feiniu_service.apply_runtime_config()
        return {
            "success": True,
            "message": result.get("message", "登录成功"),
            "token": token,
        }
    return {
        "success": False,
        "message": result.get(
            "message",
            "登录失败，请确认该账号可在飞牛影视 /v 页面登录",
        ),
        "token": None,
    }


@router.get("/emby/sync/status")
async def get_emby_sync_status():
    status = await emby_sync_index_service.get_status()
    return {
        **status,
        "configured": bool(
            runtime_settings_service.get_emby_url()
            and runtime_settings_service.get_emby_api_key()
        ),
    }


@router.post("/emby/sync/run")
async def run_emby_sync():
    result = await emby_sync_index_service.start_background_sync(trigger="manual")
    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("message") or "Emby 同步启动失败"
        )
    return result


@router.get("/feiniu/sync/status")
async def get_feiniu_sync_status():
    status = await feiniu_sync_index_service.get_status()
    return {
        **status,
        "configured": runtime_settings_service.has_feiniu_sync_credentials(),
    }


@router.post("/feiniu/sync/run")
async def run_feiniu_sync():
    result = await feiniu_sync_index_service.start_background_sync(trigger="manual")
    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("message") or "飞牛同步启动失败"
        )
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
        "has_proxy": any(
            [
                config.get("http_proxy"),
                config.get("https_proxy"),
                config.get("all_proxy"),
                config.get("socks_proxy"),
            ]
        ),
    }


@router.get("/health/all")
async def check_all_services_health():
    """检测固定目标连通性：优先走应用内代理，否则走系统网络（含路由器全局代理）。"""
    tmdb_target = runtime_settings_service.get_tmdb_base_url()

    hdhive_result, tmdb_result, tg_result = await asyncio.gather(
        _probe_target_health(
            target="https://hdhive.com/",
            not_configured_message="",
        ),
        _probe_target_health(
            target=tmdb_target,
            not_configured_message="未配置 TMDB Base URL",
        ),
        _probe_target_health(
            target="https://api.telegram.org",
            not_configured_message="",
        ),
    )

    results = {
        "hdhive": hdhive_result,
        "tmdb": tmdb_result,
        "tg": tg_result,
    }
    checked_results = [
        result
        for result in results.values()
        if result.get("status") != "not_configured"
    ]
    valid_count = sum(1 for result in checked_results if result.get("valid"))
    total_count = len(checked_results)
    all_valid = total_count > 0 and valid_count == total_count

    return {
        "all_valid": all_valid,
        "valid_count": valid_count,
        "total_count": total_count,
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
        result = await tg_service.verify_login_password(
            password=password, session=session
        )
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


@router.post("/tg/index/status/refresh")
async def refresh_tg_index_status():
    try:
        job = await tg_sync_service.start_status_refresh()
        return {
            "success": True,
            "job": job,
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


@router.post("/tg/index/stop")
async def stop_tg_index_job(payload: TgIndexStopRequest):
    try:
        return await tg_sync_service.stop_job(payload.job_type)
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


# ── TG Bot ────────────────────────────────────────────────


@router.get("/tg-bot/status")
async def get_tg_bot_status():
    from app.services.tg_bot import tg_bot_service

    return tg_bot_service.status()


async def _restart_tg_bot_background() -> None:
    from app.services.tg_bot import tg_bot_service

    try:
        await asyncio.wait_for(tg_bot_service.restart(), timeout=60.0)
        logger.info("TG Bot background restart finished, running=%s", tg_bot_service.running)
    except asyncio.TimeoutError:
        logger.error("TG Bot background restart timed out")
    except Exception:
        logger.exception("TG Bot background restart failed")


@router.post("/tg-bot/restart")
async def restart_tg_bot(background_tasks: BackgroundTasks):
    from app.services.tg_bot import tg_bot_service

    background_tasks.add_task(_restart_tg_bot_background)
    return {
        "success": True,
        "accepted": True,
        "message": "已在后台重启 Bot，请稍后点击「检测状态」确认",
        "running": tg_bot_service.running,
        "last_error": tg_bot_service.last_error,
    }


@router.post("/tg-bot/stop")
async def stop_tg_bot():
    from app.services.tg_bot import tg_bot_service

    await tg_bot_service.stop()
    return {"success": True, "running": False}


# ── 榜单订阅 ────────────────────────────────────────────────


@router.get("/chart-subscription/charts")
async def get_available_charts():
    from app.services.chart_subscription_service import get_available_charts

    return {"charts": get_available_charts()}


@router.post("/chart-subscription/run")
async def run_chart_subscription_now():
    from app.services.chart_subscription_service import run_chart_subscription

    try:
        result = await run_chart_subscription()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"榜单订阅执行失败: {str(exc)}")


@router.post("/person-follow/run")
async def run_person_follow_now():
    from app.services.person_follow_service import run_person_follow_sync

    try:
        result = await run_person_follow_sync()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"演职员关注同步失败: {str(exc)}")
