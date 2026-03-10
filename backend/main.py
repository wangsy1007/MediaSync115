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
from app.services.explore_home_warmup_service import explore_home_warmup_service
from app.services.operation_log_service import operation_log_service
from app.services.pansou_service import pansou_service
from app.services.runtime_settings_service import runtime_settings_service
from app.services.emby_sync_scheduler_service import emby_sync_scheduler_service
from app.services.subscription_scheduler_service import subscription_scheduler_service

logger = logging.getLogger(__name__)


async def _safe_log_api_request(**kwargs) -> None:
    try:
        await operation_log_service.log_api_request(**kwargs)
    except Exception:
        logger.exception("api operation log failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    pansou_service.set_base_url(runtime_settings_service.get_pansou_base_url())
    await init_db()
    await operation_log_service.prune(days=30)
    await scheduler_manager.init()
    await subscription_scheduler_service.ensure_subscription_tasks()
    await emby_sync_scheduler_service.ensure_sync_task()
    await explore_home_warmup_service.warmup(force_refresh=False)
    yield
    await scheduler_manager.stop()
    await pansou_service.close()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
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
    request_summary = {
        "query": dict(request.query_params),
        "headers": operation_log_service.redact_headers(
            {
                "user-agent": request.headers.get("user-agent", ""),
                "x-client-timezone": request.headers.get("x-client-timezone", ""),
                "content-type": request.headers.get("content-type", ""),
            }
        ),
    }

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

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
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
    response_summary = {"status_code": response.status_code}
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


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
