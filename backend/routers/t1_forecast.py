# -*- coding: utf-8 -*-
"""S232 T+1 涨停预测 watchlist router——GET /api/t1-forecast/watchlist + /report。

观察池工具非交易信号。5.28x lift 真但 EV -0.87% 负。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from vr_paths import prev_trading_date_str, resolve_data_dir

from tools.t1_forecast import generate_t1_watchlist, render_watchlist_report

_logger = logging.getLogger("vibe-research")

router = APIRouter(prefix="/api/t1-forecast", tags=["t1-forecast"])

_FORECAST_DIR = Path(resolve_data_dir()) / "t1_forecast"

# 防路径遍历 + malformed date 静默空 watchlist（reviewer HIGH 修复）
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(date: str | None) -> str:
    """校验 date 格式 YYYY-MM-DD，失败返 400。"""
    target = date or prev_trading_date_str()
    if not _DATE_RE.match(target):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: {target} (expected YYYY-MM-DD)",
        )
    return target


@router.get("/watchlist")
def get_watchlist(
    date: str | None = Query(None, description="T 日 YYYY-MM-DD，缺省最近交易日"),
) -> dict[str, Any]:
    """GET /api/t1-forecast/watchlist——T+1 涨停预测 watchlist（观察池非买入信号）。

    优先读持久化 {date}_watchlist.json，不存在则重新生成。
    诚实标注：edge_status="weak-signal-EV-negative"——5.28x lift 真但 EV -0.87% 负。
    """
    target_date = _validate_date(date)
    record = _FORECAST_DIR / f"{target_date}_watchlist.json"
    if record.exists():
        try:
            with open(record, "r", encoding="utf-8") as f:
                watchlist = json.load(f)
            return {"status": "ok", "date": target_date, "data": watchlist}
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("[S232] 读持久化失败，重新生成: %s", e)
    # 重新生成（持久化不存在或读失败）
    watchlist = generate_t1_watchlist(target_date)
    return {"status": "ok", "date": target_date, "data": watchlist}


@router.get("/report")
def get_report(
    date: str | None = Query(None, description="T 日 YYYY-MM-DD，缺省最近交易日"),
) -> dict[str, Any]:
    """GET /api/t1-forecast/report——人话报告（含诚实标注）。优先读持久化（与 /watchlist 一致）。"""
    target_date = _validate_date(date)
    record = _FORECAST_DIR / f"{target_date}_watchlist.json"
    watchlist: dict[str, Any] | None = None
    if record.exists():
        try:
            with open(record, "r", encoding="utf-8") as f:
                watchlist = json.load(f)
        except (json.JSONDecodeError, OSError):
            watchlist = None
    if watchlist is None:
        watchlist = generate_t1_watchlist(target_date)
    return {
        "status": "ok",
        "date": target_date,
        "data": {
            "watchlist": watchlist,
            "report_text": render_watchlist_report(watchlist),
        },
    }


@router.get("/history")
def get_history() -> dict[str, Any]:
    """GET /api/t1-forecast/history——读所有持久化 watchlist 聚合 daily 命中率 + 累积趋势。

    读 _FORECAST_DIR/{date}_watchlist.json，聚合每天 t1_zt 已回填的 stocks，
    返 daily 命中率 + 累积命中率 vs 预期 4.34%（验证信号预测力稳定性）。
    """
    daily: list[dict[str, Any]] = []
    if not _FORECAST_DIR.exists():
        return {
            "status": "ok",
            "data": {"daily": [], "cumulative": {"total": 0, "hit": 0, "rate": 0, "expected_rate": 0.0434}},
        }
    for path in sorted(_FORECAST_DIR.glob("*_watchlist.json")):
        date = path.stem.replace("_watchlist", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                wl = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        stocks = wl.get("stocks", [])
        backfilled = [s for s in stocks if s.get("t1_zt") is not None]
        if not backfilled:
            continue  # 跳过未回填的
        hit = sum(1 for s in backfilled if s.get("t1_zt"))
        total = len(backfilled)
        daily.append(
            {
                "date": date,
                "total": total,
                "hit": hit,
                "rate": round(hit / total, 4) if total else 0.0,
            }
        )

    cum_h = sum(d["hit"] for d in daily)
    cum_s = sum(d["total"] for d in daily)
    cum_rate = cum_h / cum_s if cum_s else 0.0
    expected = 0.0434  # HIT_RATE 信号预期命中率
    return {
        "status": "ok",
        "data": {
            "daily": daily,
            "cumulative": {
                "total": cum_s,
                "hit": cum_h,
                "rate": round(cum_rate, 4),
                "expected_rate": expected,
                "deviation_pct": round((cum_rate - expected) / expected * 100, 2) if expected else None,
                "days": len(daily),
            },
        },
    }
