# -*- coding: utf-8 -*-
"""S061 预测账本 —— 判断跟踪 + 到期自动验证 + 命中率统计。

与 win_rate_tracker 的关系：
- win_rate_tracker 记**已执行交易**的胜率
- prediction_ledger 记**判断**（含未执行的）→ 到期自动对账 → 按来源统计命中率

状态机：pending → hit/miss/expired/voided（voided=K 线缺数）
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import WINRATE_DB_PATH  # 复用 winrate.db（语义分离表，库共用）
from migrations import MigrationManager

_logger = logging.getLogger("vibe-research")
_DB_LOCK = threading.Lock()

PREDICTION_SOURCES = {"funnel_candidate", "strategy_hit", "manual"}
PREDICTION_STATUSES = {"pending", "hit", "miss", "expired", "voided"}


@dataclass
class Prediction:
    """单条预测。"""
    stated_at: str           # 预测发出日
    source: str              # funnel_candidate | strategy_hit | manual
    code: str                # 股票代码
    name: str = ""
    signal_ref: str = ""     # funnel:final / 战法 code / 空
    prediction_type: str = "next_day_premium"  # next_day_premium | strategy_outcome
    baseline_price: float = 0.0
    expected: str = ">0"     # 预期方向
    horizon: int = 1        # 验证周期（天数）
    due_date: str = ""      # 到期日
    actual_return: float | None = None
    status: str = "pending"  # pending | hit | miss | expired | voided
    attribution: str = ""
    id: int | None = None
    verified_at: str | None = None


def _migrate_schema(db_path: str = WINRATE_DB_PATH) -> None:
    """执行 prediction_ledger 表迁移。"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    manager = MigrationManager(db_path=db_path)
    sql = (
        Path(__file__).resolve().parent
        / "migrations" / "prediction_ledger" / "20260812-001_create_prediction_ledger.sql"
    ).read_text(encoding="utf-8")
    manager.upgrade([{
        "version": "20260812-001",
        "name": "create_prediction_ledger",
        "sql": sql,
    }])


def _get_conn(db_path: str = WINRATE_DB_PATH) -> sqlite3.Connection:
    _migrate_schema(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_prediction(row: sqlite3.Row) -> Prediction:
    return Prediction(
        id=row["id"],
        stated_at=row["stated_at"],
        source=row["source"],
        code=row["code"],
        name=row["name"] or "",
        signal_ref=row["signal_ref"] or "",
        prediction_type=row["prediction_type"],
        baseline_price=row["baseline_price"] or 0.0,
        expected=row["expected"] or "",
        horizon=row["horizon"],
        due_date=row["due_date"],
        actual_return=row["actual_return"],
        status=row["status"],
        attribution=row["attribution"] or "",
        verified_at=row["verified_at"],
    )


def add_prediction(p: Prediction, db_path: str = WINRATE_DB_PATH) -> int | None:
    """入账单条预测。幂等：同日同源同股只一条（UNIQUE 约束 + OR IGNORE）。

    返回 row id（新建）或 None（已存在/忽略）。
    """
    if p.source not in PREDICTION_SOURCES:
        raise ValueError(f"非法 source: {p.source}")
    if p.status not in PREDICTION_STATUSES:
        raise ValueError(f"非法 status: {p.status}")
    if not p.due_date:
        p.due_date = _compute_due_date(p.stated_at, p.horizon)
    conn = _get_conn(db_path)
    try:
        with _DB_LOCK:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO prediction_ledger
                (stated_at, source, signal_ref, code, name, prediction_type,
                 baseline_price, expected, horizon, due_date, status, attribution)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (p.stated_at, p.source, p.signal_ref or None, p.code, p.name or None,
                 p.prediction_type, p.baseline_price or None, p.expected or None,
                 p.horizon, p.due_date, p.status, p.attribution or None),
            )
            conn.commit()
            if cur.rowcount > 0:
                return cur.lastrowid
            return None
    finally:
        conn.close()


def _compute_due_date(stated_at: str, horizon: int, db_path: str = WINRATE_DB_PATH) -> str:
    """计算到期日：stated_at + horizon 个交易日。

    简化口径：交易日历取 gene_scores 已有日（防封），若无则按工作日推算。
    """
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE date > ? ORDER BY date LIMIT ?",
            (stated_at, horizon),
        ).fetchall()
        conn.close()
        if len(rows) >= horizon:
            return rows[horizon - 1][0]
    except Exception:
        pass
    # 兜底：按工作日推算（周一到周五）
    try:
        base = datetime.strptime(stated_at, "%Y-%m-%d").date()
    except ValueError:
        return stated_at
    added = 0
    cur = base
    while added < horizon:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur.strftime("%Y-%m-%d")


