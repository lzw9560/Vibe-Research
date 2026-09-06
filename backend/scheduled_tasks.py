# -*- coding: utf-8 -*-
"""定时任务系统 —— 基于 SQLite 持久化的 cron-like 调度器。"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vibe-research")

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market_data.db")


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class ScheduledTask:
    """定时任务定义。"""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    task_type: str = ""
    cron_expr: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    notify_on_success: bool = False
    notify_on_failure: bool = True
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TaskRun:
    """单次任务执行记录。"""
    id: Optional[int] = None
    task_id: int = 0
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: Optional[str] = None
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ============================================================================
# 数据库操作
# ============================================================================


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


# ============================================================================
# 任务管理器
# ============================================================================


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


# ============================================================================
# 任务执行器
# ============================================================================


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


# S150 R1：per-task_type 超时（秒），防 collect_once 挂死永堵（fork 根因 B：em_get
# 网络挂顿→collect_once 永挂→_running_task_ids 堵 dedup→task 永不触发）。
# seal collect 应 <60s（交易时段每分钟跑），120s 兜底；limitup_precompute 内部
# asyncio.run(wait_for 600s)（line 652），外层 700s 双保险；默认 300s。
_TASK_TIMEOUTS: Dict[str, int] = {
    "seal_intraday_collect": 120,
    "limitup_precompute": 700,
    "kline_refresh": 1200,  # S150 审查 HIGH2: 全A~5540股 baostock 稳态>300s, 加显式高值防误杀（当日 bar 缺失回归）
    "intraday_microstructure_snapshot": 120,  # S167：hithink 3 端点 + tencent 1 批，<60s 稳态，120s 兜底
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


class TaskExecutor:
    """内置任务执行器。"""

    def __init__(self):
        self._executors = {
            "daily_data_refresh": self._execute_daily_data_refresh,
            "daily_review_notify": self._execute_daily_review_notify,
            "limitup_precompute": self._execute_limitup_precompute,
            "portfolio_refresh": self._execute_portfolio_refresh,
            "market_data_sync": self._execute_market_data_sync,
            "cleanup_old_runs": self._execute_cleanup_old_runs,
            "daily_backtest_run": self._execute_daily_backtest_run,  # S041：回测定时任务
            "sti_post_market": self._execute_sti_post_market,  # S063 T3：STI 盘后定时计算
            "seal_intraday_collect": self._execute_seal_intraday_collect,  # S055：盘中封单时序采集
            "candidate_funnel_precompute": self._execute_candidate_funnel_precompute,  # S004 R5：盘后漏斗预计算
            "first_board_filter": self._execute_first_board_filter,  # S075：盘后首板流筛选+评分
            "s066_validation_checkpoint": self._execute_s066_validation_checkpoint,  # §44 60 天复验检查点（提醒任务）
            "evaluation_backtest": self._execute_evaluation_backtest,  # S151 R3：评价层 30日首次/60日复验检查点（提醒任务）
            "forward_test_daily": self._execute_forward_test_daily,  # S069 R1：每日记 forward_test picks+universe
            "forward_test_t1_settle": self._execute_forward_test_t1_settle,  # S069 R2：T+1 收益回填
            "first_board_t1_review": self._execute_first_board_t1_review,  # S075：T+1 溢价评分+复盘报告+飞书
            "first_board_quote_probe": self._execute_first_board_quote_probe,  # S076：盘中多源行情探查（临时研究）
            "zt_history_snapshot": self._execute_zt_history_snapshot,  # S078：涨停历史 snapshot 数据地基
            "derived_precompute": self._execute_derived_precompute,  # S084 C1：盘后 derived 异步预采集
            "monthly_vacuum": self._execute_monthly_vacuum,  # S089 D2：月度 VACUUM + wal_checkpoint
            "kline_refresh": self._execute_kline_refresh,  # S090 B：baostock_kline_cache 日更
            "daily_ai_summary": self._execute_daily_ai_summary,  # S093 R12：AI 盘后总结 stub
            "premarket_auction_notify": self._execute_premarket_auction_notify,  # S101：9:25 竞价确认通知
            "premarket_open_notify": self._execute_premarket_open_notify,  # S101：9:35 开盘表现通知
            "premarket_t1_review": self._execute_premarket_t1_review,  # S101：T+1 复盘通知
            "st_play_radar": self._execute_st_play_radar,  # S148 R3：ST-play radar 白名单（摘帽/重组/扭亏 carve-out）
            "intraday_microstructure_snapshot": self._execute_intraday_microstructure_snapshot,  # S167：盘中微结构周期快照（hithink 排名 + tencent 量比，10min）
            "baostock_5min_freeze": self._execute_baostock_5min_freeze,  # S167：次日冻结 prev_trading_date 涨停股 5min bars
        }
        # S150 审查 HIGH1 根治：调度器独占 ThreadPoolExecutor，隔离 to_thread 泄漏——
        # 调度器线程全挂也不影响路由器的 asyncio.to_thread（71 调用方共享默认池）。
        self._thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scheduler")

    def execute(self, task: ScheduledTask) -> TaskRun:
        run = TaskRun(task_id=task.id or 0, status="running")
        run = _manager.add_run(run)
        started_at = run.started_at

        try:
            executor = self._executors.get(task.task_type)
            if executor is None:
                raise ValueError(f"未知任务类型: {task.task_type}")

            result = executor(task.payload)
            run.status = "success"
            run.result = result
            run.finished_at = datetime.now().isoformat()
            _manager.update_task_status(task.id or 0, "success", started_at)

            # 成功通知
            if task.notify_on_success:
                self._send_notification(task, run, "success")

            return run
        except Exception as e:
            logger.exception("[scheduled_task] 任务执行失败: %s", e)
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now().isoformat()
            _manager.update_task_status(task.id or 0, "failed", started_at)

            # 失败通知
            if task.notify_on_failure:
                self._send_notification(task, run, "failed")

            return run
        finally:
            # R2：同一记录就地更新终态，不再二次 add_run（避免每次执行产生两条 run）
            _manager.update_run(run)

    async def execute_async(self, task: ScheduledTask) -> TaskRun:
        """协程版执行：落一条 run 记录（开头 add_run + 结尾 update_run）。

        - handler 为协程函数则直接 await，普通函数经 asyncio.to_thread 在线程执行
        - 未知任务类型 → 落一条 failed run，不抛异常
        - 成功/失败均 update_run + update_task_status + 通知，全程只一条 run 记录
        """
        run = TaskRun(task_id=task.id or 0, status="running")
        run = _manager.add_run(run)
        started_at = run.started_at

        handler = self._executors.get(task.task_type)
        if handler is None:
            run.status = "failed"
            run.error = f"未知任务类型: {task.task_type}"
            run.finished_at = datetime.now().isoformat()
            _manager.update_run(run)
            _manager.update_task_status(task.id or 0, "failed", started_at)
            if task.notify_on_failure:
                self._send_notification(task, run, "failed")
            return run

        try:
            if inspect.iscoroutinefunction(handler):  # py3.16: asyncio.iscoroutinefunction 已移除，用 inspect
                result = await asyncio.wait_for(handler(task.payload), timeout=_task_timeout(task))
            else:
                # S150 R1 + 审查 HIGH1 根治：同步 handler 走调度器独占 _thread_pool
                #（run_in_executor 替代 asyncio.to_thread），隔离泄漏——调度器线程全挂
                # 也不影响路由器默认池。wait_for 超时仍 cancel future（底层线程不可取消，
                # 但独占池爆炸半径限在调度器，不冻 API；HIGH3 重复写库另由 subprocess/async 根治）。
                result = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(self._thread_pool, handler, task.payload),
                    timeout=_task_timeout(task),
                )
            run.status = "success"
            run.result = result
            run.finished_at = datetime.now().isoformat()
            _manager.update_run(run)
            _manager.update_task_status(task.id or 0, "success", started_at)

            # 成功通知
            if task.notify_on_success:
                self._send_notification(task, run, "success")

            return run
        except Exception as e:
            logger.exception("[scheduled_task] 任务执行失败: %s", e)
            run.status = "failed"
            # S150 R1：TimeoutError 标明确（str(asyncio.TimeoutError) 为空）
            if isinstance(e, asyncio.TimeoutError):
                run.error = f"timeout ({_task_timeout(task)}s, S150 R1)"
            else:
                run.error = str(e)
            run.finished_at = datetime.now().isoformat()
            _manager.update_run(run)
            _manager.update_task_status(task.id or 0, "failed", started_at)

            # 失败通知
            if task.notify_on_failure:
                self._send_notification(task, run, "failed")

            return run

    def _send_notification(self, task: ScheduledTask, run: TaskRun, status: str) -> None:
        """发送任务执行通知。"""
        try:
            from notification.notification_service import get_notification_service
            service = get_notification_service()

            status_text = "成功" if status == "success" else "失败"
            title = f"定时任务{status_text}: {task.name}"
            content = f"任务: {task.name}\n状态: {status_text}\n时间: {run.started_at}"
            if run.error:
                content += f"\n错误: {run.error}"

            # 使用通知服务发送（如果可用）
            if hasattr(service, "send"):
                try:
                    service.send(content)
                except Exception as e:  # L1 修复：不再静默吞异常
                    logger.warning("定时任务通知发送失败: %s", e)
        except Exception as e:  # L1 修复：不再静默吞异常
            logger.warning("定时任务通知构建失败: %s", e)

    def _execute_daily_data_refresh(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """每日数据刷新：刷新持仓。

        R7（S031）：复盘预计算统一由 limitup_precompute 驱动
        （_execute_limitup_precompute 内对 back_days 各日调 reviewer.precompute_daily），
        此处只保留持仓刷新——单一事实源，不再重复调 daily_review。
        """
        import portfolio as pf

        results: Dict[str, Any] = {}
        try:
            pf.refresh_all()
            results["portfolio"] = "ok"
        except Exception as e:
            logger.warning("[daily_data_refresh] 持仓刷新失败: %s", e)
            results["portfolio"] = f"error: {e}"

        return results

    def _execute_limitup_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """盘后预计算：涨停板基因得分 + STI + 竞价选股 + 复盘报告。"""
        import limitup_screener as _ls
        import limitup_sti as _ls_sti
        import auction_screener as _asc
        import daily_review as _dr

        results: Dict[str, Any] = {}
        back_days = int(payload.get("back_days", 3))

        # 异步预计算逻辑在线程中运行
        async def _precompute_async() -> None:
            # 交易日守卫（P1·日期语义完整性第4通道）：本闭包按自然日回溯遍历，
            # 非交易日（周末/节假日）下调东财相关接口会因静默回退拿到最近交易日数据，
            # 错位入库。daily_review.generate_review 现对非交易日抛 ValueError，
            # 跳过非交易日还能避免异常日志。统一用 vr_paths.is_trading_day 判断。
            from vr_paths import is_trading_day as _is_trading_day  # noqa: PLC0415

            for back in range(back_days):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                    logger.info("[limitup_precompute] %s 非交易日，跳过涨停板基因得分预计算", d)
                    continue
                await _ls.get_screener_result(d)

            try:
                engine = _ls_sti.get_sti_engine()
                for back in range(back_days):
                    d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                    if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                        continue
                    await asyncio.to_thread(engine.precompute_daily, d)
            except Exception as e:
                logger.warning("[limitup_precompute] STI 预计算失败: %s", e)

            try:
                screener = _asc.get_screener()
                for back in range(back_days):
                    d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                    if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                        continue
                    await asyncio.to_thread(screener.precompute_daily, d)
            except Exception as e:
                logger.warning("[limitup_precompute] 竞价选股预计算失败: %s", e)

            try:
                reviewer = _dr.get_reviewer()
                for back in range(back_days):
                    d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                    if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                        continue
                    await asyncio.to_thread(reviewer.precompute_daily, d)
            except Exception as e:
                logger.warning("[limitup_precompute] 复盘报告预计算失败: %s", e)

        try:
            asyncio.run(asyncio.wait_for(_precompute_async(), timeout=600))
            results["status"] = "ok"
        except Exception as e:
            logger.warning("[limitup_precompute] 预计算失败: %s", e)
            results["status"] = f"error: {e}"

        return results

    def _execute_sti_post_market(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S063 T3：STI 盘后定时计算——交易日 15:30 触发。

        调 `market._emotion(T)` + `market._sentiment(T)` → `engine.compute()` →
        `save_result()` 持久化到 sti_timeline → 成为 T+1 的硬标准（SentimentContext
        读取 T-1 行的来源）。

        payload 可选 `date`（YYYY-MM-DD）用于补算历史日；缺省=今天。
        """
        import market as _market
        from limitup_sti.service import get_sti_engine
        from vr_paths import last_trading_date_str

        target = payload.get("date") or last_trading_date_str()
        results: Dict[str, Any] = {"date": target}

        try:
            emotion_data = _market._emotion(target)
            if not emotion_data:
                results["status"] = "no_emotion_data"
                logger.warning("[sti_post_market] %s 情绪数据未取得（非交易日或采集失败）", target)
                return results

            sentiment_data = _market._sentiment(target) or {}
            engine = get_sti_engine()
            sti_result = engine.compute(emotion_data, sentiment_data)

            results["status"] = "ok" if sti_result.source_ok else "source_fail"
            results["sti_score"] = sti_result.score
            results["sti_phase"] = sti_result.phase.value if sti_result.phase else None
            results["source_date"] = target
            logger.info(
                "[sti_post_market] %s STI 计算完成：score=%s phase=%s",
                target, sti_result.score,
                sti_result.phase.value if sti_result.phase else None,
            )
            # S065：STI 成功后落 weather_history 快照（失败不阻断主流程）
            try:
                from routers.sentiment_weather import compute_weather_snapshot
                from weather_history import save_weather_snapshot
                snapshot = compute_weather_snapshot(target)
                if snapshot.get("data_status") == "ok":
                    save_weather_snapshot(snapshot)
                    logger.info(
                        "[sti_post_market] %s weather_history 快照已落库：%s",
                        target, snapshot.get("weather_state"),
                    )
            except Exception as we:
                logger.warning("[sti_post_market] weather_history 落库失败（不阻断）: %s", we)
        except Exception as e:
            logger.exception("[sti_post_market] STI 计算失败: %s", e)
            results["status"] = f"error: {e}"

        return results

    def _execute_portfolio_refresh(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """刷新持仓数据。"""
        import portfolio as pf

        results: Dict[str, Any] = {}
        try:
            pf.refresh_all()
            results["portfolio"] = "ok"
        except Exception as e:
            logger.warning("[portfolio_refresh] 持仓刷新失败: %s", e)
            results["portfolio"] = f"error: {e}"

        return results

    def _execute_market_data_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """同步市场数据（M12：空壳桩，未实现具体同步逻辑）。"""
        results: Dict[str, Any] = {}
        results["market"] = "stub: market_data_sync 未实现具体同步逻辑"
        return results

    def _execute_cleanup_old_runs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """清理旧的运行记录。"""
        results: Dict[str, Any] = {}
        keep_days = int(payload.get("keep_days", 30))
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()

        conn = _get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM scheduled_task_runs WHERE started_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            results["deleted_runs"] = deleted
            results["keep_days"] = keep_days
        finally:
            conn.close()

        return results

    def _execute_daily_review_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """每日复盘通知：生成报告并推送。"""
        import daily_review as dr
        from notification.notification_service import get_notification_service, send_daily_report

        today = datetime.now().strftime("%Y-%m-%d")
        reviewer = dr.get_reviewer()
        report = reviewer.generate_review(today)

        results: Dict[str, Any] = {}
        try:
            service = get_notification_service()
            md = service.generate_daily_report([report.model_dump()])
            service.save_report_to_file(md)
            sent = service.send(md)
            results["sent"] = sent
            results["channels"] = len(service._available_channels) if hasattr(service, "_available_channels") else 0
        except Exception as e:
            logger.warning("[daily_review_notify] 通知发送失败: %s", e)
            results["error"] = str(e)

        return results

    def _execute_daily_backtest_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S041：每日回测快照——跑 backtest_lite + strategy_backtest，存入 backtest_daily_snapshots。

        lite 是 async，在 sync handler 里用 asyncio.run() 驱动；strategy 是 sync 直调。
        单引擎失败不阻断另一个——回测是增强，失败兜底记 error。

        S052 D1/D6：payload 增可选 as_of_date（YYYY-MM-DD）——point-in-time 回算。
        缺省=今天（行为不变）；给了则 snapshot_date=as_of、窗口终点=as_of、strategy 传 as_of。
        """
        from backtest_lite import run_backtest_async
        from strategies.strategy_backtest import run_strategy_backtest

        lookback = int(payload.get("lookback_days", 30))
        as_of = payload.get("as_of_date")  # S052 D1：可选 point-in-time 日期
        today_dt = datetime.now().date()
        if as_of:
            snapshot_date = as_of
            end = as_of
            start_dt = datetime.strptime(as_of, "%Y-%m-%d").date()
        else:
            snapshot_date = today_dt.strftime("%Y-%m-%d")
            end = snapshot_date
            start_dt = today_dt
        start = (start_dt - timedelta(days=lookback)).strftime("%Y-%m-%d")

        results: Dict[str, Any] = {"snapshot_date": snapshot_date, "lookback_days": lookback, "start": start, "as_of_date": as_of}

        # lite 引擎
        # L5 标注：asyncio.run() 在 execute() 同步路径经 asyncio.to_thread 包装在线程池中，
        # 无现有事件循环，安全。execute_async 异步路径不经过此同步方法。
        try:
            lite_result = asyncio.run(run_backtest_async(start, end))
            _save_snapshot(snapshot_date, "lite", lite_result)
            results["lite"] = {
                "hit_rate": lite_result.hit_rate,
                "avg_return": lite_result.avg_return,
                "total_signals": lite_result.total_signals,
            }
        except Exception as e:
            logger.warning("[daily_backtest_run] lite 回测失败: %s", e)
            results["lite"] = f"error: {e}"

        # strategy 引擎
        try:
            strat_results = run_strategy_backtest(lookback, as_of)
            _save_snapshot(snapshot_date, "strategy", strat_results)
            results["strategy"] = {
                "strategies": len(strat_results),
                "total_sample": sum(getattr(r, "sample_size", 0) for r in strat_results),
            }
        except Exception as e:
            logger.warning("[daily_backtest_run] strategy 回测失败: %s", e)
            results["strategy"] = f"error: {e}"

        return results


    # ============================================================================
    # S055：盘中封单时序采集
    # ============================================================================

    def _execute_seal_intraday_collect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S055：盘中封单时序采集（S150 T0.7 根治：subprocess 跑全逻辑）。

        全逻辑（prune + collect_once + rules + trajectory/derived）在子进程跑——
        asyncio 线程（run_in_executor/to_thread）不可中断，R1 wait_for 超时后底层线程
        继续跑：孤儿线程并发 em_get（rate limiter TOCTOU→跳限流→IP 封禁，HIGH1）+ 写库
        （INSERT OR REPLACE 覆盖 seal_derived/intraday_features 陈旧派生 / bomb_alert_history
        重复行 / 若线程持 _DB_LOCK 瞬间超时→锁泄漏死线程永久持有→后续 collect_once 永久
        阻塞 acquire()，HIGH3）。subprocess.run(timeout=110) 超时 SIGKILL 子进程，OS 回收
        DB 连接+lock，根治孤儿线程+死锁。逻辑在 risk.seal_intraday_collect_cli（线程→子进程，
        逻辑不变）。timeout=110 < R1 wait_for 120 避免竞态（subprocess 先 kill+线程返回）。
        """
        import json as _json
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = str(Path(__file__).resolve().parent)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "risk.seal_intraday_collect_cli"],
                input=_json.dumps(payload, ensure_ascii=False),
                capture_output=True, text=True, timeout=_SEAL_COLLECT_SUBPROCESS_TIMEOUT, cwd=backend_dir,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"collect subprocess timeout {_SEAL_COLLECT_SUBPROCESS_TIMEOUT}s (SIGKILL, no orphan thread)",
                    "timeout": True, "date": datetime.now().strftime("%Y-%m-%d")}
        try:
            result = _json.loads(proc.stdout) if proc.stdout.strip() else {}
        except _json.JSONDecodeError:
            result = {"error": f"subprocess stdout not JSON: {(proc.stdout or '')[-200:]}"}
        if proc.returncode != 0:
            result.setdefault(
                "error", f"subprocess exit {proc.returncode}: {(proc.stderr or '')[-200:]}")
        return result

    def _execute_candidate_funnel_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S004 R5：盘后漏斗预计算——预热 _FUNNEL_CACHE，盘后复盘页即时读缓存。

        取 date（默认最近交易日）→ run_funnel("all", date, live_config) →
        结果落 _FUNNEL_CACHE（TTL 由 config.CANDIDATE_FUNNEL_CACHE_TTL 控制，默认 3600s）。
        失败 catch 不抛，返 status=error（预计算是增强，不阻塞主流程）。

        S093 R10：success 后调 NotificationService.send() 发富内容卡片
        （F 日期 + final_candidates 数 + 双重确认数 + top5 标的），扩返候选统计。
        通知失败不阻断预计算（增强，catch 不抛）。
        """
        try:
            from candidate_funnel import funnel as funnel_mod
            from candidate_funnel.models import ThresholdConfig
            from vr_paths import last_trading_date_str
            target = payload.get("date") or last_trading_date_str()
            # 复用 candidates 路由的 live config（用户调参后一致）
            try:
                from routers.candidates import _store
                cfg = _store["config"]
                if not isinstance(cfg, ThresholdConfig):
                    cfg = ThresholdConfig(**cfg) if isinstance(cfg, dict) else ThresholdConfig()
            except Exception:
                cfg = ThresholdConfig()
            result = funnel_mod.run_funnel("all", target, cfg)
            # S087 R10：落库 funnel_cache（前端 tab 读缓存秒开，进程重启不丢）
            from candidate_funnel.funnel_cache import save_funnel_result
            save_funnel_result(target, "all", result)

            # S093 R10：final_candidates 诊断卡 + 双重确认 + 战法映射
            final_cards: list[dict] = []
            try:
                final_cards = [c.model_dump(mode="json") for c in result.final_candidates]
            except Exception as exc:  # noqa: BLE001
                logger.warning("[candidate_funnel_precompute] final_cards 构建失败: %s", exc)

            dual_count = _compute_dual_confirmation(target, final_cards)
            strategy_map = _compute_strategy_map(target)

            # S093 R10：发飞书富内容卡片（直接调 NotificationService.send()，
            # 不走 _send_notification——后者只产固定格式任务状态文本，不支持富内容）
            # final_candidates=0 时不发通知（数据未就绪时漏斗空，推"0 只"误导用户；
            # 根因：cron 若抢在 gene_scores 写入前跑则 R1 宽源输入 0，见 cron 17:15 修订）
            if final_cards:
                try:
                    from notification.notification_service import NotificationService
                    content = _build_premarket_notification_content(
                        target, final_cards, dual_count, strategy_map,
                    )
                    ns = NotificationService()
                    if ns.is_available():
                        ns.send(content, route_type="alert", severity="info")
                        logger.info("[candidate_funnel_precompute] 飞书通知已发送（%d 候选）", len(final_cards))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[candidate_funnel_precompute] 飞书通知发送失败: %s", exc)
            else:
                logger.warning(
                    "[candidate_funnel_precompute] final_candidates=0，跳过飞书通知"
                    "（数据未就绪或漏斗空；cron 17:15 应在 gene_scores 写入后）"
                )

            logger.info("[candidate_funnel_precompute] %s 漏斗预计算完成（缓存已预热+落库）", target)
            # S148：顺手触发 briefing _collect——precompute 写 funnel_cache 但 briefing 端点不读它，
            # 须 _collect 采集才让选股页显数据（fire-and-forget，主 loop 后台跑，不阻塞 executor）。
            try:
                from routers.workflow import trigger_collect  # noqa: PLC0415
                triggered = trigger_collect(target)
                logger.info(
                    "[candidate_funnel_precompute] briefing _collect %s（target=%s；实际采集由 dedup status=running 决定）",
                    "已调度到主 loop" if triggered else "跳过（主 loop 未设/已关）", target,
                )
            except Exception as exc:  # noqa: BLE001 — briefing 触发失败不阻断 precompute 主流程
                logger.warning("[candidate_funnel_precompute] briefing _collect 触发失败: %s", exc)
            return {
                "date": target,
                "status": "ok",
                "final_candidates_count": len(final_cards),
                "dual_confirmation_count": dual_count,
            }
        except Exception as e:
            logger.warning("[candidate_funnel_precompute] 预计算失败: %s", e)
            return {"status": f"error: {e}"}

    def _execute_daily_ai_summary(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S093 R12：AI 盘后总结 stub（cron 15:30，与 stage 推进点 15:30 对齐）。

        S094 完整实现：LLM 汇总当日信号 + 持仓表现 + 市场数据，生成
        "今日操作回顾 + 明日建议"自然语言总结。本 stub 调 generate_daily_summary
        返空串 + 落存储位（.vibe-research/daily_summaries/{date}.txt）。
        """
        from vr_paths import last_trading_date_str

        target = payload.get("date") or last_trading_date_str()
        summary = generate_daily_summary(target)
        return {
            "date": target,
            "status": "ok",
            "summary_length": len(summary),
            "note": "S094 TODO：AI 盘后总结 stub，返空串",
        }

    # ── S101 飞书多点通知：9:25 竞价 / 9:35 开盘 / T+1 复盘 ──────────────

    def _execute_premarket_auction_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S101：9:25 竞价确认后推送前瞻标的开盘竞价表现。

        读 F 日（上一交易日）funnel_cache final_candidates → tencent_quote 取竞价/开盘价
        → 算 gap_pct（open vs last_close）→ 推飞书。无缓存/无 quote/NotificationService 不可用
        → 不崩不推（增强，catch 不抛）。

        S136：开盘后实时核 kill_switch（market_note 承诺落地）——triggered 时通知前置
        「不开新仓」熔断警告。
        """
        try:
            from vr_paths import prev_trading_date_str
            from candidate_funnel.funnel_cache import load_funnel_result
            from notification.notification_service import NotificationService

            f_date = payload.get("date") or prev_trading_date_str()
            final_cards = _load_final_cards(f_date)
            if not final_cards:
                logger.info("[premarket_auction_notify] %s 无 final_candidates，跳过", f_date)
                return {"date": f_date, "status": "ok", "notified": False, "reason": "no_candidates"}

            codes = [c.get("code") for c in final_cards if c.get("code")]
            quotes = _fetch_quotes(codes)
            content = _build_auction_notify_content(f_date, final_cards, quotes)
            ks = _check_premarket_kill_switch()  # S136：开盘后实时核
            if ks["triggered"]:
                content = _prepend_kill_switch_warning(content, ks)
            notified = _send_notify(content)
            logger.info("[premarket_auction_notify] %s 候选%d notified=%s kill_switch=%s",
                        f_date, len(final_cards), notified, ks["triggered"])
            return {"date": f_date, "status": "ok", "candidates": len(final_cards),
                    "notified": notified, "kill_switch": ks}
        except Exception as e:
            logger.warning("[premarket_auction_notify] 失败: %s", e)
            return {"status": f"error: {e}"}

    def _execute_premarket_open_notify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S101：9:35 开盘 5min 后推送前瞻标的开盘表现（现价/涨跌幅/封板）。

        S136：开盘后实时核 kill_switch（market_note 承诺落地）——triggered 时通知前置
        「不开新仓」熔断警告。
        """
        try:
            from vr_paths import prev_trading_date_str

            f_date = payload.get("date") or prev_trading_date_str()
            final_cards = _load_final_cards(f_date)
            if not final_cards:
                logger.info("[premarket_open_notify] %s 无 final_candidates，跳过", f_date)
                return {"date": f_date, "status": "ok", "notified": False, "reason": "no_candidates"}

            codes = [c.get("code") for c in final_cards if c.get("code")]
            quotes = _fetch_quotes(codes)
            content = _build_open_notify_content(f_date, final_cards, quotes)
            ks = _check_premarket_kill_switch()  # S136：开盘后实时核
            if ks["triggered"]:
                content = _prepend_kill_switch_warning(content, ks)
            notified = _send_notify(content)
            logger.info("[premarket_open_notify] %s 候选%d notified=%s kill_switch=%s",
                        f_date, len(final_cards), notified, ks["triggered"])
            return {"date": f_date, "status": "ok", "candidates": len(final_cards),
                    "notified": notified, "kill_switch": ks}
        except Exception as e:
            logger.warning("[premarket_open_notify] 失败: %s", e)
            return {"status": f"error: {e}"}

    def _execute_premarket_t1_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S101：T+1 复盘——前瞻标的（F 日 final_candidates）在 T 日（F 下一交易日）收益。

        baostock_kline_cache 取 T 日 close vs F 日 close（close2close 口径，简化；open2close
        见 first_board_settlement 但需 T 日 open，baostock 当日 bar 16:35 可能未更新，故用 close2close）。
        §44 口径：n<30 标样本不足 / 不宣称 alpha / lift<2x 标无 validated edge。
        """
        try:
            from vr_paths import prev_trading_date_str, next_trading_date
            from datetime import date as _date

            f_date = payload.get("date") or prev_trading_date_str()
            final_cards = _load_final_cards(f_date)
            if not final_cards:
                logger.info("[premarket_t1_review] %s 无 final_candidates，跳过", f_date)
                return {"date": f_date, "status": "ok", "notified": False, "reason": "no_candidates"}

            t_date = next_trading_date(_date.fromisoformat(f_date)).isoformat()
            returns = _compute_t1_returns(final_cards, f_date, t_date)
            content = _build_t1_review_content(f_date, t_date, returns)
            notified = _send_notify(content)
            n = len(returns)
            logger.info("[premarket_t1_review] %s→%s n=%d notified=%s", f_date, t_date, n, notified)
            return {
                "f_date": f_date, "t_date": t_date, "status": "ok",
                "candidates": n, "notified": notified,
            }
        except Exception as e:
            logger.warning("[premarket_t1_review] 失败: %s", e)
            return {"status": f"error: {e}"}

    def _execute_first_board_filter(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S075 盘后首板流筛选——首板过滤+三层剔除+9维度评分+落盘。

        取 date（默认最近交易日）→ run_first_board_filter → 候选池+评分存快照。
        失败 catch 不抛，返 status=error（筛选是增强，不阻塞主流程）。
        """
        try:
            from strategies.first_board_filter import run_first_board_filter
            from vr_paths import last_trading_date_str
            target = payload.get("date") or last_trading_date_str()
            result = run_first_board_filter(target)
            logger.info("[first_board_filter] %s 首板流筛选完成：涨停%s/首板%s/候选%s",
                        target, result["zt_pool_count"], result["first_board_count"],
                        len(result["candidates"]))
            return {
                "date": target,
                "status": "ok",
                "zt_pool_count": result["zt_pool_count"],
                "first_board_count": result["first_board_count"],
                "candidate_count": len(result["candidates"]),
            }
        except Exception as e:
            logger.warning("[first_board_filter] 筛选失败: %s", e)
            return {"status": f"error: {e}"}


    def _execute_s066_validation_checkpoint(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """§44 60 天复验检查点（提醒任务，spec §13 ①/§44）。

        数 eastmoney_live 信号日；达 threshold（默认 60）→ 写 checkpoint 文件 + WARNING 日志
        + 返 DUE+操作指引（notify_on_success 兜底推送，若通道已配）；未到期 → 返进度（静默）。
        到点由人/会话跑 `tools/forward_test_backfill.py --weather` 查 lift——本任务只提醒不自动验证。
        """
        from config import GENE_SCORES_DB_PATH
        from vr_paths import resolve_data_dir
        from db_health import get_healthy_conn

        threshold = int(payload.get("threshold", 60))
        conn = get_healthy_conn(GENE_SCORES_DB_PATH)
        try:
            days = conn.execute(
                "SELECT COUNT(DISTINCT date) FROM gene_scores WHERE data_source='eastmoney_live'"
            ).fetchone()[0]
        finally:
            conn.close()

        if days < threshold:
            return {"status": "not_due", "eastmoney_live_days": days, "target": threshold,
                    "note": f"积累中 {days}/{threshold} 日，到点自动提醒 §44 复验"}

        # 到期：写 checkpoint + WARNING + 返操作指引
        ckpt = {"status": "due", "eastmoney_live_days": days, "target": threshold,
                "action": "cd backend && .venv/bin/python tools/forward_test_backfill.py --weather "
                          "→ 查 get_forward_test_summary 的 lift：破 2x + within-day r 显著 → alpha 成立；"
                          "否则确认无 edge（spec §13 ①/§44）",
                "checked_at": datetime.now().isoformat()}
        try:
            ckpt_path = Path(resolve_data_dir()) / "s066_60day_due.json"
            ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        logger.warning(
            "[s066_checkpoint] §44 60 天复验 DUE：eastmoney_live=%d 日 → 跑 backfill --weather 查 lift", days)
        return ckpt


    def _execute_evaluation_backtest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S151 R3：评价层回溯检查点（提醒任务，复用 s066_validation_checkpoint 范式）。

        数 forward_test_records 信号日 + buyable picks；两档门槛：
        - 30 日 + n≥100 → 首次回溯 DUE（跑 per-dimension day_paired_lift 非池化，
          写 VR_DATA_DIR/evaluation_lifts.db，DIMENSION_LIFT_REGISTRY 升级 DB-backed 动态读）
        - 60 日 → 复验 DUE（重跑 lift + 判升级/降级：lift≥2+CI不重叠→validated×1.0；
          lift<1 robust→劣于随机×0.1）
        到点只提醒不自动验证（同 s066）——由人/会话跑 harness。未到期返 not_due + 进度（静默）。
        """
        from config import GENE_SCORES_DB_PATH
        from vr_paths import resolve_data_dir
        from db_health import get_healthy_conn

        first_threshold = int(payload.get("first_threshold", 30))
        reverify_threshold = int(payload.get("reverify_threshold", 60))
        min_n = int(payload.get("min_n", 100))

        conn = get_healthy_conn(GENE_SCORES_DB_PATH)
        try:
            days = conn.execute(
                "SELECT COUNT(DISTINCT signal_date) FROM forward_test_records"
            ).fetchone()[0]
            # S144 buyable 口径（剔 is_unbuyable=1 一字板，与 verdict 同源）
            n = conn.execute(
                "SELECT COUNT(*) FROM forward_test_records WHERE is_unbuyable = 0"
            ).fetchone()[0]
        finally:
            conn.close()

        # 未到期：返进度（静默）
        if days < first_threshold:
            return {"status": "not_due", "signal_days": days, "picks_n": n,
                    "first_threshold": first_threshold, "reverify_threshold": reverify_threshold,
                    "min_n": min_n,
                    "note": f"日数积累中 {days}/{first_threshold}（n={n}），到点提醒 §44 首次回溯"}
        if n < min_n:
            return {"status": "not_due", "signal_days": days, "picks_n": n,
                    "first_threshold": first_threshold, "reverify_threshold": reverify_threshold,
                    "min_n": min_n,
                    "note": f"日数 {days}≥{first_threshold} 达首档但 n={n}/{min_n} 不足，picks 积累中"}

        # 到期：判阶段 + 写 checkpoint + WARNING + 返操作指引
        phase = "first_retrospective" if days < reverify_threshold else "reverify"
        if phase == "first_retrospective":
            action = (
                "cd backend && .venv/bin/python tools/first_board_layer_lift.py --baostock "
                "→ 跑 per-dimension day_paired_lift（非池化防 4.686x→1.723x 假象）写 "
                "evaluation_lifts.db → DIMENSION_LIFT_REGISTRY 升级 DB-backed 动态读（spec S151 R3）"
            )
        else:
            action = (
                "cd backend && .venv/bin/python tools/first_board_layer_lift.py --baostock-history "
                "→ 重跑 lift + 判升级/降级（lift≥2+CI不重叠→validated×1.0；lift<1 robust→劣于随机×0.1；"
                "1≤lift<2→未validated×0.5）——更新 DIMENSION_LIFT_REGISTRY updated_*"
            )
        ckpt = {"status": "due", "phase": phase, "signal_days": days, "picks_n": n,
                "first_threshold": first_threshold, "reverify_threshold": reverify_threshold,
                "min_n": min_n, "action": action,
                "checked_at": datetime.now().isoformat()}
        try:
            ckpt_path = Path(resolve_data_dir()) / "s151_evaluation_backtest_due.json"
            ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        logger.warning(
            "[evaluation_backtest] S151 回溯 DUE（%s）：signal_days=%d picks_n=%d → %s",
            phase, days, n, action)
        return ckpt


    def _execute_forward_test_daily(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S069 R1：每日 post-market 记当日 forward_test picks + universe codes（收益 NULL，R2 次日回填）。

        晚 limitup_precompute（gene_scores 已写 15:30）。weather 用 build_context（完整架构非退化）。
        信号日 = last_trading_date_str（当日交易日；周末跑记最近交易日，幂等）。
        """
        from vr_paths import last_trading_date_str
        from sentiment_context import build_context
        from strategies.forward_test import run_daily_forward_test

        signal_date = last_trading_date_str()
        try:
            weather = build_context(signal_date).weather_state
        except Exception:
            weather = None
        r = run_daily_forward_test(signal_date, weather_state=weather)
        logger.info("[forward_test_daily] %s picks=%s universe=%s weather=%s",
                   signal_date, r.get("recommendations", 0), r.get("universe_codes", 0), weather)
        return {"signal_date": signal_date, "weather": weather,
                "picks": r.get("recommendations", 0), "universe_codes": r.get("universe_codes", 0)}


    def _execute_forward_test_t1_settle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S069 R2：回填最近未结算 signal_date 的 T+1 收益（baostock kline→return_open2close）。

        每日 post-market 跑。处理 newest 3 个 signal_date<今日 且 return_open2close IS NULL 的
        （其 next_bar 今日收盘后可得）→ compute_returns_for_codes → record_actual_returns（picks）+
        record_universe_returns（universe）。缺 next_bar 的 code 留 NULL（下次重试）。
        **stuck-date 处理**：0-settle 的日期（如调休补班 baostock 无 bar）标 no_bar（JSON，7 日后重试），
        避免每日卡死循环在同一 stuck date。
        """
        import json as _json
        import sqlite3
        from config import GENE_SCORES_DB_PATH
        from datetime import datetime, timedelta
        from db_health import get_healthy_conn
        from vr_paths import last_trading_date_str, resolve_data_dir
        from strategies.forward_test import record_actual_returns, record_universe_returns
        from strategies.kline_returns import compute_returns_for_codes

        today = last_trading_date_str()
        # stuck-mark：7 日内 0-settle 的日期不重试（避免卡死；7 日后重试，防 baostock 暂态）
        stuck_path = Path(resolve_data_dir()) / "t1_stuck_dates.json"
        stuck: dict[str, str] = {}
        try:
            stuck = _json.loads(stuck_path.read_text(encoding="utf-8"))
        except Exception:
            stuck = {}
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        stuck = {d: t for d, t in stuck.items() if t >= cutoff}  # 清 7 日前的 stuck（重试）

        conn = get_healthy_conn(GENE_SCORES_DB_PATH)
        try:
            # S151 fix：stuck 在 SQL 内排除（LIMIT 前），避免 newest 3 全 stuck 时够不着
            # 非 stuck 旧日期（原 post-filter 在 LIMIT 后，stuck 占满 LIMIT→空）。
            # bulk=True 提 LIMIT 处理全 non-stuck（默认 3=每日 cron 轻量）。
            bulk = bool(payload.get("bulk"))
            limit = 50 if bulk else 3
            stuck_dates = list(stuck.keys())
            if stuck_dates:
                stuck_ph = ",".join("?" * len(stuck_dates))
                rows = conn.execute(
                    "SELECT DISTINCT signal_date FROM forward_test_records "
                    "WHERE return_open2close IS NULL AND signal_date < ? "
                    f"AND signal_date NOT IN ({stuck_ph}) "
                    "ORDER BY signal_date DESC LIMIT ?",
                    [today] + stuck_dates + [limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT signal_date FROM forward_test_records "
                    "WHERE return_open2close IS NULL AND signal_date < ? "
                    "ORDER BY signal_date DESC LIMIT ?",
                    [today, limit],
                ).fetchall()
            dates = [r[0] for r in rows]  # stuck 已在 SQL 排除
        finally:
            conn.close()
        if not dates:
            return {"status": "nothing_to_settle", "today": today, "stuck": len(stuck)}

        summary = []
        for signal_date in dates:
            conn = get_healthy_conn(GENE_SCORES_DB_PATH)
            try:
                # S145：picks 取 code + strategy_code（建 strategy_params_map 供 path 模拟用其战法 params）
                pick_rows = conn.execute(
                    "SELECT code, strategy_code FROM forward_test_records "
                    "WHERE signal_date=? AND return_open2close IS NULL", (signal_date,)).fetchall()
                pick_codes = list(dict.fromkeys(r[0] for r in pick_rows))
                uni_codes = [r[0] for r in conn.execute(
                    "SELECT DISTINCT code FROM universe_returns "
                    "WHERE signal_date=? AND return_open2close IS NULL", (signal_date,)).fetchall()]
            finally:
                conn.close()
            all_codes = list(dict.fromkeys(pick_codes + uni_codes))
            if not all_codes:
                continue
            # S145 R2：每 pick code 取首个战法 params（多战法同 code 时按 code UPDATE 全行同 path）
            from strategies.kline_returns import strategy_params_for  # noqa: PLC0415
            strategy_params_map: dict[str, dict] = {}
            for code, sc in pick_rows:
                if code not in strategy_params_map and sc:
                    strategy_params_map[code] = strategy_params_for(sc)
            returns_map = compute_returns_for_codes(signal_date, all_codes,
                                                    strategy_params_map=strategy_params_map or None)
            if not returns_map:
                summary.append({"signal_date": signal_date, "status": "baostock_unavailable"})
                break  # baostock 不可用，后续日也跑不了
            picks_returns = {c: returns_map[c] for c in pick_codes
                             if c in returns_map and returns_map[c]["return_open2close"] is not None}
            uni_returns = {c: returns_map[c] for c in uni_codes
                           if c in returns_map and returns_map[c]["return_open2close"] is not None}
            n_picks = record_actual_returns(signal_date, picks_returns)
            n_uni = record_universe_returns(signal_date, uni_returns)
            settled = n_picks + n_uni
            # 0-settle → 标 stuck（如调休补班 baostock 无 bar），7 日内不重试
            if settled == 0:
                stuck[signal_date] = datetime.now().isoformat()
            logger.info("[forward_test_t1_settle] %s settled picks=%s/%s universe=%s/%s%s",
                       signal_date, n_picks, len(pick_codes), n_uni, len(uni_codes),
                       " [stuck-mark]" if settled == 0 else "")
            summary.append({"signal_date": signal_date, "settled_picks": n_picks,
                            "settled_universe": n_uni, "total": settled})

        try:
            stuck_path.write_text(_json.dumps(stuck, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"today": today, "dates_processed": summary, "stuck": len(stuck)}


    def _execute_first_board_t1_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S075 T+1 溢价评分 + 复盘报告 + 飞书通知（盘后对 T-1 候选做收益评价）。

        流程：
        1. 取 T-1（最近有快照的交易日）候选
        2. 跑 run_t1_premium_review：baostock T 日 K 线算标的收益 + lift 四态判定
        3. build_review_report 构造 Markdown 复盘报告
        4. 飞书推送（NotificationService，route_type=alert/severity=info）

        无快照 / 无 T+1 数据 / 通道未配 → 不崩，返对应状态。
        失败 catch 不抛，返 status=error（评价是增强，不阻塞主流程）。
        """
        try:
            from strategies.first_board_settlement import (
                run_t1_premium_review,
                build_review_report,
            )
            from strategies.first_board_filter import list_score_dates
            from notification.notification_service import NotificationService

            # 取 T-1：优先用 payload.date，否则取最近的快照日
            signal_date = payload.get("date") if payload else None
            if not signal_date:
                dates = list_score_dates()
                if not dates:
                    return {"status": "error", "msg": "无历史快照"}
                signal_date = dates[0]  # 最近的快照日

            # 跑 T+1 评价
            review = run_t1_premium_review(signal_date)
            report = build_review_report(review)

            # 飞书推送
            ns = NotificationService()
            notified = False
            if ns.is_available():
                notified = ns.send(report, route_type="alert", severity="info")

            stats = review.get("stats", {}) if not review.get("error") else {}
            logger.info(
                "[first_board_t1_review] %s 候选%d 只 mean=%s%% notified=%s verdict=%s",
                signal_date,
                stats.get("n", 0),
                stats.get("mean_return_pct", 0),
                notified,
                review.get("verdict", review.get("error", "")),
            )
            return {
                "signal_date": signal_date,
                "status": "ok",
                "candidates": stats.get("n", 0),
                "mean_return": stats.get("mean_return_pct", 0),
                "verdict": review.get("verdict", ""),
                "error": review.get("error"),
                "notified": notified,
            }
        except Exception as e:
            logger.warning("[first_board_t1_review] 失败: %s", e)
            return {"status": f"error: {e}"}


    # ===========================================================================
    # S076：盘中多源行情探查 executor（临时研究任务）
    # ===========================================================================

    def _execute_first_board_quote_probe(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S076 盘中多源行情探查——9:20-9:36 每分钟探 tencent/mootdx/东财 push2。

        临时研究任务：产出 .scratch/s076-quote-probe/matrix_{date}.json，收 3-5 个交易日稳定
        结论后 disable。东财 push2 ≥10min 状态文件门控（R6 限流，per-minute cron 跨进程用文件持久化）。
        需 app 进程在 9:20-9:36 运行（无 catch-up，错过即缺）。失败 catch 不抛，返 error。
        """
        try:
            from tools.first_board_quote_source_probe import (
                probe_once, _append_row, OUT_DIR, EM_PUSH2_MIN_INTERVAL_S, DEFAULT_CODES,
            )
            import time as _time
            import json as _json

            codes = [c for c in (payload.get("codes") or DEFAULT_CODES) if c]

            # 东财 push2 ≥10min 状态文件门控（per-minute cron 跨进程，用文件持久化上次时间）
            state_path = OUT_DIR / "push2_state.json"
            last_push2 = 0.0
            try:
                if state_path.exists():
                    last_push2 = float(
                        _json.loads(state_path.read_text(encoding="utf-8")).get("last_push2_ts", 0.0)
                    )
            except Exception:
                last_push2 = 0.0

            srcs = ["tencent", "mootdx"]
            if _time.time() - last_push2 >= EM_PUSH2_MIN_INTERVAL_S:
                srcs.append("em_push2")

            row = probe_once(codes, sources=srcs)
            path = _append_row(row)

            if "em_push2" in srcs:
                try:
                    OUT_DIR.mkdir(parents=True, exist_ok=True)
                    state_path.write_text(
                        _json.dumps({"last_push2_ts": _time.time()}), encoding="utf-8"
                    )
                except Exception as e:
                    logger.warning("[first_board_quote_probe] push2 状态写失败: %s", e)

            return {
                "time": row.get("time"),
                "sources": srcs,
                "codes": codes,
                "matrix_path": str(path),
                "tencent_ok": row.get("tencent", {}).get("ok"),
                "mootdx_ok": row.get("mootdx", {}).get("ok"),
                "em_push2_ok": row.get("em_push2", {}).get("ok") if "em_push2" in row else None,
            }
        except Exception as e:
            logger.warning("[first_board_quote_probe] 探查失败: %s", e)
            return {"status": f"error: {e}"}


    # ===========================================================================
    # S078：涨停历史 snapshot executor（数据地基）
    # ===========================================================================

    def _execute_zt_history_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S078 涨停历史 snapshot——盘后 snapshot 当日涨停池 → zt_history.db（不 prune 累积）。

        数据地基：涨停池历史 >1 月无源（em/ths/akshare 均 ~1 月），每日累积供长窗 §44 复验。
        失败 catch 不抛，返 error（采集是增强，不阻塞主流程）。

        **每日唯一 + final 标记（2026-08-23 落地）**：
        is_final 按采集时点（北京时间）判定——>= 17:15 → True（东财池已稳定终盘），
        < 17:15 → False（中间快照，可被后续 final 覆盖）。final 一旦落定不可被非 final 覆盖。
        """
        try:
            from data.zt_history_store import snapshot_zt_pool
            from vr_paths import last_trading_date_str
            target = payload.get("date") or last_trading_date_str()
            # 采集时点判定：北京时间 17:15 后视为终盘稳定版（东财涨停池盘后持续收缩，
            # 17:15 后已稳定）。dateutil 不可用则回退 zoneinfo（3.9+ stdlib）。
            import datetime as _dt
            try:
                from zoneinfo import ZoneInfo
                now_bj = _dt.datetime.now(ZoneInfo("Asia/Shanghai"))
            except Exception:  # noqa: BLE001
                now_bj = _dt.datetime.now()  # fallback：无 tz 信息，按本地（开发机通常 CST）
            is_final = now_bj.hour > 17 or (now_bj.hour == 17 and now_bj.minute >= 15)
            written = snapshot_zt_pool(target, is_final=is_final)
            logger.info("[zt_history_snapshot] %s 涨停池 snapshot 写入 %s 行 (is_final=%s)",
                        target, written, is_final)
            return {"date": target, "written": written, "is_final": is_final, "status": "ok"}
        except Exception as e:
            logger.warning("[zt_history_snapshot] 采集失败: %s", e)
            return {"status": f"error: {e}"}

    # ===========================================================================
    # S167：盘中微结构数据累积（"等 live" 路径）——hithink 排名 + tencent 量比 + baostock 5min
    # 诚实框架：accumulation for future §44v2 testing, prior LOW (S152/S156 refuted
    # 封板时间/秒板), no edge claim yet — 累积 30-60 天后复测。
    # ===========================================================================

    def _execute_intraday_microstructure_snapshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S167 盘中微结构周期快照——每 10min 快照 hithink 排名 + tencent 量比 → 累积 DB。

        cron `*/10 9-15 * * 0-4` 触发，executor 内 ``vr_paths.is_intraday_time`` 门控
        （09:25-11:30 / 13:01-15:05 外 no-op，防封 + 省请求）。涨停池 codes 走 hithink
        ``limit_up_pool``（非 em_get 防封）；hithink 端点走 circuit_breaker，失败记
        data_status=degraded 不抛（S120：skyrocket/hot_stock/anomaly_list 失败 raise
        RuntimeError，此处 catch）。tencent urllib 免费不限流。
        """
        from vr_paths import is_intraday_time
        if not is_intraday_time():
            return {"status": "skipped", "reason": "非盘中交易时段"}

        from datetime import datetime as _dt
        from data.sources import hithink_src
        from data.sources.tencent import fetch_raw
        from data.intraday_accumulation_store import (
            save_ranking_snapshots, save_quote_snapshots,
        )
        from vr_paths import last_trading_date_str

        date = last_trading_date_str()
        ts = _dt.now().strftime("%Y-%m-%dT%H:%M")
        degraded: list[str] = []

        # 1. hithink 三榜（飙升/热股/异动）——实时无历史，不快照即丢失
        ranking_items: dict[str, list[dict]] = {}
        for source, fn in (
            ("skyrocket", hithink_src.skyrocket),
            ("hot_stock", hithink_src.hot_stock),
            ("anomaly", hithink_src.anomaly_list),
        ):
            try:
                ranking_items[source] = fn()
            except RuntimeError as e:
                degraded.append(f"{source}: {str(e)[:60]}")
                ranking_items[source] = []
            except Exception as e:  # noqa: BLE001
                degraded.append(f"{source}: {type(e).__name__}")
                ranking_items[source] = []

        for source, items in ranking_items.items():
            save_ranking_snapshots(date, ts, source, items)

        # 2. tencent 量比——涨停池 codes ∪ 排名 codes，一次批量
        zt_codes: list[str] = []
        try:
            zt_codes = [r["code"] for r in hithink_src.limit_up_pool(date) if r.get("code")]
        except Exception:  # noqa: BLE001 — hithink 涨停池失败不影响排名快照
            pass
        rank_codes = {it["code"] for items in ranking_items.values() for it in items if it.get("code")}
        codes = list({*zt_codes, *rank_codes})
        quotes = fetch_raw(codes) if codes else {}
        save_quote_snapshots(date, ts, quotes)

        ok = any(ranking_items.values()) or bool(quotes)
        return {
            "date": date, "ts": ts,
            "rankings": {s: len(v) for s, v in ranking_items.items()},
            "quotes": len(quotes), "zt_codes": len(zt_codes),
            "data_status": "degraded" if degraded else ("ok" if ok else "empty"),
            "degraded_sources": degraded,
        }

    def _execute_baostock_5min_freeze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S167 次日冻结——09:00 冻结 prev_trading_date 涨停股 5min bars（bars 稳定）。

        baostock 当日 5min bar T+1 lag（当日未稳定），故次日 09:00 冻结前一交易日
        涨停股 bars。涨停 codes 走 hithink ``limit_up_pool(prev_date)``。baostock 无 IP
        限制，单次 login。is_trading_day(today) 门控（节假日跳，prev 由下个交易日补）。
        幂等：INSERT OR REPLACE，重跑覆盖不翻倍。空 bars 仍写（bar_count=0 诚实记录）。
        """
        from vr_paths import is_trading_day, prev_trading_date_str
        if not is_trading_day():
            return {"status": "skipped", "reason": "非交易日（节假日跳，prev 由下交易日补）"}

        from data.sources import hithink_src, baostock_src
        from data.intraday_accumulation_store import freeze_baostock_5min

        prev_date = prev_trading_date_str()
        try:
            pool = hithink_src.limit_up_pool(prev_date)
        except Exception as e:  # noqa: BLE001
            return {"status": f"error: hithink 涨停池 {e}"}

        if not pool:
            return {"date": prev_date, "frozen": 0, "reason": "hithink 涨停池空（无涨停/源断）"}

        # end = prev_date（baostock 区间闭）；单日 bars
        frozen = 0
        empty = 0
        for item in pool:
            code = item.get("code")
            if not code:
                continue
            bars = baostock_src.fetch_5min_bars(code, prev_date, prev_date)
            freeze_baostock_5min(prev_date, code, item.get("name"), bars)
            frozen += 1
            if not bars:
                empty += 1
        return {
            "date": prev_date, "frozen": frozen, "empty_bars": empty,
            "pool_size": len(pool), "status": "ok",
        }

    def _execute_st_play_radar(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S148 R3：盘后 ST-play radar——扫 ST 股公告 → 摘帽/重组/扭亏 白名单 → st_play_radar.json。

        供 classify_tradability 做 ST carve-out（re-include + st_play 标）。失败 catch 不抛，
        返 error（radar 是增强；失败则 loader 返空→ST flat 排除，安全降级，不阻断主流程）。
        """
        try:
            from candidate_funnel.sources.st_play_radar import run_st_play_radar  # noqa: PLC0415
            radar = run_st_play_radar()
            logger.info("[st_play_radar] 白名单写入 %s 只（摘帽/重组/扭亏）", len(radar))
            return {"count": len(radar), "status": "ok"}
        except Exception as e:
            logger.warning("[st_play_radar] 采集失败: %s", e)
            return {"status": f"error: {e}"}


    # ===========================================================================
    # S084 C1/C2：盘后 derived 异步预采集 executor（17:00 工作日，龙虎榜 16:30 更新后）
    # ===========================================================================

    def _execute_derived_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S084 C2：17:00 盘后异步预采集——对昨日涨停股全量算 derived 落 seal_derived_features 表。

        取 yesterday（默认 last_trading_date(today-1)，与 funnel 的 yesterday_date 同口径）→
        zt_pool_source.fetch_zt_pool_map(yesterday) 取昨日涨停 codes → 对每只
        get_snapshots_by_code(code, yesterday) + compute_derived_features →
        persist_derived_features 写 seal_derived_features(date=yesterday)。选股池
        derived_source 后续读 seal_derived_features（不 per-code 实时算）。

        缺快照 / data_status='missing' → 跳过（不臆造）。单只失败不阻塞其余（catch 跳过）。
        整体失败 catch 不抛，返 status=error（预采集是增强，不阻塞主流程）。
        S084 follow-up：原 derived_results 表合并入 seal_derived_features（字段子集），
        复用 persist_derived_features 持久化（DRY，与盘中 collect 同写路径）。
        """
        from datetime import date as _date, timedelta as _td
        from vr_paths import last_trading_date as _last_td

        try:
            from candidate_funnel.sources import zt_pool_source
            from risk.seal_intraday_collector import (
                run_migrations, get_snapshots_by_code, _get_conn, _DB_LOCK,
            )
            from strategies.intraday_features import (
                compute_derived_features, persist_derived_features,
            )
        except Exception as e:
            logger.warning("[derived_precompute] 依赖导入失败: %s", e)
            return {"status": f"error: {e}"}

        # yesterday：与 funnel._run_funnel_impl 同口径（last_trading_date(today-1)），
        # payload.get("date") 允许指定回填昨日日期。
        yesterday = payload.get("date") or _last_td(_date.today() - _td(days=1)).isoformat()

        # 幂等建表（fresh env 自愈；已应用则 no-op），避免 seal_derived_features 缺表致写失败
        try:
            run_migrations()
        except Exception as e:
            logger.warning("[derived_precompute] 迁移失败（继续，首行写可能失败）: %s", e)

        try:
            zt_map = zt_pool_source.fetch_zt_pool_map(yesterday)
        except Exception as e:
            logger.warning("[derived_precompute] %s 涨停池取数失败: %s", yesterday, e)
            return {"date": yesterday, "status": f"error: {e}", "codes": 0, "written": 0}

        codes = list(zt_map.keys())
        if not codes:
            logger.info("[derived_precompute] %s 昨日涨停池为空（非交易日或采集失败）", yesterday)
            return {"date": yesterday, "status": "ok", "codes": 0, "written": 0, "skipped": 0}

        written = 0
        skipped = 0
        conn = _get_conn()
        try:
            with _DB_LOCK:
                for code in codes:
                    try:
                        snaps = get_snapshots_by_code(code, yesterday)
                        if not snaps:
                            skipped += 1
                            continue  # 缺快照跳过，不臆造
                        derived = compute_derived_features(snaps)
                        if derived.get("data_status") == "missing":
                            skipped += 1
                            continue
                        # 复用 persist_derived_features 写 seal_derived_features
                        # （INSERT OR REPLACE 幂等，同 (date,code) 重跑覆盖；S084 follow-up：
                        #   合并自 derived_results，DRY 复用战法层持久化函数，与盘中 collect 同路径）
                        name = (zt_map.get(code) or {}).get("n")
                        persist_derived_features(yesterday, code, name, derived, conn)
                        written += 1
                    except Exception as exc:
                        logger.warning(
                            "[derived_precompute] %s %s 派生落库失败（跳过）: %s",
                            yesterday, code, exc,
                        )
                        skipped += 1
                conn.commit()
        finally:
            conn.close()

        logger.info(
            "[derived_precompute] %s derived 预采集完成：涨停%s/写入%s/跳过%s",
            yesterday, len(codes), written, skipped,
        )
        return {"date": yesterday, "status": "ok", "codes": len(codes),
                "written": written, "skipped": skipped}

    def _execute_monthly_vacuum(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S089 D2：月度 VACUUM + wal_checkpoint(TRUNCATE)——热库（当年）月初触发。

        遍历 ``.vibe-research/`` 下的 ``seal_intraday_YYYY.db``，对当年库执行
        ``VACUUM``（回收碎片）+ ``PRAGMA wal_checkpoint(TRUNCATE)``（截断 -wal 文件，
        防止长期累积膨胀）。历史年冷库默认不 VACUUM（归档时单独跑一次，spec §R6.2）。

        payload 可选字段：
        - ``year``: 指定年（默认当年），debug/补跑用
        - ``include_cold``: True 时连历史年冷库一起 VACUUM（默认 False）

        返回 ``{"vacuumed": [db...], "checkpointed": [db...]}``。单库失败不阻塞其余
        （catch 记 error，标 status）。
        """
        import os
        import sqlite3
        from datetime import date as _date
        from config import SEAL_INTRADAY_DIR
        from db_health import get_healthy_conn

        target_year = str(payload.get("year", _date.today().year))
        include_cold = bool(payload.get("include_cold", False))

        if not os.path.isdir(SEAL_INTRADAY_DIR):
            logger.info("[monthly_vacuum] SEAL_INTRADAY_DIR=%s 不存在，跳过", SEAL_INTRADAY_DIR)
            return {"vacuumed": [], "checkpointed": [], "status": "no_dir"}

        vacuumed: list[str] = []
        checkpointed: list[str] = []
        errors: list[str] = []
        for fname in sorted(os.listdir(SEAL_INTRADAY_DIR)):
            # seal_intraday_YYYY.db（排除 .bak / -wal / -shm）
            if not fname.startswith("seal_intraday_") or not fname.endswith(".db"):
                continue
            if fname.endswith(".bak"):
                continue
            year = fname[len("seal_intraday_"):-len(".db")]
            if len(year) != 4 or not year.isdigit():
                continue
            is_hot = year == target_year
            if not is_hot and not include_cold:
                continue  # 冷库默认跳过

            db_path = os.path.join(SEAL_INTRADAY_DIR, fname)
            try:
                # VACUUM 需独占连接（WAL 模式下 VACUUM 仍要求无并发写）；用裸 connect
                # 避免 get_healthy_conn 的 row_factory 干扰 VACUUM（VACUUM 不返行）。
                # wal_checkpoint 在 get_healthy_conn 已开 WAL 的连接上执行。
                vconn = sqlite3.connect(db_path)
                try:
                    vconn.execute("PRAGMA journal_mode=WAL")
                    vconn.execute("PRAGMA busy_timeout=5000")
                    vconn.execute("VACUUM")
                    vacuumed.append(fname)
                finally:
                    vconn.close()

                cconn = get_healthy_conn(db_path)
                try:
                    # TRUNCATE 模式：checkpoint 后将 -wal 截断为 0（防膨胀）
                    row = cconn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    # row = (busy, log, checkpointed_frames)；busy=1 表示有并发写未完成
                    if row and row[0] == 0:
                        checkpointed.append(fname)
                    elif row:
                        logger.warning(
                            "[monthly_vacuum] %s wal_checkpoint busy（有并发写，未截断）: %s",
                            fname, tuple(row),
                        )
                        checkpointed.append(fname)  # 仍记（已尽力）
                finally:
                    cconn.close()
            except Exception as e:
                logger.warning("[monthly_vacuum] %s VACUUM/checkpoint 失败: %s", fname, e)
                errors.append(f"{fname}: {e}")

        logger.info(
            "[monthly_vacuum] year=%s vacuumed=%s checkpointed=%s errors=%s",
            target_year, vacuumed, checkpointed, errors,
        )
        return {
            "vacuumed": vacuumed,
            "checkpointed": checkpointed,
            "errors": errors,
            "status": "ok" if not errors else "partial",
        }

    def _execute_kline_refresh(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """S090 B：baostock_kline_cache 日更——盘后增量刷新当日新 bar。

        调 ``tools/refresh_kline_cache.main`` 增量刷新（从各股最新 bar 后拉到
        last_trading_date，原子写 temp→rename）。baostock 非东财不被 IP 限流
        （§44 grill 资金流被 push2his 限流，kline 不受影响），可每日跑。

        payload 可选：``max_stocks``（None=全量，debug 用）。
        返回 ``{"status": "ok"|"degraded", "return_code": int}``。baostock 未装 /
        cache 不存在 / login 失败标 degraded 不崩（main 内部返 1）。
        """
        max_stocks = payload.get("max_stocks")
        try:
            from tools.refresh_kline_cache import main as _refresh_kline  # noqa: PLC0415
            ret = _refresh_kline(max_stocks)
            return {"status": "ok" if ret == 0 else "degraded", "return_code": ret}
        except ImportError as e:  # noqa: BLE001
            logger.warning("[kline_refresh] baostock 未安装: %s", e)
            return {"status": "degraded", "reason": f"baostock 未安装: {e}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[kline_refresh] 刷新失败（不阻塞）: %s", exc)
            return {"status": "degraded", "reason": str(exc)}


_manager = ScheduledTaskManager()


# ============================================================================
# S093 R10/R12：通知内容构建 + AI 盘后总结 stub
# ============================================================================


def _compute_dual_confirmation(target: str, final_cards: list[dict]) -> int:
    """计算双重确认数（漏斗 final_candidates ∩ breakout candidates，spec R10）。

    调 ``select_premarket_with_risk(forward)`` 读本地 kline 算交集，成本低。
    forward = F 的下一交易日（vr_paths.next_trading_date）。失败返 0（不臆造）。
    """
    try:
        from datetime import date as _date
        from vr_paths import next_trading_date
        from strategies.premarket_selection import select_premarket_with_risk

        forward = next_trading_date(_date.fromisoformat(target)).isoformat()
        selection = select_premarket_with_risk(forward)
        breakout_codes = {c.code for c in selection.candidates}
        funnel_codes = {c.get("code", "") for c in final_cards if c.get("code")}
        return len(funnel_codes & breakout_codes)
    except Exception as e:
        logger.warning("[candidate_funnel_precompute] 双重确认计算失败: %s", e)
        return 0


def _compute_strategy_map(target: str) -> dict[str, list[str]]:
    """从 scored_candidates 构建 code→[strategy_name] 映射（通知 top5 命中战法用）。

    轻量：load_gene_scores(DB 读) + score_candidates(CPU)，skip fetch_zt_pool
    （pool_item_map=None 降级——storm_reversal/PRD 不命中，既有战法不受影响）。
    失败返空 dict（不臆造战法命中）。
    """
    try:
        from limitup_screener.data import load_gene_scores
        from strategies.strategy_funnel_registry import score_candidates
        from sentiment_context import build_context

        genes = load_gene_scores(target)
        if not genes:
            return {}
        weather = build_context(target).weather_state
        cand_input = [
            {
                "code": g.code,
                "name": getattr(g, "name", ""),
                "factors": getattr(g, "factors", {}) or {},
                "total_score": getattr(g, "total_score", 0) or 0,
                "zt_count_250d": getattr(g, "zt_count_250d", 0) or 0,
            }
            for g in genes
        ]
        scored = score_candidates(cand_input, weather, "limitup", target, None)
        scored = [s for s in scored if s.get("strategy_code") != "none"]
        out: dict[str, list[str]] = {}
        for s in scored:
            code = s.get("code", "")
            sn = s.get("strategy_name", "")
            if code and sn:
                out.setdefault(code, []).append(sn)
        return out
    except Exception as e:
        logger.warning("[candidate_funnel_precompute] 战法映射计算失败: %s", e)
        return {}


def _build_premarket_notification_content(
    f_date: str,
    final_cards: list[dict],
    dual_count: int,
    strategy_map: dict[str, list[str]],
) -> str:
    """构建前瞻选股通知内容（spec R10 富内容卡片 Markdown）。

    内容：F 日期 + final_candidates 数 + 双重确认数 + top5 标的（code/name/基因分/命中战法）。
    标注历史统计特征风险提醒（CLAUDE.md §1.2 工程底线 + §7 合规自查）。
    """
    lines: list[str] = [
        f"📊 前瞻选股结果 {f_date}",
        "",
        f"漏斗最终候选: {len(final_cards)} 只",
        f"交集计数（§44 未 validated，排序参考非 edge）: {dual_count} 只",
        "",
    ]
    top5 = final_cards[:5]
    if top5:
        lines.append("Top 5 标的:")
        for c in top5:
            code = c.get("code", "")
            name = c.get("name", "")
            gs = c.get("gene_score") or {}
            gene_score = gs.get("total_score", "—")
            strategies = strategy_map.get(code, [])
            strat_str = "、".join(strategies) if strategies else "—"
            lines.append(f"  - {name}({code}) 基因分:{gene_score} 战法:{strat_str}")
        lines.append("")
    lines.append("历史统计特征，参考值，非执行指令；市场有风险")
    return "\n".join(lines)


# ============================================================================
# S101 飞书多点通知：辅助函数 + 3 个时点通知内容构建
# ============================================================================

# §44 raw-shadow 口径风险提醒（所有 S101 通知尾挂）
_S101_DISCLAIMER = "参考值，非执行指令；§44 未验证，市场有风险"


def _load_final_cards(f_date: str) -> list[dict]:
    """读 F 日 funnel_cache final_candidates（model_dump 列表）。无缓存返空。"""
    try:
        from candidate_funnel.funnel_cache import load_funnel_result

        result = load_funnel_result(f_date, "all")
        if result is None:
            return []
        return [c.model_dump(mode="json") for c in result.final_candidates]
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] load_final_cards %s 失败: %s", f_date, e)
        return []


def _fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量 tencent_quote 取实时行情。失败返空 dict（不臆造）。"""
    if not codes:
        return {}
    try:
        import astock

        raw = astock.tencent_quote(codes) or {}
        # raw[code] = dict with price/change_pct/last_close/open/limit_up 等
        return {c: raw.get(c, {}) for c in codes if raw.get(c)}
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] fetch_quotes 失败: %s", e)
        return {}


def _send_notify(content: str) -> bool:
    """发飞书通知。不可用/失败返 False（不崩）。"""
    try:
        from notification.notification_service import NotificationService

        ns = NotificationService()
        if not ns.is_available():
            return False
        return bool(ns.send(content, route_type="alert", severity="info"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] send_notify 失败: %s", e)
        return False


def _fmt_pct(v) -> str:
    """格式化百分比，None/非数 → '—'。"""
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _check_premarket_kill_switch() -> dict:
    """S136：盘前通知开盘后实时核市场熔断（market_note 承诺落地）。

    check_market_kill_switch 查上证<-3%/创业板<-4%→triggered 不开新仓。
    astock.index_quote() 不可达/空 → check_market_kill_switch 返 not_triggered
    （不臆造熔断）。检查本身抛 → 降级 not_triggered（不阻断通知，诚实标降级）。
    """
    try:
        from strategies.execution_model import check_market_kill_switch
        import astock  # noqa: PLC0415
        ks = check_market_kill_switch(astock.index_quote())
        return {
            "triggered": ks.triggered,
            "reason": ks.reason,
            "sh_change_pct": ks.sh_change_pct,
            "gem_change_pct": ks.gem_change_pct,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[S136] kill_switch 检查失败，降级 not_triggered: %s", e)
        return {"triggered": False, "reason": f"检查失败（降级不触发）: {e}",
                "sh_change_pct": None, "gem_change_pct": None}


def _prepend_kill_switch_warning(content: str, ks: dict) -> str:
    """S136：熔断触发时通知 content 前置警告块。

    honest 标注非屏蔽——候选仍列（用户需知熔断+候选），前置块明确 gate 状态
    「不开新仓」。对齐 S126 诚实范式（标注非屏蔽）。
    """
    pct = ""
    if ks.get("sh_change_pct") is not None:
        pct += f"上证 {ks['sh_change_pct']:.2f}%"
    if ks.get("gem_change_pct") is not None:
        pct += f"{' / ' if pct else ''}创业板 {ks['gem_change_pct']:.2f}%"
    pct_str = f"（{pct}）" if pct else ""
    return (
        f"⚠️ 市场熔断：{ks.get('reason', '')}{pct_str}\n"
        f"不开新仓。premarket 候选风控价仅供参考，熔断中不入场。\n"
        f"---\n"
        f"{content}"
    )


def _build_auction_notify_content(
    f_date: str, final_cards: list[dict], quotes: dict[str, dict],
) -> str:
    """9:25 竞价确认通知：逐只高开/低开/平开（open vs last_close）。"""
    lines = [f"🔔 9:25 竞价确认 {f_date}", "", f"竞价标的 {len(final_cards)} 只:"]
    for c in final_cards:
        code = c.get("code", "")
        name = c.get("name", "") or code
        q = quotes.get(code, {})
        open_p = q.get("open")
        last_close = q.get("last_close")
        if open_p and last_close and last_close > 0:
            gap = (open_p - last_close) / last_close * 100
            tag = "高开" if gap > 0.1 else ("低开" if gap < -0.1 else "平开")
            lines.append(f"  - {name}({code}) {tag} {_fmt_pct(gap)}")
        else:
            lines.append(f"  - {name}({code}) 竞价数据待接入")
    lines.append("")
    lines.append(_S101_DISCLAIMER)
    return "\n".join(lines)


def _build_open_notify_content(
    f_date: str, final_cards: list[dict], quotes: dict[str, dict],
) -> str:
    """9:35 开盘表现通知：逐只现价/涨跌幅/封板状态。"""
    lines = [f"📈 9:35 开盘表现 {f_date}", "", f"开盘标的 {len(final_cards)} 只:"]
    for c in final_cards:
        code = c.get("code", "")
        name = c.get("name", "") or code
        q = quotes.get(code, {})
        price = q.get("price")
        change = q.get("change_pct")
        limit_up = q.get("limit_up_price") or q.get("limit_up")
        if price and limit_up and float(price) >= float(limit_up):
            tag = "封板"
        elif price:
            tag = "未封板"
        else:
            tag = "行情待接入"
        price_str = f"{float(price):.2f}" if price else "—"
        lines.append(f"  - {name}({code}) {price_str} {_fmt_pct(change)} {tag}")
    lines.append("")
    lines.append(_S101_DISCLAIMER)
    return "\n".join(lines)


def _compute_t1_returns(
    final_cards: list[dict], f_date: str, t_date: str,
) -> list[dict]:
    """算 final_candidates 在 T 日的 close2close 收益（F close → T close）。

    从 baostock_kline_cache 读 F 日 close + T 日 close。缺数据跳过（不臆造收益）。
    """
    try:
        from strategies.premarket_selection import KLINE_CACHE
        import json

        cache = json.loads(KLINE_CACHE.read_bytes())
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] t1 读 kline cache 失败: %s", e)
        return []

    out: list[dict] = []
    for c in final_cards:
        code = c.get("code", "")
        name = c.get("name", "") or code
        bars = cache.get(code, [])
        f_close = _bar_close(bars, f_date)
        t_close = _bar_close(bars, t_date)
        if f_close and t_close and f_close > 0:
            ret = (t_close - f_close) / f_close * 100
            out.append({
                "code": code, "name": name,
                "f_close": round(f_close, 2), "t_close": round(t_close, 2),
                "return_pct": round(ret, 2),
            })
    return out


def _bar_close(bars: list[dict], target_date: str) -> float | None:
    """从 baostock bars 找 target_date 的 close。"""
    for b in bars:
        if b.get("date") == target_date:
            close = b.get("close")
            try:
                return float(close) if close else None
            except (TypeError, ValueError):
                return None
    return None


def _build_t1_review_content(
    f_date: str, t_date: str, returns: list[dict],
) -> str:
    """T+1 复盘通知：均值/胜率/逐只 + §44 诚实口径。"""
    n = len(returns)
    if n == 0:
        lines = [
            f"📋 T+1 复盘 {f_date}→{t_date}",
            "",
            "无 T+1 收益数据（baostock kline 待更新或无候选）",
            "",
            _S101_DISCLAIMER,
        ]
        return "\n".join(lines)

    rets = [r["return_pct"] for r in returns]
    mean_ret = sum(rets) / n
    wins = sum(1 for r in rets if r > 0)
    win_rate = wins / n * 100
    # §44 口径：n<30 标样本不足；不宣称 alpha（lift<2x=噪声）
    sample_note = "样本不足(n<30)，不下结论" if n < 30 else f"n={n}"

    lines = [
        f"📋 T+1 复盘 {f_date}→{t_date}",
        "",
        f"标的 {n} 只 · 均值收益 {_fmt_pct(mean_ret)} · 红盘 {wins}/{n}（{win_rate:.0f}%）",
        f"§44 口径：{sample_note}，未 validated，不宣称 alpha",
        "",
        "逐只收益:",
    ]
    for r in returns:
        lines.append(f"  - {r['name']}({r['code']}) {_fmt_pct(r['return_pct'])} ({r['f_close']}→{r['t_close']})")
    lines.append("")
    lines.append(_S101_DISCLAIMER)
    return "\n".join(lines)


def generate_daily_summary(date: str) -> str:
    """S093 R12 AI 盘后总结 stub — 返空串 + 落存储位。

    S094 完整实现：LLM 汇总当日信号 + 持仓表现 + 市场数据，生成
    "今日操作回顾 + 明日建议"自然语言总结。本 stub 只返空串 + 创建存储位文件
    （接口最小定义，spec R12 / Oracle 非阻断 #14）。
    """
    summary = ""  # stub：空串，S094 完整实现
    try:
        from vr_paths import resolve_data_dir

        d = Path(resolve_data_dir()) / "daily_summaries"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{date}.txt").write_text(summary, encoding="utf-8")
    except Exception as e:
        logger.warning("[daily_ai_summary] 存储位写入失败: %s", e)
    return summary


# ============================================================================
# 模块级 executor 包装（向后兼容：旧测试/调用方按 st._execute_* 访问）
# ============================================================================
# S011-A R2 重构将 executor 方法从模块级函数迁入 TaskExecutor 类，部分旧测试与
# 调用方仍按 st._execute_xxx(ctx, payload) 访问（ctx 占位，executor 内部不用）。
# 此处提供向后兼容包装：转调默认 TaskExecutor 实例的对应方法。
# executor 方法不自持久状态（DB 操作走模块级 _manager），每次 new 实例无副作用。
def _execute_s066_validation_checkpoint(ctx, payload):
    """§44 60 天复验检查点（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_s066_validation_checkpoint(payload)


def _execute_evaluation_backtest(ctx, payload):
    """S151 R3 评价层回溯检查点（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_evaluation_backtest(payload)


def _execute_forward_test_daily(ctx, payload):
    """S069 R1 每日 forward_test picks 记录（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_forward_test_daily(payload)


def _execute_forward_test_t1_settle(ctx, payload):
    """S069 R2 T+1 收益回填（模块级兼容包装；ctx 占位忽略）。"""
    return TaskExecutor()._execute_forward_test_t1_settle(payload)


# ============================================================================
# Cron 表达式匹配
# ============================================================================

# 各字段合法值域：[分, 时, 日, 月, 周]，weekday 0=周一..6=周日
_CRON_FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _cron_token_match(token: str, value: int, lo: int, hi: int) -> bool:
    """单个逗号子项匹配：支持 单值 / */n / a-b / a-b/n。非法子项返回 False。"""
    step = 1
    range_part = token
    if "/" in token:
        range_part, step_str = token.split("/", 1)
        if not step_str.isdigit() or int(step_str) <= 0:
            return False
        step = int(step_str)

    if range_part == "*":
        return value % step == 0

    if "-" in range_part:
        a_str, b_str = range_part.split("-", 1)
        if not a_str.isdigit() or not b_str.isdigit():
            return False
        a, b = int(a_str), int(b_str)
        if a < lo or b > hi or a > b:
            return False
        return a <= value <= b and (value - a) % step == 0

    if not range_part.isdigit():
        return False
    n = int(range_part)
    if n < lo or n > hi:
        return False
    if step == 1:
        return value == n
    return value >= n and (value - n) % step == 0


def _cron_field_match(field: str, value: int, lo: int, hi: int) -> bool:
    """单字段匹配：``*`` 恒 True；逗号分隔的任意一个子项命中即命中。"""
    if field == "*":
        return True
    for token in field.split(","):
        if _cron_token_match(token, value, lo, hi):
            return True
    return False


def cron_match(cron_expr: str, dt: datetime) -> bool:
    """cron 5 段表达式匹配（分 时 日 月 周）。纯函数，非法输入一律 False、不抛异常。

    - ``*`` → 恒 True
    - 单值数字 → 相等
    - ``*/n`` → value % n == 0（``*/0`` / ``*/x`` 非法 → False；``*/1`` 等价 ``*``）
    - ``a-b`` → 含边界的范围
    - ``a-b/n`` → 范围内且 (value - a) % n == 0
    - 逗号 OR（可混合 range，如 ``0-30,45``）
    - weekday 用 ``dt.weekday()``（0=周一..6=周日）
    """
    try:
        parts = cron_expr.split()
        if len(parts) != 5:
            return False
        values = (dt.minute, dt.hour, dt.day, dt.month, dt.weekday())
        for field, value, (lo, hi) in zip(parts, values, _CRON_FIELD_BOUNDS):
            if not _cron_field_match(field, value, lo, hi):
                return False
        return True
    except Exception:
        return False


# ============================================================================
# Cron 调度器
# ============================================================================

# 心跳间隔（秒）：_ticker 每两次 tick 之间 sleep 的时长。模块级常量以便测试
# monkeypatch 缩短心跳（st._TICK_INTERVAL）。
_TICK_INTERVAL = 60


class CronScheduler:
    """轻量 cron-like 调度器，每分钟检查一次。

    S032 R6：ticker 挂调用方（FastAPI 主）事件循环——``await start()`` 在
    当前循环 create_task；不再有 daemon 线程 + 自建循环的桥接（S011 R6 兑现）。
    """

    def __init__(self, executor: Optional[TaskExecutor] = None):
        self._executor = executor or TaskExecutor()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # R4：正在执行的任务 id 集合，用于 _tick 去重（fire-and-forget）
        self._running_task_ids: set = set()
        # S032 R6：已 spawn 的 _run_task 集合（done 即弃）——生产 stop 不等待，
        # 测试可据此等 fire-and-forget 任务落终态 run。
        self._spawned: set = set()

    async def start(self) -> None:
        """在当前（FastAPI 主）事件循环启动 ticker task。

        R4 重启恢复：进程重启后 DB 里可能残留 status="running" 的 run 行（上一次
        进程非正常退出），启动前用 count_running 重建 _running_task_ids——残留 running
        的任务视为"仍在执行中"，_tick 会跳过它们，防止重启后重复执行/卡死。
        """
        if self._running:
            return
        # R4 重启恢复：DB 残留 running 行的任务加入去重集合，防重启后重放。
        # S150 R2：重建前先 reap stale running（>800s 挂死），避免把挂死 run 重新加回
        # _running_task_ids 致重启也救不了（fork 根因 B：line 2180 重建回 stale）。
        self._reap_stale_runs()
        for t in _manager.list_tasks():
            if t.id is not None and _manager.count_running(t.id) > 0:
                self._running_task_ids.add(t.id)
        self._running = True
        self._task = asyncio.get_running_loop().create_task(self._ticker())
        logger.info("[scheduler] 定时任务调度器已启动（主循环 ticker）")

    async def stop(self) -> None:
        """停止：置标志 + cancel ticker task，限时等待不阻塞 shutdown。

        已 spawn 的 _run_task 子任务（fire-and-forget）随主循环关闭终止——
        与 S031 daemon 不 join 政策一致：强杀进程时运行中任务被取消，
        DB 残留 running 行由下次启动的 R4 恢复逻辑接管。
        """
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=2.0)
            except BaseException:  # noqa: BLE001 — CancelledError/TimeoutError 均预期
                pass
            self._task = None
        logger.info("[scheduler] 定时任务调度器已停止")

    async def _ticker(self) -> None:
        """心跳循环：周期性执行 _tick，异常不中断循环。"""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.warning("[scheduler] tick 异常: %s", e)
            await asyncio.sleep(_TICK_INTERVAL)

    async def _tick(self) -> None:
        # R9：统一 BEIJING_TZ——now 带时区，cron 命中按北京时间比较（懒导入避免模块级重依赖）
        from limitup_screener import BEIJING_TZ
        now = datetime.now(BEIJING_TZ)
        # S150 R2：每轮 reap stale running run（>800s 视挂死）→ DB 标 failed + discard
        # _running_task_ids，防 collect_once 挂死堵 dedup（根因 B 真修，与 R1 timeout 双保险）
        self._reap_stale_runs()
        tasks = [t for t in _manager.list_tasks() if t.enabled]
        for task in tasks:
            # R4：cron 命中且未在执行中的任务才触发，避免同一任务并发重复执行
            if self._should_run(task, now) and task.id not in self._running_task_ids:
                logger.info("[scheduler] 触发任务: %s (%s)", task.name, task.id)
                self._running_task_ids.add(task.id)
                spawned = asyncio.create_task(self._run_task(task))
                self._spawned.add(spawned)
                spawned.add_done_callback(self._spawned.discard)

    async def _run_task(self, task: ScheduledTask) -> TaskRun:
        """执行单个任务（fire-and-forget），完成后清理去重标志。"""
        try:
            return await self._executor.execute_async(task)
        finally:
            self._running_task_ids.discard(task.id)

    def _should_run(self, task: ScheduledTask, now: datetime) -> bool:
        """cron 匹配：委托模块级纯函数 cron_match。"""
        return cron_match(task.cron_expr, now)

    def _reap_stale_runs(self) -> None:
        """S150 R2：reap stale running run → discard _running_task_ids（去堵 dedup）。

        每轮 _tick + start 重建前调，清 DB stale（>800s 挂死）→ 返 task_id 列表 →
        从 _running_task_ids discard，让被堵 task 能再触发（根因 B 真修）。
        """
        try:
            reaped = _manager.reap_stale_running(_REAPER_STALE_SECONDS)
            for task_id in reaped:
                self._running_task_ids.discard(task_id)
            if reaped:
                logger.info("[scheduler] reap stale runs (task_ids): %s", reaped)
        except Exception as e:  # noqa: BLE001 — reap 失败不阻断 tick
            logger.warning("[scheduler] reap stale runs 失败: %s", e)


_scheduler: Optional[CronScheduler] = None


def get_scheduler() -> CronScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler


async def start_scheduler() -> None:
    """启动调度器（主循环 ticker）+ seed 默认任务。须在运行中的事件循环内 await（lifespan）。"""
    await get_scheduler().start()
    _ensure_seed_tasks()


def _ensure_seed_tasks() -> None:
    """R13：seed 默认定时任务——盘后涨停预计算（工作日 15:30）。幂等（重名跳过）。

    cron `30 15 * * 0-4`：cron_match 用 Python datetime.weekday()（0=周一..6=周日，
    见 test_cron_should_run），故工作日=0-4（Mon-Fri）。spec 原写 `1-5`（标准 cron 习惯）
    在本约定下=周二至周六，与"跳周末"意图不符，已按 0=周一 约定修正为 0-4。
    节假日精确判断推 S011b（trading_calendar.json 本轮不建，非交易日由 screener
    返空涨停池自然处理）。

    S101 迁移：candidate_funnel_precompute cron 曾被手改为 16:05（`5 16`），早于
    gene_scores 写入完成（limitup_precompute 15:30 起，全量基因得分+STI 跑 >30min
    未写完），致漏斗 R1 宽源输入 0 → final_candidates=0 → 通知"0 只"。改回 17:15
    （晚 derived_precompute 16:30 +15min，龙虎榜 16:30 后 + gene_scores 写完）。
    """
    existing = {t.name for t in _manager.list_tasks()}

    # S101 迁移：把偏离的 candidate_funnel_precompute cron 拉回 17:15（一次，幂等）
    for t in _manager.list_tasks():
        if t.name == "candidate_funnel_precompute" and t.cron_expr != "15 17 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "15 17 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] candidate_funnel_precompute cron 迁移 %s → 15 17 * * 0-4"
                "（S101：等 gene_scores 写入完成 + 龙虎榜 16:30 后）",
                old_cron,
            )
    if "limitup_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="limitup_precompute",
            description="盘后涨停板基因得分+STI+竞价+复盘预计算（S031 R13 seed）",
            task_type="limitup_precompute",
            cron_expr="30 15 * * 0-4",
            payload={"back_days": 10},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 limitup_precompute 已创建（cron 30 15 * * 0-4）")

    if "sti_post_market" not in existing:
        _manager.create_task(ScheduledTask(
            name="sti_post_market",
            description="S063 盘后 STI 定时计算（交易日 15:30，持久化成为 T+1 硬标准）",
            task_type="sti_post_market",
            cron_expr="35 15 * * 0-4",  # 15:35（晚 precompute 5min，避免并发抢 DB）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 sti_post_market 已创建（cron 35 15 * * 0-4）")

    # S055：盘中封单时序采集——交易时段每分钟 tick。
    # cron `* 9-15 * * 0-4` 触发 09:00-15:59（末次触发延至 15:59，含 15:00 收盘
    # 集合竞价终态）。实际写入由 is_intraday_trading_time（09:25-11:30 / 13:01-15:05）
    # 在 collect_once 内门控——15:06-15:59 的 no-op 触发在 em_get 前早返 skipped
    # （防封安全，已实锤：collect_once 第一行门在 em_zt_topic_pool 之前）。
    if "seal_intraday_collect" not in existing:
        _manager.create_task(ScheduledTask(
            name="seal_intraday_collect",
            description="S055 盘中封单时序采集（交易时段 09:25-15:05 每 60s 轮询 em_zt_topic_pool）",
            task_type="seal_intraday_collect",
            cron_expr="* 9-15 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 seal_intraday_collect 已创建（cron * 9-15 * * 0-4）")

    # S148 R3：盘后 ST-play radar——摘帽/重组/扭亏 白名单（供 classify_tradability ST carve-out）。
    # 17:30 工作日：晚 candidate_funnel_precompute 17:15（gene_scores 写完）+ zt_history_snapshot 17:15 后。
    if "st_play_radar" not in existing:
        _manager.create_task(ScheduledTask(
            name="st_play_radar",
            description="S148 盘后 ST-play radar：扫 ST 股公告 → 摘帽/重组/扭亏 白名单（ST carve-out）",
            task_type="st_play_radar",
            cron_expr="30 17 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 st_play_radar 已创建（cron 30 17 * * 0-4）")

    # S167：盘中微结构数据累积（"等 live" 路径）——累积实时无历史源供 §44v2 复测。
    # 周期快照：每 10min（09:00-15:00 触发，is_intraday_time 门控 09:25-11:30/13:01-15:05）。
    # 诚实：accumulation for future §44v2, prior LOW (S152/S156 refuted), no edge claim yet。
    if "intraday_microstructure_snapshot" not in existing:
        _manager.create_task(ScheduledTask(
            name="intraday_microstructure_snapshot",
            description="S167 盘中微结构周期快照（hithink 排名 + tencent 量比，每 10min 累积供 §44v2 复测）",
            task_type="intraday_microstructure_snapshot",
            cron_expr="*/10 9-15 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 intraday_microstructure_snapshot 已创建（cron */10 9-15 * * 0-4）")

    # S167 baostock 5min 次日冻结——09:00 冻结 prev_trading_date 涨停股 5min bars
    # （当日 bar T+1 lag，次日 09:00 bars 稳定）。is_trading_day 门控（节假日跳）。
    if "baostock_5min_freeze" not in existing:
        _manager.create_task(ScheduledTask(
            name="baostock_5min_freeze",
            description="S167 次日冻结 prev_trading_date 涨停股 baostock 5min bars（秒板/封板时间派生，供 §44v2）",
            task_type="baostock_5min_freeze",
            cron_expr="0 9 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 baostock_5min_freeze 已创建（cron 0 9 * * 0-4）")

    # S123 R3：既有 DB 迁移——seed 仅 `if not in existing` 建任务，旧库仍存 cron
    # `* 9-14 * * 0-4`（末次触发 14:59，漏采 15:00 收盘集合竞价终态）。幂等更新：
    # 仅旧 cron 才改（新 cron 已是目标值→no-op），对齐 candidate_funnel_precompute 迁移范式。
    for t in _manager.list_tasks():
        if t.name == "seal_intraday_collect" and t.cron_expr == "* 9-14 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "* 9-15 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] seal_intraday_collect cron 迁移 %s → * 9-15 * * 0-4"
                "（S123 R3：覆盖 15:00 收盘集合竞价终态，写入由 is_intraday_trading_time 门控）",
                old_cron,
            )

    # S004 R5：盘后漏斗预计算——晚 derived_precompute 15min（读 derived 预采集）+ 龙虎榜 16:30 后。
    # candidate_funnel 走 fund_flow 取龙虎榜（dragon_tiger_board，东财 16:30 后才更新），
    # 故漏斗预计算须在 16:30 后；且 derived_source 读 derived 预采集，须晚 derived_precompute。
    if "candidate_funnel_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="candidate_funnel_precompute",
            description="S004 盘后漏斗预计算（预热 _FUNNEL_CACHE，龙虎榜 16:30 后 + 读 derived 预采集）",
            task_type="candidate_funnel_precompute",
            cron_expr="15 17 * * 0-4",  # 17:15（晚 derived_precompute 17:00 +15min，龙虎榜 16:30 后）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 candidate_funnel_precompute 已创建（cron 15 17 * * 0-4）")

    # S075：盘后首板流筛选——16:15（晚 forward_test_t1_settle 15:50，避抢 DB；
    #   candidate_funnel_precompute 已后移 17:15，与 first_board 不再同刻抢 DB）。
    if "first_board_filter" not in existing:
        _manager.create_task(ScheduledTask(
            name="first_board_filter",
            description="S075 盘后首板流筛选（首板过滤+三层剔除+9维度评分，15:30后跑）",
            task_type="first_board_filter",
            cron_expr="15 16 * * 0-4",  # 16:15（晚 forward_test_t1_settle 15:50）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 first_board_filter 已创建（cron 15 16 * * 0-4）")

    # S090 B：kline 日更——盘后 16:30 增量刷新 baostock_kline_cache（premarket breakout 数据源）。
    # baostock 非东财不被限流；晚 first_board_filter 16:15 +15min，盘后拉当日新 bar。
    if "kline_refresh" not in existing:
        _manager.create_task(ScheduledTask(
            name="kline_refresh",
            description="S090 B：盘后 baostock_kline_cache 增量刷新（premarket breakout 数据源日更）",
            task_type="kline_refresh",
            cron_expr="30 16 * * 0-4",  # 16:30（晚 first_board_filter 16:15 +15min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 kline_refresh 已创建（cron 30 16 * * 0-4）")

    # §44 60 天复验检查点（提醒任务）：周一 18:00 数 eastmoney_live 日数，达 60 →
    # 写 s066_60day_due.json + WARNING + notify_on_success 推送（通道未配则静默）。
    # 到点由人/会话跑 backfill --weather 查 lift；本任务只提醒不自动验证。
    if "s066_validation_checkpoint" not in existing:
        _manager.create_task(ScheduledTask(
            name="s066_validation_checkpoint",
            description="§44 60 天复验检查点：eastmoney_live 达 60 日提醒重跑 Phase 0b/0e（spec §13 ①）",
            task_type="s066_validation_checkpoint",
            cron_expr="0 18 * * 1",  # 周一 18:00（每周检查一次，到点提醒）
            payload={"threshold": 60},
            enabled=True,
            notify_on_success=True,
        ))
        logger.info("[scheduler] seed 默认任务 s066_validation_checkpoint 已创建（cron 0 18 * * 1，§44 60 天复验提醒）")

    # S151 R3：评价层回溯检查点（提醒任务）：周一 18:05 数 forward_test 信号日 + buyable picks，
    # 30 日 + n≥100 → 首次回溯 DUE（写 s151_evaluation_backtest_due.json + WARNING）；
    # 60 日 → 复验 DUE。到点只提醒不自动验证（同 s066）——由人/会话跑 day_paired_lift harness。
    if "evaluation_backtest" not in existing:
        _manager.create_task(ScheduledTask(
            name="evaluation_backtest",
            description="S151 R3：评价层 30日首次/60日复验回溯检查点（§44 per-dimension lift 提醒）",
            task_type="evaluation_backtest",
            cron_expr="5 18 * * 1",  # 周一 18:05（晚 s066 18:00，同窗口周一一次）
            payload={"first_threshold": 30, "reverify_threshold": 60, "min_n": 100},
            enabled=True,
            notify_on_success=True,
        ))
        logger.info("[scheduler] seed 默认任务 evaluation_backtest 已创建（cron 5 18 * * 1，S151 回溯提醒）")

    # S069 R1：每日 post-market 记当日 forward_test picks + universe（晚 limitup_precompute 15min）。
    # weather 用 build_context（完整架构）；T+1 收益由 R2 次日回填（待接）。
    if "forward_test_daily" not in existing:
        _manager.create_task(ScheduledTask(
            name="forward_test_daily",
            description="S069 R1：每日 post-market 记当日 forward_test picks+universe（§44 数据日积）",
            task_type="forward_test_daily",
            cron_expr="45 15 * * 0-4",  # 15:45（晚 precompute 15:30 + sti 15:35）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 forward_test_daily 已创建（cron 45 15 * * 0-4）")

    # S069 R2：每日 post-market 回填昨日 forward_test T+1 收益（baostock kline 次日 bar）。
    if "forward_test_t1_settle" not in existing:
        _manager.create_task(ScheduledTask(
            name="forward_test_t1_settle",
            description="S069 R2：每日 post-market 回填昨日 forward_test picks+universe 的 T+1 收益",
            task_type="forward_test_t1_settle",
            cron_expr="50 15 * * 0-4",  # 15:50（晚 R1 15:45，next_bar 今日收盘后可得）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 forward_test_t1_settle 已创建（cron 50 15 * * 0-4）")

    # S075：盘后 T+1 溢价评分 + 复盘报告 + 飞书通知（晚 first_board_filter 16:15 +15min）。
    # 对 T-1 候选做 T+1 收益评价，构造 Markdown 复盘报告，飞书推送用户。
    if "first_board_t1_review" not in existing:
        _manager.create_task(ScheduledTask(
            name="first_board_t1_review",
            description="S075 T+1 溢价评分+复盘报告+飞书通知（盘后对 T-1 候选做收益评价）",
            task_type="first_board_t1_review",
            cron_expr="30 16 * * 0-4",  # 16:30（晚 first_board_filter 16:15 +15min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 first_board_t1_review 已创建（cron 30 16 * * 0-4）")

    # S084 C1：盘后 derived 异步预采集——17:00 对昨日涨停股全量算派生落 seal_derived_features，
    # 选股池 derived_source 读预采集（不 per-code 实时算）。龙虎榜 16:30 后统一盘后跑，
    # derived 不依赖龙虎榜但提前 candidate_funnel_precompute 17:15（漏斗读 derived 预采集）。
    if "derived_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="derived_precompute",
            description="S084 盘后 derived 异步预采集（昨日涨停股全量算派生落 seal_derived_features，选股池读预采集）",
            task_type="derived_precompute",
            cron_expr="0 17 * * 0-4",  # 17:00 工作日（0=周一约定，龙虎榜 16:30 后 + 早 candidate 17:15）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 derived_precompute 已创建（cron 0 17 * * 0-4）")

    # S089 D2：月度 VACUUM + wal_checkpoint(TRUNCATE)——月初 02:00 跑（低负载时段，
    # 避开盘后批处理 15:30-17:15）。当年热库 VACUUM 回收碎片 + 截断 -wal 防膨胀。
    if "monthly_vacuum" not in existing:
        _manager.create_task(ScheduledTask(
            name="monthly_vacuum",
            description="S089 月度 VACUUM + wal_checkpoint(TRUNCATE)——当年热库回收碎片+截断 -wal 防膨胀",
            task_type="monthly_vacuum",
            cron_expr="0 2 1 * *",  # 每月 1 日 02:00
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 monthly_vacuum 已创建（cron 0 2 1 * *，月初 02:00）")

    # S093 R12：AI 盘后总结 stub——15:30（与 stage 推进点 intraday→post_transition 15:30 对齐）。
    # S094 完整实现：LLM 汇总当日信号 + 持仓表现。本 stub 返空串 + 落存储位。
    if "daily_ai_summary" not in existing:
        _manager.create_task(ScheduledTask(
            name="daily_ai_summary",
            description="S093 R12：AI 盘后总结 stub（cron 15:30，S094 完整实现 LLM 汇总）",
            task_type="daily_ai_summary",
            cron_expr="30 15 * * 0-4",  # 15:30（与 limitup_precompute 同刻，stub 无 DB 写不抢锁）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 daily_ai_summary 已创建（cron 30 15 * * 0-4）")

    # S101：飞书多点通知——9:25 竞价 / 9:35 开盘 / T+1 16:35 复盘
    # 前瞻标的从 F 日 funnel_cache 读（17:15 已存），不重跑漏斗。
    if "premarket_auction_notify" not in existing:
        _manager.create_task(ScheduledTask(
            name="premarket_auction_notify",
            description="S101 9:25 竞价确认通知（前瞻标的 F 日 final_candidates 开盘竞价表现）",
            task_type="premarket_auction_notify",
            cron_expr="25 9 * * 0-4",  # 工作日 9:25（集合竞价完成后）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 premarket_auction_notify 已创建（cron 25 9 * * 0-4）")

    if "premarket_open_notify" not in existing:
        _manager.create_task(ScheduledTask(
            name="premarket_open_notify",
            description="S101 9:35 开盘表现通知（前瞻标的开盘 5min 现价/涨跌幅/封板）",
            task_type="premarket_open_notify",
            cron_expr="35 9 * * 0-4",  # 工作日 9:35（开盘后 5min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 premarket_open_notify 已创建（cron 35 9 * * 0-4）")

    if "premarket_t1_review" not in existing:
        _manager.create_task(ScheduledTask(
            name="premarket_t1_review",
            description="S101 T+1 复盘通知（前瞻标的 F→T 收益评价，§44 诚实口径）",
            task_type="premarket_t1_review",
            cron_expr="35 16 * * 0-4",  # 16:35（晚 first_board_t1_review 5min 避抢 DB）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 premarket_t1_review 已创建（cron 35 16 * * 0-4）")

    # S078：盘后终盘涨停池 snapshot——17:15（过稳定点写 is_final=true，zt_history.db）。
    # 旧 cron "0 16"（16:00 写 is_final=false，无 17:15 final run → is_final 从不自动 true）。
    # 迁移到 "15 17"（仿 :2233 candidate_funnel 范式）。幂等：存在跳过 create，旧 cron 才迁移。
    if "zt_history_snapshot" not in existing:
        _manager.create_task(ScheduledTask(
            name="zt_history_snapshot",
            description="S078 盘后终盘涨停池 snapshot（17:15 过稳定点写 is_final=true，zt_history.db 数据地基）",
            task_type="zt_history_snapshot",
            cron_expr="15 17 * * 0-4",  # 17:15（东财池盘后稳定，写 is_final=true）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 zt_history_snapshot 已创建（cron 15 17 * * 0-4）")
    for t in _manager.list_tasks():
        if t.name == "zt_history_snapshot" and t.cron_expr == "0 16 * * 0-4":
            old_cron = t.cron_expr
            t.cron_expr = "15 17 * * 0-4"
            _manager.update_task(t)
            logger.info(
                "[scheduler] zt_history_snapshot cron 迁移 %s → 15 17 * * 0-4"
                "（17:15 过稳定点写 is_final=true，旧 16:00 写 is_final=false 无 final run）",
                old_cron,
            )


async def stop_scheduler() -> None:
    if _scheduler is not None:
        await _scheduler.stop()
