import json
import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api import (
    auth as auth_api,
    license as license_api,
    logs as logs_api,
    pan115,
    pansou,
    scheduler,
    search,
    settings as runtime_settings_api,
    subscriptions,
    workflow,
)
from app.scheduler import scheduler_manager
from app.services.auth_service import auth_service
from app.services.app_metadata_service import app_metadata_service
from app.services.explore_home_warmup_service import explore_home_warmup_service
from app.services.operation_log_service import operation_log_service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.emby_sync_scheduler_service import emby_sync_scheduler_service
from app.services.hdhive_checkin_scheduler_service import (
    hdhive_checkin_scheduler_service,
)
from app.services.subscription_scheduler_service import subscription_scheduler_service
from app.services.tg_bot import tg_bot_service

logger = logging.getLogger(__name__)


async def _safe_log_operation(**kwargs) -> None:
    try:
        await operation_log_service.log(**kwargs)
    except Exception:
        logger.exception("operation log failed")


async def _safe_log_api_request(**kwargs) -> None:
    try:
        await operation_log_service.log_api_request(**kwargs)
    except Exception:
        logger.exception("api operation log failed")


def _get_client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for", "")).strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    client = request.client
    return str(getattr(client, "host", "") or "unknown")


def _get_route_path(request: Request, fallback_path: str) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", "") if route else ""
    return str(route_path or fallback_path)


def _get_endpoint_name(request: Request) -> str:
    endpoint = request.scope.get("endpoint")
    return str(getattr(endpoint, "__name__", "") or "unknown")


def _extract_response_body_summary(response) -> dict | None:
    body = getattr(response, "body", None)
    if body in (None, b""):
        return None
    if not isinstance(body, (bytes, bytearray)):
        return {"body_preview": str(body)}

    content_type = str(
        getattr(response, "media_type", "") or response.headers.get("content-type", "")
    ).lower()
    payload = bytes(body)
    if len(payload) > 64 * 1024:
        return {"body_size": len(payload), "body_preview": "响应体过大，已省略"}
    if "application/json" in content_type:
        try:
            return {"body": json.loads(payload.decode("utf-8"))}
        except Exception:
            return {"body_text": payload.decode("utf-8", errors="ignore")}
    if content_type.startswith("text/"):
        return {"body_text": payload.decode("utf-8", errors="ignore")}
    return {"body_size": len(payload), "body_preview": "非文本响应，已省略内容"}


def _build_request_summary(request: Request) -> dict:
    session = getattr(request.state, "auth_session", None)
    return {
        "method": request.method,
        "path": request.url.path,
        "route_path": _get_route_path(request, request.url.path),
        "query": dict(request.query_params),
        "client": {
            "ip": _get_client_ip(request),
            "user_agent": request.headers.get("user-agent", ""),
            "timezone": request.headers.get("x-client-timezone", ""),
        },
        "auth": {
            "authenticated": bool(session),
            "username": (session or {}).get("username", "")
            if isinstance(session, dict)
            else "",
        },
        "headers": operation_log_service.redact_headers(
            {
                "content-type": request.headers.get("content-type", ""),
                "content-length": request.headers.get("content-length", ""),
                "referer": request.headers.get("referer", ""),
                "origin": request.headers.get("origin", ""),
            }
        ),
        "endpoint": _get_endpoint_name(request),
    }


def _build_response_summary(
    request: Request, response, trace_id: str, duration_ms: int
) -> dict:
    summary = {
        "status_code": response.status_code,
        "route_path": _get_route_path(request, request.url.path),
        "endpoint": _get_endpoint_name(request),
        "duration_ms": duration_ms,
        "headers": operation_log_service.redact_headers(
            {
                "content-type": response.headers.get("content-type", ""),
                "content-length": response.headers.get("content-length", ""),
                "location": response.headers.get("location", ""),
                "x-trace-id": trace_id,
            }
        ),
    }
    body_summary = _extract_response_body_summary(response)
    if body_summary:
        summary.update(body_summary)
    return summary


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    pansou_service.set_base_url(runtime_settings_service.get_pansou_base_url())
    await init_db()
    await operation_log_service.prune(days=30)
    await scheduler_manager.init()
    await subscription_scheduler_service.ensure_subscription_tasks()
    await subscription_scheduler_service.ensure_chart_subscription_task()
    await hdhive_checkin_scheduler_service.ensure_checkin_task()
    await emby_sync_scheduler_service.ensure_sync_task()
    await explore_home_warmup_service.warmup(force_refresh=False)
    await tg_bot_service.start()
    yield
    await tg_bot_service.stop()
    await scheduler_manager.stop()
    await pansou_service.close()


