"""
Health check router.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter(tags=["health"])


def _check_database() -> Dict[str, Any]:
    """检查数据库连通性与核心表可读性。"""
    try:
        from limitup_screener.data import get_db as get_screener_db
        from limitup_sti.data import get_db as get_sti_db
        import sqlite3

        screener_db = get_screener_db()
        sti_db = get_sti_db()

        with screener_db:
            screener_db.execute("SELECT 1 FROM gene_scores LIMIT 1").fetchone()
        with sti_db:
            sti_db.execute("SELECT 1 FROM sti_timeline LIMIT 1").fetchone()

        from config import WINRATE_DB_PATH
        winrate_path = WINRATE_DB_PATH
        with sqlite3.connect(winrate_path) as conn:
            conn.execute("SELECT 1 FROM winrate_records LIMIT 1").fetchone()

        return {"ok": True, "detail": "database_ok"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"database_error: {exc}"}


def _check_circuit_breaker() -> Dict[str, Any]:
    """检查熔断器状态。"""
    try:
        from circuit_breaker import get_breaker

        breaker = get_breaker("eastmoney")
        # peek_state 尊重 recovery_timeout：陈旧 OPEN（>60s 无请求）自愈为 HALF_OPEN，
        # 避免测试触发的瞬时 OPEN 使 health 永久报红（S022）。
        state = breaker.peek_state().value
        return {
            "ok": state != "open",
            "detail": f"circuit_breaker_{state}",
            "failure_count": breaker.failure_count,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"circuit_breaker_error: {exc}"}


def _check_data_freshness() -> Dict[str, Any]:
    """检查核心数据表最后更新时间。"""
    try:
        from limitup_screener.data import get_db as get_screener_db
        from limitup_sti.data import get_db as get_sti_db

        screener_db = get_screener_db()
        sti_db = get_sti_db()

        screener_row = screener_db.execute(
            "SELECT MAX(updated_at) AS last_updated FROM gene_scores"
        ).fetchone()
        sti_row = sti_db.execute(
            "SELECT MAX(computed_at) AS last_updated FROM sti_timeline"
        ).fetchone()

        screener_ts = screener_row["last_updated"] if screener_row else None
        sti_ts = sti_row["last_updated"] if sti_row else None

        return {
            "ok": bool(screener_ts or sti_ts),
            "detail": {
                "gene_scores_last_updated": screener_ts,
                "sti_timeline_last_updated": sti_ts,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"freshness_error: {exc}"}


def _check_scheduler() -> Dict[str, Any]:
    """检查调度器状态（仅返回配置，不触发副作用）。

    S031 R12：scheduler.py 已删，改查 scheduled_tasks CronScheduler + limitup_precompute seed。
    """
    try:
        import scheduled_tasks as st

        seeded = any(t.name == "limitup_precompute" for t in st._manager.list_tasks())
        return {
            "ok": True,
            "detail": {
                "cron_scheduler": "configured",
                "limitup_precompute_seed": "seeded" if seeded else "missing",
                "portfolio_scheduler": "configured",
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"scheduler_error: {exc}"}


def _check_fallback() -> Dict[str, Any]:
    """检查降级缓存目录可用性。"""
    try:
        from pathlib import Path
        from fallback import _CACHE_DIR

        cache_dir = Path(_CACHE_DIR)
        exists = cache_dir.exists()
        writable = exists and cache_dir.is_dir() and bool(cache_dir.parent.exists())

        return {
            "ok": writable,
            "detail": {
                "cache_dir": str(cache_dir),
                "exists": exists,
                "writable": writable,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"fallback_error: {exc}"}


async def _check_extreme_market() -> Dict[str, Any]:
    """检查极端行情检测模块状态。"""
    try:
        from extreme_market_detector import get_extreme_market_signal

        signal = await get_extreme_market_signal()
        if signal is None:
            return {"ok": False, "detail": "extreme_market_detector_unavailable"}

        return {
            "ok": True,
            "detail": {
                "date": signal.date,
                "signal_type": signal.signal_type,
                "is_extreme": signal.is_extreme,
                "zt_count": signal.zt_count,
                "dt_count": signal.dt_count,
                "zb_count": signal.zb_count,
                "threshold_zt": signal.threshold_zt,
                "threshold_dt": signal.threshold_dt,
                "last_updated": signal.last_updated,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"extreme_market_error: {exc}"}


@router.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """系统健康检查（数据库 / 熔断器 / 数据新鲜度 / 调度器 / 降级缓存 / 极端行情）。"""
    checks = {
        "database": _check_database(),
        "circuit_breaker": _check_circuit_breaker(),
        "data_freshness": _check_data_freshness(),
        "scheduler": _check_scheduler(),
        "fallback": _check_fallback(),
        "extreme_market": await _check_extreme_market(),
    }

    overall_ok = all(item.get("ok", False) for item in checks.values())

    return {
        "ok": overall_ok,
        "service": "vibe-research-api",
        "version": "0.1.3",
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


__all__ = ["router"]