def get_pending_predictions(db_path: str = WINRATE_DB_PATH) -> list[Prediction]:
    """取所有待验证预测。"""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM prediction_ledger WHERE status = ? ORDER BY due_date",
            ("pending",),
        ).fetchall()
        return [_row_to_prediction(r) for r in rows]
    finally:
        conn.close()


def get_due_predictions(as_of: str, db_path: str = WINRATE_DB_PATH) -> list[Prediction]:
    """取到期日 <= as_of 的待验证预测。"""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM prediction_ledger WHERE status = ? AND due_date <= ? ORDER BY due_date",
            ("pending", as_of),
        ).fetchall()
        return [_row_to_prediction(r) for r in rows]
    finally:
        conn.close()


def verify_prediction(pred_id: int, actual_return: float | None,
                      status: str, attribution: str = "",
                      db_path: str = WINRATE_DB_PATH) -> bool:
    """写验证结果。status ∈ {hit, miss, voided}。幂等：已验证的不重写。"""
    if status not in {"hit", "miss", "voided"}:
        raise ValueError(f"非法验证 status: {status}")
    conn = _get_conn(db_path)
    try:
        with _DB_LOCK:
            cur = conn.execute(
                """
                UPDATE prediction_ledger
                SET actual_return = ?, status = ?, attribution = ?, verified_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (actual_return, status, attribution or None, datetime.now().isoformat(), pred_id),
            )
            conn.commit()
            return cur.rowcount > 0
    finally:
        conn.close()


def list_predictions(days: int = 30, source: str = "",
                     db_path: str = WINRATE_DB_PATH) -> list[Prediction]:
    """账本列表：最近 N 天，可按 source 过滤。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = _get_conn(db_path)
    try:
        if source:
            rows = conn.execute(
                "SELECT * FROM prediction_ledger WHERE stated_at >= ? AND source = ? ORDER BY stated_at DESC",
                (cutoff, source),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM prediction_ledger WHERE stated_at >= ? ORDER BY stated_at DESC",
                (cutoff,),
            ).fetchall()
        return [_row_to_prediction(r) for r in rows]
    finally:
        conn.close()


def compute_hit_rate(source: str = "", days: int = 30,
                     db_path: str = WINRATE_DB_PATH) -> dict[str, Any]:
    """命中率统计：按 source 分桶。n<10 标注样本不足。

    返回 [{source, total, hit, miss, voided, hit_rate, sample_sufficient}]。
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = _get_conn(db_path)
    try:
        if source:
            rows = conn.execute(
                """SELECT source,
                          COUNT(*) as total,
                          SUM(CASE WHEN status='hit' THEN 1 ELSE 0 END) as hit,
                          SUM(CASE WHEN status='miss' THEN 1 ELSE 0 END) as miss,
                          SUM(CASE WHEN status='voided' THEN 1 ELSE 0 END) as voided
                   FROM prediction_ledger
                   WHERE stated_at >= ? AND source = ?
                   GROUP BY source""",
                (cutoff, source),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT source,
                          COUNT(*) as total,
                          SUM(CASE WHEN status='hit' THEN 1 ELSE 0 END) as hit,
                          SUM(CASE WHEN status='miss' THEN 1 ELSE 0 END) as miss,
                          SUM(CASE WHEN status='voided' THEN 1 ELSE 0 END) as voided
                   FROM prediction_ledger
                   WHERE stated_at >= ?
                   GROUP BY source""",
                (cutoff,),
            ).fetchall()
        result = []
        for r in rows:
            verified = (r["hit"] or 0) + (r["miss"] or 0)
            hit = r["hit"] or 0
            rate = round(hit / verified, 4) if verified else None
            result.append({
                "source": r["source"],
                "total": r["total"],
                "hit": hit,
                "miss": r["miss"] or 0,
                "voided": r["voided"] or 0,
                "hit_rate": rate,
                "sample_sufficient": verified >= 10,
                "verified": verified,
            })
        return result
    finally:
        conn.close()


def expire_overdue(as_of: str, db_path: str = WINRATE_DB_PATH) -> int:
    """把到期日 < as_of 仍未验证的 pending 标记为 expired（K 线实在拿不到的兜底）。"""
    conn = _get_conn(db_path)
    try:
        with _DB_LOCK:
            cur = conn.execute(
                """UPDATE prediction_ledger
                   SET status = 'expired', verified_at = ?
                   WHERE status = 'pending' AND due_date < ?""",
                (datetime.now().isoformat(), as_of),
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()