app = FastAPI(
    title=settings.APP_NAME,
    version=app_metadata_service.get_current_metadata()["current_version"],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


UNAUTHENTICATED_API_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/session",
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path or ""
    if not path.startswith("/api") or path in UNAUTHENTICATED_API_PATHS:
        return await call_next(request)

    session = auth_service.get_request_session(request)
    if not session:
        return JSONResponse(status_code=401, content={"detail": "请先登录"})
    request.state.auth_session = session
    return await call_next(request)


@app.middleware("http")
async def operation_logging_middleware(request: Request, call_next):
    path = request.url.path or ""
    if not path.startswith("/api") or path.startswith("/api/logs"):
        return await call_next(request)

    trace_id = request.headers.get("X-Trace-Id") or uuid4().hex
    started_at = time.perf_counter()
    module = operation_log_service._build_module(path)
    request_summary = _build_request_summary(request)

    content_type = str(request.headers.get("content-type", "")).lower()
    content_length = int(request.headers.get("content-length", "0") or "0")
    if "application/json" in content_type and 0 < content_length <= 1024 * 1024:
        body_bytes = await request.body()
        if body_bytes:

            async def receive() -> dict:
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request._receive = receive  # type: ignore[attr-defined]
            try:
                request_summary["body"] = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                request_summary["body"] = body_bytes.decode("utf-8", errors="ignore")

    await _safe_log_operation(
        trace_id=trace_id,
        source_type="api",
        module=module,
        action="api.request.start",
        status="info",
        message=(
            f"收到接口请求：{request.method} {path}，模块={module}，路由={request_summary['route_path']}，"
            f"处理函数={request_summary['endpoint']}，客户端={request_summary['client']['ip']}"
        ),
        http_method=request.method,
        path=path,
        request_summary=request_summary,
        extra={
            "phase": "start",
            "route_path": request_summary["route_path"],
            "endpoint": request_summary["endpoint"],
            "client_ip": request_summary["client"]["ip"],
            "authenticated": request_summary["auth"]["authenticated"],
            "username": request_summary["auth"]["username"],
        },
    )

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        await _safe_log_operation(
            trace_id=trace_id,
            source_type="api",
            module=module,
            action="api.request.exception",
            status="failed",
            message=(
                f"接口处理异常：{request.method} {path}，模块={module}，"
                f"耗时={duration_ms}ms，异常={str(exc)[:180]}"
            ),
            http_method=request.method,
            path=path,
            status_code=500,
            duration_ms=duration_ms,
            request_summary=request_summary,
            response_summary={"error": str(exc)},
            extra={
                "phase": "exception",
                "route_path": request_summary["route_path"],
                "endpoint": request_summary["endpoint"],
                "client_ip": request_summary["client"]["ip"],
            },
        )
        await _safe_log_api_request(
            trace_id=trace_id,
            method=request.method,
            path=path,
            status_code=500,
            duration_ms=duration_ms,
            request_summary=request_summary,
            response_summary={"error": str(exc)},
            message=f"{request.method} {path} failed with unhandled exception",
        )
        raise

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    response_summary = _build_response_summary(request, response, trace_id, duration_ms)
    status_text = (
        "成功"
        if response.status_code < 400
        else "警告"
        if response.status_code < 500
        else "失败"
    )
    await _safe_log_operation(
        trace_id=trace_id,
        source_type="api",
        module=module,
        action="api.request.finish",
        status="success"
        if response.status_code < 400
        else "warning"
        if response.status_code < 500
        else "failed",
        message=(
            f"接口处理完成：{request.method} {path}，模块={module}，状态码={response.status_code}，"
            f"耗时={duration_ms}ms，结果={status_text}"
        ),
        http_method=request.method,
        path=path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        request_summary=request_summary,
        response_summary=response_summary,
        extra={
            "phase": "finish",
            "route_path": request_summary["route_path"],
            "endpoint": request_summary["endpoint"],
            "client_ip": request_summary["client"]["ip"],
            "status_code": response.status_code,
        },
    )
    await _safe_log_api_request(
        trace_id=trace_id,
        method=request.method,
        path=path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        request_summary=request_summary,
        response_summary=response_summary,
    )
    response.headers["X-Trace-Id"] = trace_id
    return response


app.include_router(search.router, prefix="/api")
app.include_router(auth_api.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(pan115.router, prefix="/api")
app.include_router(pansou.router, prefix="/api")
app.include_router(runtime_settings_api.router, prefix="/api")
app.include_router(scheduler.router, prefix="/api")
app.include_router(workflow.router, prefix="/api")
app.include_router(logs_api.router, prefix="/api")
app.include_router(license_api.router, prefix="/api")


@app.get("/")
async def root():
    metadata = app_metadata_service.get_current_metadata()
    return {
        "name": settings.APP_NAME,
        "version": metadata["current_version"],
        "status": "running",
        "build": metadata,
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
