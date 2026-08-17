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
    total_signals/percentile_json；strategy 取 strategy_breakdown_json（8 战法聚合）。
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
            "forward_test_daily": self._execute_forward_test_daily,  # S069 R1：每日记 forward_test picks+universe
            "forward_test_t1_settle": self._execute_forward_test_t1_settle,  # S069 R2：T+1 收益回填
        }

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
                result = await handler(task.payload)
            else:
                result = await asyncio.to_thread(handler, task.payload)
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
                except Exception:
                    pass
        except Exception:
            pass

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
            for back in range(back_days):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                await _ls.get_screener_result(d)

            try:
                engine = _ls_sti.get_sti_engine()
                for back in range(back_days):
                    d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                    engine.precompute_daily(d)
            except Exception as e:
                logger.warning("[limitup_precompute] STI 预计算失败: %s", e)

            try:
                screener = _asc.get_screener()
                for back in range(back_days):
                    d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                    screener.precompute_daily(d)
            except Exception as e:
                logger.warning("[limitup_precompute] 竞价选股预计算失败: %s", e)

            try:
                reviewer = _dr.get_reviewer()
                for back in range(back_days):
                    d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                    reviewer.precompute_daily(d)
            except Exception as e:
                logger.warning("[limitup_precompute] 复盘报告预计算失败: %s", e)

        try:
            asyncio.run(_precompute_async())
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
        """同步市场数据。"""
        results: Dict[str, Any] = {}
        try:
            import market as _market
            # 这里可以添加具体的市场数据同步逻辑
            results["market"] = "ok"
        except Exception as e:
            logger.warning("[market_data_sync] 市场数据同步失败: %s", e)
            results["market"] = f"error: {e}"

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
    """S055：盘中封单时序采集——交易时段每 60s 轮询 em_zt_topic_pool 写快照。

    采集后对每只票跑规则引擎（C1-C6）→ 去重落库 bomb_alert_history。
    非交易时段不落库、不请求东财（门控）。采集前先 prune 旧数据（保留期外）。
    缺数据诚实标注，不臆造。
    """
    from risk.seal_intraday_collector import collect_once, prune_old_snapshots, get_latest_snapshots
    from risk.bomb_alert_rules import check_all_rules
    from risk.bomb_alert_dispatcher import process_alerts

    # 每日首调 prune（payload 带 prune=True 触发，默认只采集）
    if payload.get("prune"):
        retention = int(payload.get("retention_days", 30))
        pruned = prune_old_snapshots(retention)
    else:
        pruned = 0

    result = collect_once()
    result["pruned"] = pruned

    # 采集成功后跑规则引擎（仅对本次采集的票）
    if result.get("written", 0) > 0:
        from datetime import datetime
        now = datetime.now()
        latest_snaps = get_latest_snapshots(result.get("date") or now.strftime("%Y-%m-%d"))
        triggered_total = 0
        for snap in latest_snaps:
            code = snap.get("code")
            name = snap.get("name") or code
            if not code:
                continue
            # 取该 code 全部时序（规则需窗口）
            from risk.seal_intraday_collector import get_snapshots_by_code
            snaps = get_snapshots_by_code(code, result.get("date") or now.strftime("%Y-%m-%d"))
            results = check_all_rules(snaps, code, name, now=now)
            active = process_alerts(code, name, results, now=now)
            triggered_total += len(active)
        result["alerts_triggered"] = triggered_total

    return result


# 绑定到 TaskExecutor 类（方法定义在类后，用 setattr 绑定）
TaskExecutor._execute_seal_intraday_collect = _execute_seal_intraday_collect


