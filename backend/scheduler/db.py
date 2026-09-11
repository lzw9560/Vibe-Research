# -*- coding: utf-8 -*-
"""SQLite 持久化——_DB_PATH / 连接 / 建表 / ScheduledTaskManager / 单例 _manager。

``_get_connection`` 在调用时读模块级 ``_DB_PATH`` global，conftest 测试 monkeypatch
``scheduler.db._DB_PATH`` 直接生效（不通过 scheduled_tasks shim 间接 patch）。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from scheduler.models import ScheduledTask, TaskRun
from vr_paths import resolve_data_dir

logger = logging.getLogger("vibe-research")

# S184 统一 DB 到 VR_DATA_DIR（.vibe-research/market_data.db）——避免 scheduler 用
# backend/data/market_data.db 而其他 DB 在 .vibe-research/ 的歧义（用户要求唯一 db 存储目录，
# CLAUDE.md §1.2 私有数据隔离）。_get_connection 读模块级 _DB_PATH，conftest monkeypatch 不变。
_DB_PATH = str(resolve_data_dir() / "market_data.db")


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    # R3：连接级 busy_timeout——写冲突时等待 30s 而非立即抛 database is locked
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_tables() -> None:
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                task_type TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                enabled INTEGER DEFAULT 1,
                notify_on_success INTEGER DEFAULT 0,
                notify_on_failure INTEGER DEFAULT 1,
                last_run_at TEXT,
                last_run_status TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                result TEXT DEFAULT '{}',
                error TEXT,
                FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backtest_daily_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                engine TEXT NOT NULL,
                hit_rate REAL,
                avg_return REAL,
                max_drawdown REAL,
                sharpe_ratio REAL,
                total_signals INTEGER,
                percentile_json TEXT,
                strategy_breakdown_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(snapshot_date, engine)
            );

            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_enabled ON scheduled_tasks(enabled);
            CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task_id ON scheduled_task_runs(task_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_backtest_snapshots_date ON backtest_daily_snapshots(snapshot_date DESC, engine);
        """)
        # R3：WAL 模式（DB 级持久）——读不阻塞写，并发写不再 database is locked
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


