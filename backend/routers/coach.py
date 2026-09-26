"""W-C 盯盘教练 router（S064）。

4 端点：时刻表 / 教练状态 / attention_mode GET / attention_mode POST。
纯计算 + 读已有数据，零新外部调用。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Query

from limitup_screener import BEIJING_TZ
from vr_paths import last_trading_date_str
import intraday_coach as coach

logger = logging.getLogger(__name__)

router = APIRouter(tags=["coach"])


class _AttentionModeRequest(BaseModel):
    mode: str  # A/B/C


@router.get("/api/coach/timetable")
async def get_timetable() -> dict[str, Any]:
    """时刻表 10 槽位 + 当前槽位。"""
    now = datetime.now(BEIJING_TZ)
    slot, status = coach.get_current_slot(now)
    slots = [
        {
            "slot_id": s.slot_id,
            "label": s.label,
            "start": s.start,
            "end": s.end,
            "watch": s.watch,
            "judge": s.judge,
            "teaching": s.teaching,
            "mode_note": s.mode_note,
        }
        for s in coach.TIMETABLE
    ]
    return {
        "slots": slots,
        "current_slot_id": slot.slot_id if slot else None,
        "current_time": now.strftime("%H:%M"),
        "status": status,
    }


@router.get("/api/coach/status")
async def get_coach_status(
    date: str | None = Query(None, description="日期 YYYY-MM-DD；默认最近交易日"),
) -> dict[str, Any]:
    """教练状态：current_slot + attention_mode + checklist + mode_rules。"""
    d = date or last_trading_date_str()
    try:
        return {"data": coach.build_coach_state(d)}
    except Exception as exc:
        logger.exception("[coach] build_coach_state 异常")
        raise HTTPException(500, f"教练状态构建失败：{exc}") from exc


@router.get("/api/coach/attention-mode")
async def get_attention_mode(
    date: str | None = Query(None, description="日期 YYYY-MM-DD；默认最近交易日"),
) -> dict[str, Any]:
    """读当日 attention_mode。"""
    d = date or last_trading_date_str()
    mode = coach.get_attention_mode(d)
    rules = coach.MODE_RULES.get(mode, coach.MODE_RULES["A"])
    return {"data": {"date": d, "attention_mode": mode, "rules": rules}}


@router.post("/api/coach/attention-mode")
async def set_attention_mode(req: _AttentionModeRequest) -> dict[str, Any]:
    """写当日 attention_mode（跨日自动重置 A）。"""
    d = last_trading_date_str()
    if req.mode not in ("A", "B", "C"):
        raise HTTPException(400, "mode 必须是 A/B/C")
    try:
        coach.set_attention_mode(d, req.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"data": {"date": d, "attention_mode": req.mode}}
