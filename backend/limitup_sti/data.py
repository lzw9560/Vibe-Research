# -*- coding: utf-8 -*-
"""limitup_sti 数据层 —— 数据库连接、迁移、读写。"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from config import STI_TIMELINE_DB_PATH

from migrations import MigrationManager

from limitup_sti.models import STIResult, DISCLAIMER

DB_PATH = STI_TIMELINE_DB_PATH


def run_initial_migrations() -> None:
    """执行初始 schema 迁移（仅一次）。"""
    manager = MigrationManager(db_path=DB_PATH)
    migration_v1 = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "sti" / "20250613-001_create_sti_timeline.sql"
    ).read_text(encoding="utf-8")
    migration_v2 = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "sti" / "20250613-002_add_sti_indexes.sql"
    ).read_text(encoding="utf-8")
    migrations = [
        {
            "version": "20250613-001",
            "name": "create_sti_timeline",
            "sql": migration_v1,
        },
        {
            "version": "20250613-002",
            "name": "add_sti_indexes",
            "sql": migration_v2,
        },
    ]
    manager.upgrade(migrations)


def get_db() -> sqlite3.Connection:
    """获取 SQLite 连接（单例，线程安全）。"""
    db = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def migrate_schema(db: sqlite3.Connection) -> None:
    """迁移旧 schema：移除 break_rate 列，重命名 momentum → change_from_yesterday，新增 data_updated。"""
    db_path = db.execute("PRAGMA database_list").fetchone()[2]
    cursor = db.execute("PRAGMA table_info(sti_timeline)")
    columns = {row["name"] for row in cursor.fetchall()}

    needs_migration = False
    if "dimension_break_rate" in columns:
        needs_migration = True
    if "momentum" in columns and "change_from_yesterday" not in columns:
        needs_migration = True

    if not needs_migration:
        return

    insert_cols = "date, score, phase, dimension_limit_up_count, dimension_limit_down_count, dimension_seal_rate, dimension_advance_decline_ratio, dimension_promotion_rate, dimension_prev_zt_performance, dimension_max_boards, market_factor, confidence, source_ok, change_from_yesterday, data_updated, computed_at"
    sel_date = "date" if "date" in columns else "NULL"
    sel_score = "score" if "score" in columns else "NULL"
    sel_phase = "phase" if "phase" in columns else "NULL"
    sel_dims = []
    for c in ("dimension_limit_up_count", "dimension_limit_down_count", "dimension_seal_rate",
              "dimension_advance_decline_ratio", "dimension_promotion_rate",
              "dimension_prev_zt_performance", "dimension_max_boards"):
        sel_dims.append(c if c in columns else "NULL")
    sel_market = "market_factor" if "market_factor" in columns else "NULL"
    sel_conf = "confidence" if "confidence" in columns else "NULL"
    sel_srcok = "source_ok" if "source_ok" in columns else "NULL"
    sel_chg = "change_from_yesterday" if "change_from_yesterday" in columns else ("momentum" if "momentum" in columns else "NULL")
    sel_du = "data_updated" if "data_updated" in columns else "NULL"
    sel_computed = "computed_at" if "computed_at" in columns else "CURRENT_TIMESTAMP"
    select_cols = f"{sel_date}, {sel_score}, {sel_phase}, {', '.join(sel_dims)}, {sel_market}, {sel_conf}, {sel_srcok}, {sel_chg}, {sel_du}, {sel_computed}"

    migration_sql = f"""
