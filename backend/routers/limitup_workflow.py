# -*- coding: utf-8 -*-
"""S233 打板工作流 router——GET /api/limitup-workflow/today + /report。

打板工作流操作建议（T 日 watchlist + T+1 二次确认 + -3% stop exit 规则）。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from vr_paths import prev_trading_date_str

from tools.limitup_workflow import limitup_workflow, render_workflow_report

_logger = logging.getLogger("vibe-research")

router = APIRouter(prefix="/api/limitup-workflow", tags=["limitup-workflow"])

_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(date: str | None) -> str:
    target = date or prev_trading_date_str()
    if not _DATE_RE.match(target):
        raise HTTPException(status_code=400, detail=f"Invalid date: {target}")
    return target


@router.get("/today")
def get_workflow(
    date: str | None = Query(None, description="T 日 YYYY-MM-DD，缺省最近交易日"),
) -> dict[str, Any]:
    """GET /api/limitup-workflow/today——打板工作流操作建议。

    5 Stage 闭环：watchlist → 二次确认 → open 买 → -3% stop/close 卖 → 回填归因。
    """
    target_date = _validate_date(date)
    workflow = limitup_workflow(target_date)
    return {"status": "ok", "date": target_date, "data": workflow}


@router.get("/report")
def get_report(
    date: str | None = Query(None, description="T 日 YYYY-MM-DD，缺省最近交易日"),
) -> dict[str, Any]:
    """GET /api/limitup-workflow/report——人话报告。"""
    target_date = _validate_date(date)
    workflow = limitup_workflow(target_date)
    return {
        "status": "ok",
        "date": target_date,
        "data": {"workflow": workflow, "report_text": render_workflow_report(workflow)},
    }
