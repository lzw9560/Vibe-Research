"""weather_history 持久化（S065）。

每日盘后落 weather_state 快照 + 五因子明细，为 WR-Workflow W1 证据层提供可回放的真地基。

- 表 weather_history（date PK + weather_state + 五因子 + phase + confidence）
- UPSERT 落库，幂等可重跑
- 零 em_get（只读 sti_timeline dimensions）

合规：不臆造（sti 无行 → missing）；快照落 .gitignored DB。
"""
from __future__ import annotations

import logging
from typing import Any

from config import STI_TIMELINE_DB_PATH

logger = logging.getLogger(__name__)

import sqlite3

_DB_PATH = STI_TIMELINE_DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_TABLE_FIELDS = (
    "date", "weather_state", "composite_score", "sti_score",
    "risk_score", "sector_continuity", "capital_momentum",
    "public_sentiment", "phase", "confidence",
)


def save_weather_snapshot(row: dict[str, Any]) -> None:
    """UPSERT by date。幂等可重跑。"""
    values = [row.get(f) for f in _TABLE_FIELDS]
    placeholders = ", ".join(["?"] * len(_TABLE_FIELDS))
    updates = ", ".join([f"{f}=excluded.{f}" for f in _TABLE_FIELDS[1:]])
    sql = (
        f"INSERT INTO weather_history ({', '.join(_TABLE_FIELDS)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(date) DO UPDATE SET {updates}"
    )
    conn = _get_conn()
    try:
        conn.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def get_weather_by_date(date: str) -> dict[str, Any] | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM weather_history WHERE date = ?", (date,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_weather_history(days: int = 90) -> list[dict[str, Any]]:
    """近 N 天快照（date 降序）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM weather_history ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
