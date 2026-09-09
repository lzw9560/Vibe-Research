# -*- coding: utf-8 -*-
"""回测快照存取——_save_snapshot / get_backtest_snapshots。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from scheduler.db import _get_connection

logger = logging.getLogger("vibe-research")


def _save_snapshot(snapshot_date: str, engine: str, result: Any) -> None:
    """S041：幂等写回测快照行（同天重跑覆盖）。

    result 对 lite 是 BacktestResult dataclass，对 strategy 是 list[StrategyBacktestResult]。
    按 engine 字段区分提取字段——lite 取 hit_rate/avg_return/max_drawdown/sharpe_ratio/
    total_signals/percentile_json；strategy 取 strategy_breakdown_json（12 战法聚合，S086 起 8→12）。
    """
    conn = _get_connection()
    try:
        if engine == "lite":
            hit_rate = getattr(result, "hit_rate", None)
            avg_return = getattr(result, "avg_return", None)
            max_drawdown = getattr(result, "max_drawdown", None)
            sharpe_ratio = getattr(result, "sharpe_ratio", None)
            total_signals = getattr(result, "total_signals", None)
            percentile_json = json.dumps(getattr(result, "percentile_analysis", None), ensure_ascii=False)
            strategy_breakdown_json = None
        elif engine == "strategy":
            # result: list[StrategyBacktestResult]
            breakdown = [
                {
                    "strategy_code": getattr(r, "strategy_code", ""),
                    "strategy_name": getattr(r, "strategy_name", ""),
                    "win_rate": getattr(r, "win_rate", None),
                    "avg_return": getattr(r, "avg_return", None),
                    "sample_size": getattr(r, "sample_size", None),
                    "available_days": getattr(r, "available_days", None),
                    "skipped": getattr(r, "skipped", 0),
                }
                for r in (result or [])
            ]
            hit_rate = None
            avg_return = None
            max_drawdown = None
            sharpe_ratio = None
            total_signals = None
            percentile_json = None
            strategy_breakdown_json = json.dumps(breakdown, ensure_ascii=False)
        else:
            raise ValueError(f"未知 engine: {engine}")

        conn.execute(
            """
            INSERT INTO backtest_daily_snapshots
                (snapshot_date, engine, hit_rate, avg_return, max_drawdown,
                 sharpe_ratio, total_signals, percentile_json, strategy_breakdown_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date, engine) DO UPDATE SET
                hit_rate = excluded.hit_rate,
                avg_return = excluded.avg_return,
                max_drawdown = excluded.max_drawdown,
                sharpe_ratio = excluded.sharpe_ratio,
                total_signals = excluded.total_signals,
                percentile_json = excluded.percentile_json,
                strategy_breakdown_json = excluded.strategy_breakdown_json
            """,
            (snapshot_date, engine, hit_rate, avg_return, max_drawdown,
             sharpe_ratio, total_signals, percentile_json, strategy_breakdown_json),
        )
        conn.commit()
    finally:
        conn.close()


def get_backtest_snapshots(days: int = 90) -> List[Dict[str, Any]]:
    """S041：查最近 N 天回测快照（按 snapshot_date 升序）。

    返回 list[dict]——percentile_json/strategy_breakdown_json 已反序列化成 dict/list，
    None 保留为 None。供 GET /api/backtest/trend 端点用。
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT snapshot_date, engine, hit_rate, avg_return, max_drawdown,
                   sharpe_ratio, total_signals, percentile_json, strategy_breakdown_json,
                   created_at
            FROM backtest_daily_snapshots
            WHERE snapshot_date >= date('now', ?)
            ORDER BY snapshot_date ASC, engine ASC
            """,
            (f"-{days} days",),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["percentile_json"] = json.loads(d["percentile_json"]) if d.get("percentile_json") else None
            d["strategy_breakdown_json"] = (
                json.loads(d["strategy_breakdown_json"]) if d.get("strategy_breakdown_json") else None
            )
            out.append(d)
        return out
    finally:
        conn.close()
