# -*- coding: utf-8 -*-
"""S204 T9: candidate_tracking_pool + indicator_snapshots 两表（多日跟踪架构）。

mirror workflow_state_repo 模式（_ensure_tables 幂等 CREATE IF NOT EXISTS + ON CONFLICT DO
NOTHING + resolve_data_dir .vibe-research/ 不进 git）。

tracking_pool key=(code, first_admit_date) 与 workflow_state key=(code, trade_date) 不同——
两池同步协议在 escalation_engine（T11）：escalation run date T 查 tracking_pool 活跃 track →
对每 track 用 (code,T) 查 workflow_state；无行 → ensure_candidate 再 transition。

tracking_pool.current_status 是 **tracking 级 label**（admit/tracking/decayed/promoted），
NOT workflow_state.WorkflowStatus enum（R5/R6 对抗审修正：实际 transition 走
WATCHING→FILTERED reason='decayed'，不加新 DECAYED 态保 _ALLOWED_TRANSITIONS 不破）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from vr_paths import resolve_data_dir

_DB_PATH: str = str(resolve_data_dir() / "market_data.db")

#: tracking 级 label（NOT workflow_state enum——词表分离，R6 对抗审修正）
TRACKING_LABELS: frozenset[str] = frozenset({"admit", "tracking", "decayed", "promoted"})


@dataclass(frozen=True)
class TrackingRecord:
    """候选跟踪记录（不可变）。每股每次入池一条 track。"""

    code: str
    first_admit_date: str
    admit_signal: str
    admit_indicators_json: str
    current_status: str  # tracking 级 label（admit/tracking/decayed/promoted）
    tracking_age_days: int


@dataclass(frozen=True)
class IndicatorSnapshot:
    """每股每日指标快照（不可变）。"""

    code: str
    trade_date: str
    indicators_json: str
    snapshot_source: str  # 'pre_market'/'escalation'/'early_admit'


def _ensure_tables() -> None:
    """幂等建表（CREATE IF NOT EXISTS）+ 索引。"""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidate_tracking_pool (
                code TEXT NOT NULL,
                first_admit_date TEXT NOT NULL,
                admit_signal TEXT,
                admit_indicators_json TEXT,
                current_status TEXT DEFAULT 'admit',
                tracking_age_days INTEGER DEFAULT 0,
                UNIQUE(code, first_admit_date)
            );
            CREATE TABLE IF NOT EXISTS indicator_snapshots (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                indicators_json TEXT,
                snapshot_source TEXT,
                UNIQUE(code, trade_date)
            );
            CREATE INDEX IF NOT EXISTS idx_tracking_code ON candidate_tracking_pool(code);
            CREATE INDEX IF NOT EXISTS idx_snapshots_code_date ON indicator_snapshots(code, trade_date);
            """
        )


def insert_tracking_record(
    code: str,
    first_admit_date: str,
    admit_signal: str = "",
    indicators: Optional[dict[str, Any]] = None,
) -> bool:
    """insert-if-absent（ON CONFLICT DO NOTHING 幂等）。返 True 若新插入。"""
    ind_json = json.dumps(indicators or {}, ensure_ascii=False)
    with sqlite3.connect(_DB_PATH) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO candidate_tracking_pool "
            "(code, first_admit_date, admit_signal, admit_indicators_json, current_status, tracking_age_days) "
            "VALUES (?, ?, ?, ?, 'admit', 0)",
            (code, first_admit_date, admit_signal, ind_json),
        )
        return cur.rowcount > 0


def upsert_indicator_snapshot(
    code: str,
    trade_date: str,
    indicators: Optional[dict[str, Any]] = None,
    snapshot_source: str = "pre_market",
) -> None:
    """upsert（UNIQUE code,trade_date → INSERT OR REPLACE）。"""
    ind_json = json.dumps(indicators or {}, ensure_ascii=False)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO indicator_snapshots "
            "(code, trade_date, indicators_json, snapshot_source) VALUES (?, ?, ?, ?)",
            (code, trade_date, ind_json, snapshot_source),
        )


def get_active_tracks(current_status: str = "tracking") -> list[TrackingRecord]:
    """查活跃 track（current_status='tracking' 默认）。返 list[TrackingRecord]。"""
    with sqlite3.connect(_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT code, first_admit_date, admit_signal, admit_indicators_json, "
            "current_status, tracking_age_days FROM candidate_tracking_pool "
            "WHERE current_status = ?",
            (current_status,),
        ).fetchall()
        return [
            TrackingRecord(r[0], r[1], r[2] or "", r[3] or "{}", r[4] or "admit", int(r[5] or 0))
            for r in rows
        ]


def update_tracking_status(
    code: str,
    first_admit_date: str,
    new_status: str,
    tracking_age_days: Optional[int] = None,
) -> None:
    """更新 tracking_pool.current_status（tracking 级 label，NOT workflow_state enum）。"""
    with sqlite3.connect(_DB_PATH) as conn:
        if tracking_age_days is not None:
            conn.execute(
                "UPDATE candidate_tracking_pool SET current_status=?, tracking_age_days=? "
                "WHERE code=? AND first_admit_date=?",
                (new_status, tracking_age_days, code, first_admit_date),
            )
        else:
            conn.execute(
                "UPDATE candidate_tracking_pool SET current_status=? "
                "WHERE code=? AND first_admit_date=?",
                (new_status, code, first_admit_date),
            )


def get_snapshots_for(code: str, up_to_date: Optional[str] = None) -> list[IndicatorSnapshot]:
    """查 code 的指标快照序列（按 date asc）。返 list[IndicatorSnapshot]。"""
    with sqlite3.connect(_DB_PATH) as conn:
        if up_to_date:
            rows = conn.execute(
                "SELECT code, trade_date, indicators_json, snapshot_source "
                "FROM indicator_snapshots WHERE code=? AND trade_date<=? ORDER BY trade_date",
                (code, up_to_date),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT code, trade_date, indicators_json, snapshot_source "
                "FROM indicator_snapshots WHERE code=? ORDER BY trade_date",
                (code,),
            ).fetchall()
        return [IndicatorSnapshot(r[0], r[1], r[2] or "{}", r[3] or "") for r in rows]


_ensure_tables()
