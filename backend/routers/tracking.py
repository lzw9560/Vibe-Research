# -*- coding: utf-8 -*-
"""S204 T9: 多日跟踪查询 API（candidate_tracking_pool + indicator_snapshots 只读看板）。

GET /api/tracking/pool — 活跃 track 列表（默认 current_status='tracking'）。
GET /api/tracking/{code}/snapshots — code 的指标快照序列（按 date asc）。

tracking_pool_repo._ensure_tables() 在模块 import 时幂等建表（mirror workflow_state_repo）。
DB: .vibe-research/market_data.db（不进 git）。tracking 级 label（admit/tracking/decayed/promoted）
与 WorkflowStatus enum 词表分离（R5/R6 对抗审修正，不破 _ALLOWED_TRANSITIONS）。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

import tracking_pool_repo as repo

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


def _safe_json(s: str) -> dict[str, Any]:
    try:
        return json.loads(s) if s else {}
    except (TypeError, ValueError):
        return {}


@router.get("/pool")
async def list_pool(
    status: str = Query("tracking", description="tracking 级 label: admit/tracking/decayed/promoted"),
) -> dict[str, Any]:
    """活跃 track 列表（默认 tracking）。tracking 级 label，非 WorkflowStatus enum。"""
    tracks = repo.get_active_tracks(status)
    return {
        "status": status,
        "count": len(tracks),
        "tracks": [
            {
                "code": t.code,
                "first_admit_date": t.first_admit_date,
                "admit_signal": t.admit_signal,
                "admit_indicators": _safe_json(t.admit_indicators_json),
                "current_status": t.current_status,
                "tracking_age_days": t.tracking_age_days,
            }
            for t in tracks
        ],
    }


@router.get("/{code}/snapshots")
async def get_snapshots(
    code: str,
    up_to: str | None = Query(None, description="截止日期（含），默认全部"),
) -> dict[str, Any]:
    """code 的指标快照序列（按 date asc）。供多日跟踪 aging / escalation 判定看指标演进。"""
    snaps = repo.get_snapshots_for(code, up_to_date=up_to)
    return {
        "code": code,
        "count": len(snaps),
        "snapshots": [
            {
                "trade_date": s.trade_date,
                "indicators": _safe_json(s.indicators_json),
                "source": s.snapshot_source,
            }
            for s in snaps
        ],
    }