def _execute_candidate_funnel_precompute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """S004 R5：盘后漏斗预计算——预热 _FUNNEL_CACHE，盘后复盘页即时读缓存。

    取 date（默认最近交易日）→ run_funnel("all", date, live_config) →
    结果落 _FUNNEL_CACHE（TTL 由 config.CANDIDATE_FUNNEL_CACHE_TTL 控制，默认 3600s）。
    失败 catch 不抛，返 status=error（预计算是增强，不阻塞主流程）。
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
        funnel_mod.run_funnel("all", target, cfg)
        logger.info("[candidate_funnel_precompute] %s 漏斗预计算完成（缓存已预热）", target)
        return {"date": target, "status": "ok"}
    except Exception as e:
        logger.warning("[candidate_funnel_precompute] 预计算失败: %s", e)
        return {"status": f"error: {e}"}


TaskExecutor._execute_candidate_funnel_precompute = _execute_candidate_funnel_precompute


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


TaskExecutor._execute_first_board_filter = _execute_first_board_filter


def _execute_s066_validation_checkpoint(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """§44 60 天复验检查点（提醒任务，spec §13 ①/§44）。

    数 eastmoney_live 信号日；达 threshold（默认 60）→ 写 checkpoint 文件 + WARNING 日志
    + 返 DUE+操作指引（notify_on_success 兜底推送，若通道已配）；未到期 → 返进度（静默）。
    到点由人/会话跑 `tools/forward_test_backfill.py --weather` 查 lift——本任务只提醒不自动验证。
    """
    from config import GENE_SCORES_DB_PATH
    from vr_paths import resolve_data_dir

    threshold = int(payload.get("threshold", 60))
    conn = sqlite3.connect(GENE_SCORES_DB_PATH, timeout=10)
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


TaskExecutor._execute_s066_validation_checkpoint = _execute_s066_validation_checkpoint


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


TaskExecutor._execute_forward_test_daily = _execute_forward_test_daily


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

    conn = sqlite3.connect(GENE_SCORES_DB_PATH, timeout=10)
    try:
        rows = conn.execute(
            "SELECT DISTINCT signal_date FROM forward_test_records "
            "WHERE return_open2close IS NULL AND signal_date < ? "
            "ORDER BY signal_date DESC LIMIT 3", (today,)
        ).fetchall()
        dates = [r[0] for r in rows if r[0] not in stuck]
    finally:
        conn.close()
    if not dates:
        return {"status": "nothing_to_settle", "today": today, "stuck": len(stuck)}

    summary = []
    for signal_date in dates:
        conn = sqlite3.connect(GENE_SCORES_DB_PATH, timeout=10)
        try:
            pick_codes = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM forward_test_records "
                "WHERE signal_date=? AND return_open2close IS NULL", (signal_date,)).fetchall()]
            uni_codes = [r[0] for r in conn.execute(
                "SELECT DISTINCT code FROM universe_returns "
                "WHERE signal_date=? AND return_open2close IS NULL", (signal_date,)).fetchall()]
        finally:
            conn.close()
        all_codes = list(dict.fromkeys(pick_codes + uni_codes))
        if not all_codes:
            continue
        returns_map = compute_returns_for_codes(signal_date, all_codes)
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


TaskExecutor._execute_forward_test_t1_settle = _execute_forward_test_t1_settle


_manager = ScheduledTaskManager()


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
        # R4 重启恢复：DB 残留 running 行的任务加入去重集合，防重启后重放
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
    """
    existing = {t.name for t in _manager.list_tasks()}
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
    # cron `* 9-14 * * 0-4` 覆盖 09:00-14:59，加上 15:00-15:05 的 5 分钟。
    # 实际门控由 is_intraday_trading_time（09:25-15:05）在 collect_once 内兜底。
    if "seal_intraday_collect" not in existing:
        _manager.create_task(ScheduledTask(
            name="seal_intraday_collect",
            description="S055 盘中封单时序采集（交易时段 09:25-15:05 每 60s 轮询 em_zt_topic_pool）",
            task_type="seal_intraday_collect",
            cron_expr="* 9-14 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 seal_intraday_collect 已创建（cron * 9-14 * * 0-4）")

    # S004 R5：盘后漏斗预计算——晚 STI 30 分钟避抢 DB。
    if "candidate_funnel_precompute" not in existing:
        _manager.create_task(ScheduledTask(
            name="candidate_funnel_precompute",
            description="S004 盘后漏斗预计算（预热 _FUNNEL_CACHE，盘后复盘页即时读缓存）",
            task_type="candidate_funnel_precompute",
            cron_expr="5 16 * * 0-4",
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 candidate_funnel_precompute 已创建（cron 5 16 * * 0-4）")

    # S075：盘后首板流筛选——晚 candidate_funnel_precompute 10min 避抢 DB。
    if "first_board_filter" not in existing:
        _manager.create_task(ScheduledTask(
            name="first_board_filter",
            description="S075 盘后首板流筛选（首板过滤+三层剔除+9维度评分，15:30后跑）",
            task_type="first_board_filter",
            cron_expr="15 16 * * 0-4",  # 16:15（晚 precompute 10min）
            payload={},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 first_board_filter 已创建（cron 15 16 * * 0-4）")

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


async def stop_scheduler() -> None:
    if _scheduler is not None:
        await _scheduler.stop()