class ScheduledTaskManager:
    """定时任务 CRUD + 执行记录。"""

    def __init__(self):
        _ensure_tables()

    def list_tasks(self) -> List[ScheduledTask]:
        conn = _get_connection()
        try:
            rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY id DESC").fetchall()
            return [self._row_to_task(row) for row in rows]
        finally:
            conn.close()

    def get_task(self, task_id: int) -> Optional[ScheduledTask]:
        conn = _get_connection()
        try:
            row = conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None
        finally:
            conn.close()

    def create_task(self, task: ScheduledTask) -> ScheduledTask:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO scheduled_tasks (name, description, task_type, cron_expr, payload, enabled, notify_on_success, notify_on_failure)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.name,
                    task.description,
                    task.task_type,
                    task.cron_expr,
                    json.dumps(task.payload, ensure_ascii=False),
                    1 if task.enabled else 0,
                    1 if task.notify_on_success else 0,
                    1 if task.notify_on_failure else 0,
                ),
            )
            conn.commit()
            task.id = cursor.lastrowid
            return task
        finally:
            conn.close()

    def update_task(self, task: ScheduledTask) -> Optional[ScheduledTask]:
        if task.id is None:
            return None
        conn = _get_connection()
        try:
            conn.execute(
                """
                UPDATE scheduled_tasks SET
                    name = ?, description = ?, task_type = ?, cron_expr = ?, payload = ?,
                    enabled = ?, notify_on_success = ?, notify_on_failure = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    task.name,
                    task.description,
                    task.task_type,
                    task.cron_expr,
                    json.dumps(task.payload, ensure_ascii=False),
                    1 if task.enabled else 0,
                    1 if task.notify_on_success else 0,
                    1 if task.notify_on_failure else 0,
                    datetime.now().isoformat(),
                    task.id,
                ),
            )
            conn.commit()
            return self.get_task(task.id)
        finally:
            conn.close()

    def delete_task(self, task_id: int) -> bool:
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM scheduled_task_runs WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def add_run(self, run: TaskRun) -> TaskRun:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO scheduled_task_runs (task_id, status, started_at, finished_at, result, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run.task_id,
                    run.status,
                    run.started_at,
                    run.finished_at,
                    json.dumps(run.result, ensure_ascii=False),
                    run.error,
                ),
            )
            conn.commit()
            run.id = cursor.lastrowid
            return run
        finally:
            conn.close()

    def update_run(self, run: TaskRun) -> None:
        """更新一条执行记录（status / finished_at / result / error），不再二次 add_run。"""
        if run.id is None:
            return
        conn = _get_connection()
        try:
            conn.execute(
                """
                UPDATE scheduled_task_runs SET
                    status = ?, finished_at = ?, result = ?, error = ?
                WHERE id = ?
                """,
                (
                    run.status,
                    run.finished_at,
                    json.dumps(run.result, ensure_ascii=False),
                    run.error,
                    run.id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def count_running(self, task_id: int) -> int:
        """统计指定任务当前处于 running 状态的执行记录数（R4 去重辅助）。"""
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM scheduled_task_runs WHERE task_id = ? AND status = 'running'",
                (task_id,),
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()

    def reap_stale_running(self, stale_seconds: int) -> List[int]:
        """S150 R2：reap 挂死的 stale running run——started_at 早于 now-stale_seconds 的
        running run 标 failed，返被 reap 的 task_id 列表（供 CronScheduler.discard 去堵）。

        根因 B 真修：collect_once 挂死致 run 永驻 running + _running_task_ids 堵 dedup，
        即使 R1 timeout 兜底（双保险），reaper 每轮清 DB stale + 返 task_id 让调度器 discard。
        """
        from datetime import datetime as _dt, timedelta
        cutoff = (_dt.now() - timedelta(seconds=stale_seconds)).isoformat()
        conn = _get_connection()
        try:
            stale = conn.execute(
                "SELECT id, task_id FROM scheduled_task_runs "
                "WHERE status = 'running' AND started_at < ?",
                (cutoff,),
            ).fetchall()
            if not stale:
                return []
            reaped_task_ids: List[int] = []
            for row in stale:
                conn.execute(
                    "UPDATE scheduled_task_runs SET status = 'failed', "
                    "finished_at = ?, error = ? WHERE id = ?",
                    (_dt.now().isoformat(),
                     f"reaped stale (>{stale_seconds}s, S150 R2)", row["id"]),
                )
                if row["task_id"] is not None:
                    reaped_task_ids.append(int(row["task_id"]))
            conn.commit()
            return reaped_task_ids
        finally:
            conn.close()

    def update_task_status(self, task_id: int, status: Optional[str], last_run_at: Optional[str] = None) -> None:
        conn = _get_connection()
        try:
            conn.execute(
                """
                UPDATE scheduled_tasks SET last_run_status = ?, last_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, last_run_at, datetime.now().isoformat(), task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_runs(self, task_id: int, limit: int = 50) -> List[TaskRun]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM scheduled_task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
            return [self._row_to_run(row) for row in rows]
        finally:
            conn.close()

    def _row_to_task(self, row: sqlite3.Row) -> ScheduledTask:
        return ScheduledTask(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            task_type=row["task_type"],
            cron_expr=row["cron_expr"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            enabled=bool(row["enabled"]),
            notify_on_success=bool(row["notify_on_success"]),
            notify_on_failure=bool(row["notify_on_failure"]),
            last_run_at=row["last_run_at"],
            last_run_status=row["last_run_status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_run(self, row: sqlite3.Row) -> TaskRun:
        return TaskRun(
            id=row["id"],
            task_id=row["task_id"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result=json.loads(row["result"]) if row["result"] else {},
            error=row["error"],
        )


# S150 R1：per-task_type 超时（秒），防 collect_once 挂死永堵（fork 根因 B：em_get
# 网络挂顿→collect_once 永挂→_running_task_ids 堵 dedup→task 永不触发）。
# seal collect 应 <60s（交易时段每分钟跑），120s 兜底；limitup_precompute 内部
# asyncio.run(wait_for 600s)（line 652），外层 700s 双保险；默认 300s。
_TASK_TIMEOUTS: Dict[str, int] = {
    "seal_intraday_collect": 120,
    "limitup_precompute": 700,
    "kline_refresh": 1200,  # S150 审查 HIGH2: 全A~5540股 baostock 稳态>300s, 加显式高值防误杀（当日 bar 缺失回归）
    "intraday_microstructure_snapshot": 120,  # S167：hithink 3 端点 + tencent 1 批，<60s 稳态，120s 兜底
    "intraday_auction_dense": 90,  # S167：竞价密集采集，hithink limit_up_pool + auction_snapshot 2 调用，<30s 稳态，90s 兜底
    "baostock_5min_freeze": 600,  # S167：~100 股 baostock 5min fetch（无 IP 限制，单次 login）
}
_DEFAULT_TASK_TIMEOUT = 300

# S150 R2：stale run reaper 阈值（秒）——超此的 running run 视为挂死，reap 为 failed
_REAPER_STALE_SECONDS = 1300  # > max(_TASK_TIMEOUTS)=1200(kline_refresh) + buffer

# S150 T0.7 根治：seal_intraday_collect subprocess 超时（< R1 wait_for 120 避免竞态——
# subprocess 先 SIGKILL+线程返回，R1 wait_for 不触发，无孤儿线程）。
_SEAL_COLLECT_SUBPROCESS_TIMEOUT = 110


def _task_timeout(task: "ScheduledTask") -> int:
    """S150 R1：按 task_type 返回超时秒数。"""
    return _TASK_TIMEOUTS.get(task.task_type, _DEFAULT_TASK_TIMEOUT)


# 模块级单例——所有子模块共享同一实例（不另建）
_manager = ScheduledTaskManager()
