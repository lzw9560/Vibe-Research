# -*- coding: utf-8 -*-
"""limitup_screener 数据层 —— 数据库连接、迁移、读写。"""

from __future__ import annotations

import os
import sqlite3
import threading as _threading
from pathlib import Path

from config import default_config

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), default_config.DB_PATH)
_DB_LOCK = _threading.Lock()


def run_migrations() -> None:
    """执行数据库迁移（仅一次）。"""
    from migrations import MigrationManager
    manager = MigrationManager(db_path=_DB_PATH)
    migration_sql = (
        Path(__file__).resolve().parent
        / "migrations" / "limitup_screener" / "20250613-001_create_gene_scores.sql"
    ).read_text(encoding="utf-8")
    migrations = [
        {
            "version": "20250613-001",
            "name": "create_gene_scores",
            "sql": migration_sql,
        }
    ]
    manager.upgrade(migrations)


def get_db() -> sqlite3.Connection:
    """获取 SQLite 连接（单例，线程安全）。"""
    with _DB_LOCK:
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn


def save_gene_scores(date: str, scores: list) -> None:
    """保存基因得分到数据库。"""
    conn = get_db()
    with _DB_LOCK:
        conn.execute("BEGIN TRANSACTION")
        try:
            for s in scores:
                conn.execute("""
                    INSERT OR REPLACE INTO gene_scores
                    (date, code, name, total_score, factor_premium_rate, factor_red_rate,
                     factor_seal_rate, factor_rebound_rate, factor_freq_score,
                     wilson_adjusted, qualify, high_gene, zt_count_250d)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date, s.code, s.name, s.total_score,
                    s.factors.get("次日溢价率", 0),
                    s.factors.get("红盘率", 0),
                    s.factors.get("封板率", 0),
                    s.factors.get("炸板后溢价", 0),
                    s.factors.get("涨停频次", 0),
                    s.wilson_adjusted,
                    1 if s.qualify else 0,
                    1 if s.high_gene else 0,
                    s.zt_count_250d,
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def load_gene_scores(date: str) -> list | None:
    """从数据库加载基因得分。如果不存在则返回 None。"""
    conn = get_db()
    with _DB_LOCK:
        rows = conn.execute(
            "SELECT * FROM gene_scores WHERE date = ? ORDER BY total_score DESC",
            (date,),
        ).fetchall()
        conn.close()

    if not rows:
        return None

    scores = []
    for row in rows:
        factors = {
            "次日溢价率": row["factor_premium_rate"] or 0,
            "红盘率": row["factor_red_rate"] or 0,
            "封板率": row["factor_seal_rate"] or 0,
            "炸板后溢价": row["factor_rebound_rate"] or 0,
            "涨停频次": row["factor_freq_score"] or 0,
        }
        scores.append({
            "code": row["code"],
            "name": row["name"] or "",
            "total_score": row["total_score"] or 0,
            "factors": factors,
            "wilson_adjusted": row["wilson_adjusted"] or 0,
            "qualify": bool(row["qualify"]),
            "high_gene": bool(row["high_gene"]),
            "last_zt_dates": [],
            "zt_count_250d": row["zt_count_250d"] or 0,
        })
    return scores
