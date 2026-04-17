from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, select

from app.core.database import async_session_maker
from app.models.models import OperationLog
from app.services.operation_log_service import operation_log_service

router = APIRouter(prefix="/logs", tags=["logs"])


def _parse_iso_datetime(value: Optional[str], field_name: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        raise HTTPException(
            status_code=400, detail=f"invalid {field_name}, expected ISO datetime"
        )


@router.get("")
async def list_operation_logs(
    source_type: Optional[str] = None,
    module: Optional[str] = None,
    status: Optional[str] = None,
    path: Optional[str] = None,
    trace_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
):
    where_clauses = []
    if source_type:
        where_clauses.append(OperationLog.source_type == source_type.strip())
    if module:
        where_clauses.append(OperationLog.module == module.strip())
    if status:
        where_clauses.append(OperationLog.status == status.strip())
    if path:
        where_clauses.append(OperationLog.path.ilike(f"%{path.strip()}%"))
    if trace_id:
        where_clauses.append(OperationLog.trace_id == trace_id.strip())

    dt_from = _parse_iso_datetime(date_from, "date_from")
    dt_to = _parse_iso_datetime(date_to, "date_to")
    if dt_from:
        where_clauses.append(OperationLog.created_at >= dt_from)
    if dt_to:
        where_clauses.append(OperationLog.created_at <= dt_to)

    condition = and_(*where_clauses) if where_clauses else None

    async with async_session_maker() as db:
        base_query = select(OperationLog)
        total_query = select(func.count(OperationLog.id))
        summary_query = select(OperationLog.status, func.count(OperationLog.id))

        if condition is not None:
            base_query = base_query.where(condition)
            total_query = total_query.where(condition)
            summary_query = summary_query.where(condition)

        rows_result = await db.execute(
            base_query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total_result = await db.execute(total_query)
        summary_result = await db.execute(summary_query.group_by(OperationLog.status))

    items = []
    for row in rows_result.scalars().all():
        items.append(
            {
                "id": row.id,
                "trace_id": row.trace_id,
                "source_type": row.source_type,
                "module": row.module,
                "action": row.action,
                "status": row.status,
                "http_method": row.http_method,
                "path": row.path,
                "status_code": row.status_code,
                "duration_ms": row.duration_ms,
                "message": row.message,
                "request_summary": row.request_summary,
                "response_summary": row.response_summary,
                "extra": row.extra,
                "created_at": row.created_at,
            }
        )

    summary = {"success": 0, "warning": 0, "failed": 0, "info": 0}
    for current_status, count in summary_result.all():
        key = str(current_status or "info")
        summary[key] = int(count or 0)

    return {
        "items": items,
        "total": int(total_result.scalar() or 0),
        "summary": summary,
        "limit": limit,
        "offset": offset,
    }


@router.get("/modules")
async def list_operation_log_modules():
    async with async_session_maker() as db:
        modules_result = await db.execute(
            select(OperationLog.module).distinct().order_by(OperationLog.module.asc())
        )
        source_result = await db.execute(
            select(OperationLog.source_type)
            .distinct()
            .order_by(OperationLog.source_type.asc())
        )
        status_result = await db.execute(
            select(OperationLog.status).distinct().order_by(OperationLog.status.asc())
        )

    return {
        "modules": [item for item in modules_result.scalars().all() if item],
        "source_types": [item for item in source_result.scalars().all() if item],
        "statuses": [item for item in status_result.scalars().all() if item],
    }


@router.post("/prune")
async def prune_operation_logs(days: int = Query(30, ge=1, le=3650)):
    removed = await operation_log_service.prune(days=days)
    return {"success": True, "removed": removed, "days": days}


@router.delete("/clear")
async def clear_operation_logs():
    removed = await operation_log_service.clear()
    return {"success": True, "removed": removed}
