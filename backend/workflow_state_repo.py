# -*- coding: utf-8 -*-
"""打板工作流状态落库（S032 R10）。

七态状态机（workflow_state_machine）的持久化层：
- workflow_state：(code, trade_date) 的当前状态，UNIQUE(code, trade_date)
- workflow_state_history：每次流转一条（from/to/reason），可回放审计

与 scheduled_tasks 同库（backend/data/market_data.db），连接模式平行
（busy_timeout=30000 + WAL）。流转规则复用 workflow_state_machine 的
_ALLOWED_TRANSITIONS（经 WorkflowStateMachine.transition），不复制规则表。

接线模型（S032 D3）：
- 盘前 run() 自动落 candidate/filtered（insert-if-absent，不回退已进阶状态）；
- 其余流转走 routers/workflow.py 手动 API——watching/monitoring/holding 的语义
  是「用户在盯/在持有」，盘中自动推进未实现（S012 桩范围），系统无数据源自动推进。

落库是增强不是正确性依赖：调用方（pre_market_workflow）须 try/except 隔离。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from workflow_state_machine import WorkflowStateMachine, WorkflowStatus

logger = logging.getLogger("vibe-research")

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market_data.db")


# ============================================================================
# 数据库操作
# ============================================================================


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    # 连接级 busy_timeout：写冲突时等待 30s 而非立即抛 database is locked
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_tables() -> None:
    conn = _get_connection()
    try:
        if not _migrate_legacy_tables(conn):
            return  # 旧 schema 非空：保留原表，不建新表（避免索引列冲突）
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT DEFAULT '',
                trade_date TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(code, trade_date)
            );

            CREATE TABLE IF NOT EXISTS workflow_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                reason TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_workflow_state_date ON workflow_state(trade_date);
            CREATE INDEX IF NOT EXISTS idx_workflow_state_history_code
                ON workflow_state_history(code, trade_date);
        """)
        # WAL 模式（DB 级持久）：读不阻塞写
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """S033 R1：幂等扩列 entry_price/exit_price/strategy（holding/settled 结算输入，为 S034 铺路）。

    PRAGMA table_info 检查列已存在则跳过；旧数据三新列为 NULL 不影响查询。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_state)").fetchall()}
    for col, typ in (
        ("entry_price", "REAL"),
        ("exit_price", "REAL"),
        ("strategy", "TEXT"),
        ("settled_at", "TEXT"),  # S034：结算幂等锚点（结算写 winrate 后落戳）
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE workflow_state ADD COLUMN {col} {typ}")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _migrate_legacy_tables(conn: sqlite3.Connection) -> bool:
    """处置旧实验残留的 workflow_state 表（列名 date/transitioned_at 的旧 schema）。

    返回 True = 可按新 schema 建表；False = 旧表非空保留不动（绝不毁数据，
    届时需人工迁移）。旧表无任何在仓代码引用（rg 验证），属历史实验残留。
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_state'"
    ).fetchone()
    if row is None:
        return True
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_state)").fetchall()}
    if "trade_date" in cols:
        return True  # 已是新 schema
    state_n = conn.execute("SELECT COUNT(*) FROM workflow_state").fetchone()[0]
    has_history = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_state_history'"
    ).fetchone()
    history_n = (
        conn.execute("SELECT COUNT(*) FROM workflow_state_history").fetchone()[0]
        if has_history else 0
    )
    if state_n == 0 and history_n == 0:
        logger.info("[workflow_state] 检测到空旧 schema 表，DROP 重建（S032 迁移）")
        conn.execute("DROP TABLE workflow_state")
        if has_history:
            conn.execute("DROP TABLE workflow_state_history")
        conn.commit()
        return True
    logger.warning(
        "[workflow_state] 旧 schema 表非空（state=%d history=%d），保留不动；"
        "S032 新表未建，状态端点将不可用，请人工迁移", state_n, history_n,
    )
    return False


def _row_to_state(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "trade_date": row["trade_date"],
        "status": row["status"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # S033 R1：扩列字段（旧行可能为 NULL；row 无列时兜底 None）
        "entry_price": row["entry_price"] if "entry_price" in row.keys() else None,
        "exit_price": row["exit_price"] if "exit_price" in row.keys() else None,
        "strategy": row["strategy"] if "strategy" in row.keys() else None,
        "settled_at": row["settled_at"] if "settled_at" in row.keys() else None,
    }


def _row_to_history(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "code": row["code"],
        "trade_date": row["trade_date"],
        "from_status": row["from_status"],
        "to_status": row["to_status"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }


# ============================================================================
# 查询
# ============================================================================


def get_state(code: str, trade_date: str) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM workflow_state WHERE code = ? AND trade_date = ?",
            (code, trade_date),
        ).fetchone()
        return _row_to_state(row) if row else None
    finally:
        conn.close()


def list_states(trade_date: str) -> List[Dict[str, Any]]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_state WHERE trade_date = ? ORDER BY code",
            (trade_date,),
        ).fetchall()
        return [_row_to_state(r) for r in rows]
    finally:
        conn.close()


