"""
Scheduled tasks router.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import date, datetime
import asyncio

from vr_paths import BEIJING_TZ

import scheduled_tasks as st

router = APIRouter(tags=["scheduled_tasks"])


# ---- today_status 推算（S092 R18：后端算，不前端算）----

def _compute_today_status(task: Any) -> str:
    """根据 last_run_at/last_run_status 推算今日完成状态。

    返回值：running / done / error / pending

    last_run_at 是 naive ISO 字符串（无时区后缀，假设服务器本地时区=北京，GR5 标注）。
    今日北京日期与 last_run 日期同为 naive date 比较。
    """
    status = task.last_run_status
    if status == "running":
        return "running"

    today_bj = datetime.now(BEIJING_TZ).date()
    last_run_date = None
    if task.last_run_at:
        try:
            parsed = datetime.fromisoformat(task.last_run_at)
            last_run_date = parsed.date()
        except ValueError:
            last_run_date = None

    if last_run_date == today_bj and status == "success":
        return "done"
    if last_run_date == today_bj and status == "failed":
        return "error"
    # last_run_date != today_bj 或 last_run_at 为 None 或解析失败 → pending
    return "pending"


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
                "today_status": _compute_today_status(t),
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
            "sti_post_market",
            "seal_intraday_collect",
            "candidate_funnel_precompute",
            "first_board_filter",
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
            "today_status": _compute_today_status(task),
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


@router.post("/api/backtest/backfill")
async def backfill_backtest(days: int = Query(60, ge=1, le=90)) -> Dict[str, Any]:
    """S052 D2：一次性回测快照回填——逐日补跑缺口日（point-in-time，只读 gene_scores + 本地 K 线）。

    幂等：已有快照日自动排除；单日失败不阻断整批。
    """
    from backfill_snapshots import backfill_backtest_snapshots  # noqa: PLC0415
    result = await asyncio.to_thread(backfill_backtest_snapshots, days)
    return {"data": result}


@router.post("/api/winrate/backfill-samples")
async def backfill_winrate_samples_endpoint(days: int = Query(30, ge=1, le=90)) -> Dict[str, Any]:
    """S054：回填合成 winrate 样本——假设用户按推荐建仓，补全三桶数据。

    70% 推荐标的假设买入（funnel_candidate），30% 留作 missed 桶。
    return_pct 用次日 K 线收益（信号日 close→次日 close）。
    幂等：signal_ref='backfill:synthetic' 标记，重复跑先删旧行。
    """
    from backfill_winrate_samples import backfill_winrate_samples  # noqa: PLC0415
    result = await asyncio.to_thread(backfill_winrate_samples, days)
    return {"data": result}


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