BEGIN TRANSACTION;
DROP TABLE IF EXISTS sti_timeline_new;
CREATE TABLE sti_timeline_new (
    date TEXT NOT NULL UNIQUE,
    score REAL, phase TEXT,
    dimension_limit_up_count REAL, dimension_limit_down_count REAL,
    dimension_seal_rate REAL, dimension_advance_decline_ratio REAL,
    dimension_promotion_rate REAL, dimension_prev_zt_performance REAL,
    dimension_max_boards REAL,
    market_factor REAL, confidence TEXT,
    source_ok BOOLEAN DEFAULT 1,
    change_from_yesterday REAL, data_updated TEXT,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO sti_timeline_new ({insert_cols}) SELECT {select_cols} FROM sti_timeline;
DROP TABLE sti_timeline;
ALTER TABLE sti_timeline_new RENAME TO sti_timeline;
CREATE INDEX IF NOT EXISTS idx_sti_date ON sti_timeline(date DESC);
CREATE INDEX IF NOT EXISTS idx_sti_phase ON sti_timeline(phase);
COMMIT;
"""
    manager = MigrationManager(db_path=db_path)
    migrations = [
        {
            "version": "20250613-002",
            "name": "migrate_sti_timeline_v2",
            "sql": migration_sql,
        }
    ]
    manager.upgrade(migrations)


def save_result(result: STIResult) -> None:
    """持久化 STI 结果到 sti_timeline 表。"""
    try:
        db = get_db()
        if result.dimensions is None:
            dim_values = [None] * 8
        else:
            dims = result.dimensions
            dim_values = [
                dims.limit_up_count,
                dims.limit_down_count,
                dims.seal_rate,
                dims.advance_decline_ratio,
                dims.promotion_rate,
                dims.prev_zt_performance,
                dims.max_boards,
                dims.market_factor,
            ]

        db.execute(
            """INSERT OR REPLACE INTO sti_timeline (
                date, score, phase,
                dimension_limit_up_count, dimension_limit_down_count,
                dimension_seal_rate,
                dimension_advance_decline_ratio, dimension_promotion_rate,
                dimension_prev_zt_performance, dimension_max_boards,
                market_factor, confidence, source_ok,
                change_from_yesterday, data_updated, raw_break_rate, zt_real
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result.date,
                result.score,
                result.phase.value if result.phase else None,
                *dim_values,
                result.confidence,
                1 if result.source_ok else 0,
                round(result.change_from_yesterday, 2) if result.change_from_yesterday is not None else None,
                result.data_updated,
                result.raw_break_rate,
                result.zt_real,
            ),
        )
        db.commit()
    except Exception:
        pass


def load_last_score() -> float | None:
    """加载昨日 STI 分数（用于动量计算）。"""
    try:
        db = get_db()
        row = db.execute(
            "SELECT score FROM sti_timeline WHERE score IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return float(row["score"]) if row else None
    except Exception:
        return None


def load_history_scores() -> list[float]:
    """加载历史 STI 分数（用于 3 日平滑 + 动态分位数）。"""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT score FROM sti_timeline WHERE score IS NOT NULL ORDER BY date DESC LIMIT 252"
        ).fetchall()
        return [float(r["score"]) for r in rows][::-1]
    except Exception:
        return []


# ============================================================================
# S063 T1：sti_intraday 盘中采样表 CRUD
# ============================================================================

def save_intraday(snapshot: dict) -> None:
    """持久化单条盘中 snapshot 到 sti_intraday 表。

    snapshot 字段：date, time, zt_count, seal_rate, break_rate, ad_ratio,
    score, trend, t1_baseline, zone, projected_t1_score, projected_t1_weather,
    actual_score（后四者可 None）。
    """
    try:
        db = get_db()
        db.execute(
            """INSERT OR REPLACE INTO sti_intraday (
                date, time, zt_count, seal_rate, break_rate, ad_ratio,
                score, trend, t1_baseline, zone,
                projected_t1_score, projected_t1_weather, actual_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.get("date"),
                snapshot.get("time"),
                snapshot.get("zt_count"),
                snapshot.get("seal_rate"),
                snapshot.get("break_rate"),
                snapshot.get("ad_ratio"),
                snapshot.get("score"),
                snapshot.get("trend"),
                snapshot.get("t1_baseline"),
                snapshot.get("zone"),
                snapshot.get("projected_t1_score"),
                snapshot.get("projected_t1_weather"),
                snapshot.get("actual_score"),
            ),
        )
        db.commit()
    except Exception:
        pass


def load_intraday_day(date: str) -> list[dict]:
    """加载某日全部盘中 snapshot（按 time 升序）。"""
    try:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM sti_intraday WHERE date = ? ORDER BY time ASC",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def prune_intraday(keep_days: int = 60) -> int:
    """清理 keep_days 个交易日之前的盘中 snapshot。返回删除条数。"""
    try:
        db = get_db()
        # 取 keep_days+1 个交易日的日期集合（STI 表 date DESC 即交易日期序列）
        rows = db.execute(
            "SELECT DISTINCT date FROM sti_intraday ORDER BY date DESC LIMIT ?",
            (keep_days,),
        ).fetchall()
        if not rows:
            return 0
        cutoff_date = rows[-1]["date"]
        cursor = db.execute(
            "DELETE FROM sti_intraday WHERE date < ?",
            (cutoff_date,),
        )
        db.commit()
        return cursor.rowcount
    except Exception:
        return 0


def load_recent_intraday_scores(days: int = 20) -> list[dict]:
    """加载近 days 个交易日的盘中 snapshot（用于历史参照）。

    返回 [{date, time, score, trend, ...}, ...]，按 date DESC, time ASC。
    """
    try:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM sti_intraday WHERE score IS NOT NULL "
            "ORDER BY date DESC, time ASC LIMIT ?",
            (days * 20,),  # 每日约 12-14 条，取 days*20 覆盖
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
