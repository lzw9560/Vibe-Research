# -*- coding: utf-8 -*-
"""S218: 信号报告路由——/api/signals/*。

GET /api/signals/daily ——当日 consecutive_relay 信号（结构化 dict）
GET /api/signals/status ——regime 新鲜度 + arm 状态
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from engine.trade_journal import TradeJournal
from tools.gap_regime_stratified import compute_regime_labels
from tools.signal_report import get_consecutive_relay_signals, render_daily_report

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/daily")
def _signals_daily() -> dict[str, Any]:
    """返回当日 consecutive_relay 信号报告（结构化 dict）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_consecutive_relay_signals(today)


@router.get("/daily-report")
def _signals_daily_report() -> dict[str, str]:
    """返回人话版每日信号报告（Markdown 文本）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    signals = get_consecutive_relay_signals(today)
    return {"report": render_daily_report(signals)}


@router.get("/status")
def _signals_status() -> dict[str, Any]:
    """返回 regime 新鲜度 + 各 arm 状态。"""
    today = datetime.now().strftime("%Y-%m-%d")
    regime_map = compute_regime_labels()
    regime = regime_map.get(today)

    # regime cache freshness
    from tools.signal_report import _regime_freshness
    freshness = _regime_freshness()

    # arm status
    tj = TradeJournal()
    arms = ["consecutive_relay", "breakout", "trend_swing", "floor"]
    arm_statuses = {}
    for arm in arms:
        status = tj.query_arm_status(arm)
        if status is None:
            arm_statuses[arm] = {"is_active": True, "weight_override": None}
        else:
            arm_statuses[arm] = {
                "is_active": status["is_active"],
                "weight_override": status["weight_override"],
                "kill_reason": status.get("kill_reason"),
            }

    return {
        "regime": {
            "current": regime,
            "freshness": freshness,
        },
        "arms": arm_statuses,
    }
