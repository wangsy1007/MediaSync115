import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.workflow import Workflow
from app.scheduler import scheduler_manager
from app.services.workflow_service import WorkflowService

from app.core.timezone_utils import beijing_now

router = APIRouter(prefix="/workflow", tags=["workflow"])


class WorkflowPayload(BaseModel):
    name: str
    description: Optional[str] = None
    timer: Optional[str] = None
    trigger_type: str = "timer"
    event_type: Optional[str] = None
    event_conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    flows: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    state: str = "P"


class WorkflowUpdatePayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    timer: Optional[str] = None
    trigger_type: Optional[str] = None
    event_type: Optional[str] = None
    event_conditions: Optional[dict[str, Any]] = None
    actions: Optional[list[dict[str, Any]]] = None
    flows: Optional[list[dict[str, Any]]] = None
    context: Optional[dict[str, Any]] = None
    state: Optional[str] = None


class EventTriggerPayload(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_workflows(db: AsyncSession = Depends(get_db)):
    return await WorkflowService(db).list_all()


@router.get("/event-types")
async def list_event_types():
    return {
        "items": [
            {"value": "download.completed", "title": "下载完成"},
            {"value": "download.failed", "title": "下载失败"},
            {"value": "subscription.created", "title": "订阅创建"},
            {"value": "manual.trigger", "title": "手动触发"},
        ]
    }


@router.post("/events/trigger")
async def trigger_workflow_event(payload: EventTriggerPayload):
    results = await scheduler_manager.trigger_event_workflows(payload.event_type, payload.payload)
    return {"count": len(results), "results": results}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    workflow = await WorkflowService(db).get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("")
async def create_workflow(payload: WorkflowPayload, db: AsyncSession = Depends(get_db)):
    service = WorkflowService(db)
    if await service.get_by_name(payload.name):
        raise HTTPException(status_code=400, detail="Workflow name already exists")

    workflow = await service.create(
        {
            "name": payload.name,
            "description": payload.description,
            "timer": payload.timer,
            "trigger_type": payload.trigger_type,
            "event_type": payload.event_type,
            "event_conditions": json.dumps(payload.event_conditions or {}, ensure_ascii=False),
            "actions": json.dumps(payload.actions or [], ensure_ascii=False),
            "flows": json.dumps(payload.flows or [], ensure_ascii=False),
            "context": json.dumps(payload.context or {}, ensure_ascii=False),
            "state": payload.state,
            "run_count": 0,
        }
    )

    if workflow.trigger_type == "timer" and workflow.state == "W":
        await scheduler_manager.update_workflow_job(workflow)
    return workflow


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: int, payload: WorkflowUpdatePayload, db: AsyncSession = Depends(get_db)):
    service = WorkflowService(db)
    workflow = await service.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != workflow.name:
        existing = await service.get_by_name(data["name"])
        if existing:
            raise HTTPException(status_code=400, detail="Workflow name already exists")

    mapped = {}
    for key, value in data.items():
        if key in {"event_conditions", "actions", "flows", "context"}:
            mapped[key] = json.dumps(value or ({} if key in {"event_conditions", "context"} else []), ensure_ascii=False)
        else:
            mapped[key] = value
    mapped["updated_at"] = beijing_now()

    workflow = await service.update(workflow, mapped)

    if workflow.trigger_type == "timer" and workflow.state == "W":
        await scheduler_manager.update_workflow_job(workflow)
    else:
        await scheduler_manager.remove_workflow_job(workflow.id)
    return workflow


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    service = WorkflowService(db)
    workflow = await service.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await service.delete(workflow)
    await scheduler_manager.remove_workflow_job(workflow_id)
    return {"success": True}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: int):
    result = await scheduler_manager.run_workflow_once(workflow_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "run failed")
    return result


@router.post("/{workflow_id}/start")
async def start_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    service = WorkflowService(db)
    workflow = await service.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.state = "W"
    await db.commit()
    await db.refresh(workflow)

    if workflow.trigger_type == "timer":
        await scheduler_manager.update_workflow_job(workflow)
    return {"success": True}


@router.post("/{workflow_id}/pause")
async def pause_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    service = WorkflowService(db)
    workflow = await service.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.state = "P"
    await db.commit()
    await db.refresh(workflow)
    await scheduler_manager.remove_workflow_job(workflow_id)
    return {"success": True}


@router.post("/{workflow_id}/reset")
async def reset_workflow(workflow_id: int, db: AsyncSession = Depends(get_db)):
    workflow = await WorkflowService(db).get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.run_count = 0
    workflow.current_action = None
    workflow.last_result = None
    workflow.last_run_at = None
    await db.commit()
    await db.refresh(workflow)
    return {"success": True}