def get_history(code: str, trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = _get_connection()
    try:
        if trade_date is None:
            rows = conn.execute(
                "SELECT * FROM workflow_state_history WHERE code = ? ORDER BY id",
                (code,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM workflow_state_history WHERE code = ? AND trade_date = ? ORDER BY id",
                (code, trade_date),
            ).fetchall()
        return [_row_to_history(r) for r in rows]
    finally:
        conn.close()


# ============================================================================
# 写入
# ============================================================================


def _insert_initial(
    code: str, name: str, trade_date: str, target: WorkflowStatus, reason: str
) -> bool:
    """insert-if-absent：行不存在才写（初始态 pending→target），已存在跳过。

    语义（D3）：盘前重跑不得把用户已推进的状态（watching/holding/…）回退，
    故冲突时 DO NOTHING——是否写入以 rowcount 判定。
    """
    now = _now_iso()
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO workflow_state (code, name, trade_date, status, reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, trade_date) DO NOTHING
            """,
            (code, name, trade_date, target.value, reason, now, now),
        )
        if cursor.rowcount == 0:
            conn.commit()
            return False
        conn.execute(
            """
            INSERT INTO workflow_state_history (code, trade_date, from_status, to_status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (code, trade_date, WorkflowStatus.PENDING.value, target.value, reason, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def ensure_candidate(code: str, name: str, trade_date: str, reason: str = "") -> bool:
    """盘前 qualified 候选落 candidate 态（insert-if-absent）。"""
    return _insert_initial(code, name, trade_date, WorkflowStatus.CANDIDATE, reason)


def ensure_filtered(code: str, name: str, trade_date: str, reason: str = "") -> bool:
    """盘前未达标股落 filtered 态（insert-if-absent）。"""
    return _insert_initial(code, name, trade_date, WorkflowStatus.FILTERED, reason)


def allowed_targets(code: str, trade_date: str) -> List[str]:
    """当前状态允许的目标态（供端点 400 提示；无记录返回空）。"""
    current = get_state(code, trade_date)
    if current is None:
        return []
    machine = WorkflowStateMachine(WorkflowStatus(current["status"]))
    return [s.value for s in machine.allowed_targets()]


def transition(
    code: str,
    trade_date: str,
    target: str,
    reason: str = "",
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    strategy: Optional[str] = None,
) -> tuple[bool, str]:
    """手动流转：读当前态 → 状态机规则校验 → UPDATE + history。

    规则单一事实源：复用 WorkflowStateMachine.transition（_ALLOWED_TRANSITIONS）。
    S033 R2：entry_price/exit_price/strategy 为用户自填操作记录（holding 买入价/
    settled 卖出价/战法），COALESCE 语义——传 None 不覆盖已有值。
    返回 (ok, detail)：非法/未知/无记录时 ok=False，detail 说明当前态与允许目标。
    """
    try:
        target_status = WorkflowStatus(target)
    except ValueError:
        allowed = [s.value for s in WorkflowStatus]
        return False, f"未知目标状态: {target}（合法值: {', '.join(allowed)}）"

    current = get_state(code, trade_date)
    if current is None:
        return False, f"该日无此股的工作流状态记录: code={code} date={trade_date}"

    machine = WorkflowStateMachine(WorkflowStatus(current["status"]))
    if not machine.transition(target_status, reason):
        allowed_targets = [s.value for s in machine.allowed_targets()]
        return (
            False,
            f"当前状态 {current['status']} 不允许流转到 {target}"
            f"（允许: {', '.join(allowed_targets) or '无'}）",
        )

    now = _now_iso()
    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE workflow_state
            SET status = ?, reason = ?, updated_at = ?,
                entry_price = COALESCE(?, entry_price),
                exit_price = COALESCE(?, exit_price),
                strategy = COALESCE(?, strategy)
            WHERE code = ? AND trade_date = ?
            """,
            (
                target_status.value, reason, now,
                entry_price, exit_price, strategy,
                code, trade_date,
            ),
        )
        conn.execute(
            """
            INSERT INTO workflow_state_history (code, trade_date, from_status, to_status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (code, trade_date, current["status"], target_status.value, reason, now),
        )
        # S034 R4：流转到 candidate = 新一轮（settled/filtered 重入）——清结算锚点，新轮可再结算
        if target_status == WorkflowStatus.CANDIDATE:
            conn.execute(
                "UPDATE workflow_state SET settled_at = NULL WHERE code = ? AND trade_date = ?",
                (code, trade_date),
            )
        conn.commit()
    finally:
        conn.close()
    return True, "ok"


def mark_settled(code: str, trade_date: str, settled_at: str) -> None:
    """S034：结算成功落幂等锚点（winrate 记录写入后调用）。"""
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE workflow_state SET settled_at = ?, updated_at = ? WHERE code = ? AND trade_date = ?",
            (settled_at, _now_iso(), code, trade_date),
        )
        conn.commit()
    finally:
        conn.close()


def get_state_with_targets(code: str, trade_date: str) -> Optional[Dict[str, Any]]:
    """S033 R3：单股状态 + 当前态允许的目标态（无记录返 None）。"""
    state = get_state(code, trade_date)
    if state is None:
        return None
    machine = WorkflowStateMachine(WorkflowStatus(state["status"]))
    return {**state, "allowed_targets": [s.value for s in machine.allowed_targets()]}


# 模块导入即建表（平行 scheduled_tasks 的 _manager 模式；WAL 为 DB 级持久）
_ensure_tables()
