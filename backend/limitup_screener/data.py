# -*- coding: utf-8 -*-
"""limitup_screener 数据层 —— 数据库连接、迁移、读写。"""

from __future__ import annotations

import os
import sqlite3
import threading as _threading
from datetime import datetime
from pathlib import Path

from config import default_config

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), default_config.DB_PATH)
_DB_LOCK = _threading.Lock()


def run_migrations() -> None:
    """执行数据库迁移（仅一次）。"""
    from migrations import MigrationManager
    manager = MigrationManager(db_path=_DB_PATH)
    migration_v1 = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "limitup_screener" / "20250613-001_create_gene_scores.sql"
    ).read_text(encoding="utf-8")
    migration_v2 = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "limitup_screener" / "20250613-002_add_gene_scores_indexes.sql"
    ).read_text(encoding="utf-8")
    migration_v3 = (
        Path(__file__).resolve().parent.parent
        / "migrations" / "limitup_screener" / "20250724-001_create_fuse_pardon_records.sql"
    ).read_text(encoding="utf-8")
    migrations = [
        {
            "version": "20250613-001",
            "name": "create_gene_scores",
            "sql": migration_v1,
        },
        {
            "version": "20250613-002",
            "name": "add_gene_scores_indexes",
            "sql": migration_v2,
        },
        {
            "version": "20250724-001",
            "name": "create_fuse_pardon_records",
            "sql": migration_v3,
        },
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
        try:
            rows = [
                (
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
                )
                for s in scores
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO gene_scores
                (date, code, name, total_score, factor_premium_rate, factor_red_rate,
                 factor_seal_rate, factor_rebound_rate, factor_freq_score,
                 wilson_adjusted, qualify, high_gene, zt_count_250d)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def load_gene_scores(date: str) -> list | None:
    """从数据库加载基因得分。如果不存在则返回 None。"""
    from limitup_screener.models import GeneScore

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
        scores.append(GeneScore(
            code=row["code"],
            name=row["name"] or "",
            total_score=row["total_score"] or 0,
            factors=factors,
            wilson_adjusted=row["wilson_adjusted"] or 0,
            qualify=bool(row["qualify"]),
            high_gene=bool(row["high_gene"]),
            last_zt_dates=[],
            zt_count_250d=row["zt_count_250d"] or 0,
        ))
    return scores


# =============================================================================
# V2.0.3 新增：仓位熔断赦免记录
# =============================================================================


def create_pardon_record(record: dict) -> None:
    """创建赦免记录。"""
    conn = get_db()
    with _DB_LOCK:
        try:
            conn.execute("""
                INSERT INTO fuse_pardon_records
                (id, strategy_code, strategy_name, enabled_by, enabled_ip,
                 approved_by, max_position_pct, created_at, expires_at, reason, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record["id"],
                record["strategy_code"],
                record["strategy_name"],
                record["enabled_by"],
                record.get("enabled_ip"),
                record["approved_by"],
                record.get("max_position_pct", 0.35),
                record["created_at"],
                record["expires_at"],
                record.get("reason", ""),
                1 if record.get("is_active", True) else 0,
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_active_pardon_records() -> list[dict]:
    """获取所有生效中的赦免记录。"""
    conn = get_db()
    with _DB_LOCK:
        rows = conn.execute("""
            SELECT * FROM fuse_pardon_records
            WHERE is_active = 1 AND expires_at > ?
            ORDER BY created_at DESC
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
        conn.close()

    return [dict(row) for row in rows]


def get_all_pardon_records(limit: int = 100) -> list[dict]:
    """获取所有赦免记录（包括已撤销的）。"""
    conn = get_db()
    with _DB_LOCK:
        rows = conn.execute("""
            SELECT * FROM fuse_pardon_records
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

    return [dict(row) for row in rows]


def revoke_pardon_record(pardon_id: str, revoked_by: str) -> bool:
    """撤销赦免记录。"""
    conn = get_db()
    with _DB_LOCK:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor = conn.execute("""
                UPDATE fuse_pardon_records
                SET is_active = 0, revoked_at = ?, revoked_by = ?
                WHERE id = ? AND is_active = 1
            """, (now, revoked_by, pardon_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def update_pardon_outcome(pardon_id: str, outcome: dict) -> bool:
    """更新赦免交易结果。"""
    import json
    conn = get_db()
    with _DB_LOCK:
        try:
            cursor = conn.execute("""
                UPDATE fuse_pardon_records
                SET outcome_json = ?
                WHERE id = ?
            """, (json.dumps(outcome, ensure_ascii=False), pardon_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def cleanup_expired_pardons() -> int:
    """清理过期的赦免记录（将过期但仍标记为生效的记录设为失效）。"""
    conn = get_db()
    with _DB_LOCK:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor = conn.execute("""
                UPDATE fuse_pardon_records
                SET is_active = 0
                WHERE is_active = 1 AND expires_at <= ?
            """, (now,))
            conn.commit()
            return cursor.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
