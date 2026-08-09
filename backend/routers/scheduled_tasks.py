"""
Scheduled tasks router.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

import scheduled_tasks as st

router = APIRouter(tags=["scheduled_tasks"])


# ---- Models ----

class TaskCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    task_type: str = Field(..., min_length=1)
    cron_expr: str = Field(..., min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = Field(default=True)
    notify_on_success: bool = Field(default=False)
    notify_on_failure: bool = Field(default=True)


class TaskUpdateBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    task_type: Optional[str] = Field(None, min_length=1)
    cron_expr: Optional[str] = Field(None, min_length=1)
    payload: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    notify_on_success: Optional[bool] = None
    notify_on_failure: Optional[bool] = None


# ---- Routes ----

@router.get("/api/scheduled-tasks")
async def list_scheduled_tasks() -> Dict[str, Any]:
    """List all scheduled tasks."""
    tasks = st._manager.list_tasks()
    return {
        "data": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "task_type": t.task_type,
                "cron_expr": t.cron_expr,
                "payload": t.payload,
                "enabled": t.enabled,
                "notify_on_success": t.notify_on_success,
                "notify_on_failure": t.notify_on_failure,
                "last_run_at": t.last_run_at,
                "last_run_status": t.last_run_status,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tasks
        ]
    }


@router.get("/api/scheduled-tasks/types")
async def list_task_types() -> Dict[str, List[str]]:
    """List available task types.

    必须注册在 ``/{task_id}`` 之前，否则 /types 会被 int 路径捕获（422）。
    """
    return {
        "data": [
            "daily_data_refresh",
            "daily_review_notify",
            "limitup_precompute",
            "portfolio_refresh",
            "market_data_sync",
            "cleanup_old_runs",
            "daily_backtest_run",
        ]
    }


@router.get("/api/scheduled-tasks/{task_id}")
async def get_scheduled_task(task_id: int) -> Dict[str, Any]:
    """Get a single scheduled task."""
    task = st._manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "data": {
            "id": task.id,
            "name": task.name,
            "description": task.description,
            "task_type": task.task_type,
            "cron_expr": task.cron_expr,
            "payload": task.payload,
            "enabled": task.enabled,
            "notify_on_success": task.notify_on_success,
            "notify_on_failure": task.notify_on_failure,
            "last_run_at": task.last_run_at,
            "last_run_status": task.last_run_status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
    }


@router.post("/api/scheduled-tasks")
async def create_scheduled_task(body: TaskCreateBody) -> Dict[str, Any]:
    """Create a new scheduled task."""
    task = st.ScheduledTask(
        name=body.name,
        description=body.description,
        task_type=body.task_type,
        cron_expr=body.cron_expr,
        payload=body.payload,
        enabled=body.enabled,
        notify_on_success=body.notify_on_success,
        notify_on_failure=body.notify_on_failure,
    )
    task = st._manager.create_task(task)
    return {"data": {"id": task.id}}


@router.put("/api/scheduled-tasks/{task_id}")
async def update_scheduled_task(task_id: int, body: TaskUpdateBody) -> Dict[str, Any]:
    """Update a scheduled task."""
    task = st._manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(task, key):
            setattr(task, key, value)

    task = st._manager.update_task(task)
    if not task:
        raise HTTPException(status_code=500, detail="更新失败")

    return {"data": {"id": task.id}}


@router.delete("/api/scheduled-tasks/{task_id}")
async def delete_scheduled_task(task_id: int) -> Dict[str, str]:
    """Delete a scheduled task."""
    task = st._manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    st._manager.delete_task(task_id)
    return {"status": "ok"}


@router.post("/api/scheduled-tasks/{task_id}/run")
async def run_scheduled_task_now(task_id: int) -> Dict[str, Any]:
    """Manually trigger a task run."""
    task = st._manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    import threading
    executor = st.TaskExecutor()
    run = executor.execute(task)
    return {
        "data": {
            "run_id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error": run.error,
        }
    }


@router.get("/api/scheduled-tasks/{task_id}/runs")
async def list_task_runs(task_id: int, limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """List recent runs for a task."""
    task = st._manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    runs = st._manager.list_runs(task_id, limit=limit)
    return {
        "data": [
            {
                "id": r.id,
                "task_id": r.task_id,
                "status": r.status,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "result": r.result,
                "error": r.error,
            }
            for r in runs
        ]
    }


__all__ = ["router"]

