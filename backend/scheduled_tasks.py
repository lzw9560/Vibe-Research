# -*- coding: utf-8 -*-
"""定时任务系统 —— 基于 SQLite 持久化的 cron-like 调度器。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_enabled ON scheduled_tasks(enabled);
            CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task_id ON scheduled_task_runs(task_id, started_at DESC);
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
            if asyncio.iscoroutinefunction(handler):
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
            payload={"back_days": 3},
            enabled=True,
        ))
        logger.info("[scheduler] seed 默认任务 limitup_precompute 已创建（cron 30 15 * * 0-4）")


async def stop_scheduler() -> None:
    if _scheduler is not None:
        await _scheduler.stop()
