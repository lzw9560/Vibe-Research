# -*- coding: utf-8 -*-
"""CronScheduler 调度器——async ticker 循环 + stale run reap + fire-and-forget 任务执行。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from scheduler import cron as _cron
from scheduler.db import _manager, _REAPER_STALE_SECONDS
from scheduler.executors import TaskExecutor
from scheduler.models import ScheduledTask, TaskRun

logger = logging.getLogger("vibe-research")

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
        """cron 匹配 + S190 R5 depends_on 门控。

        depends_on（逗号分隔 task_type）：今日上游 task_type 须有 status IN
        (success/degraded) 的 run，否则跳过（防下游先于上游跑吃陈旧数据）。
        """
        if not _cron.cron_match(task.cron_expr, now):
            return False
        # S190 R5：depends_on 门控
        if task.depends_on:
            from vr_paths import last_trading_date_str  # noqa: PLC0415
            today = last_trading_date_str()
            deps = [d.strip() for d in task.depends_on.split(",") if d.strip()]
            for dep_type in deps:
                if not _manager.dependency_satisfied(dep_type, today):
                    logger.info(
                        "[scheduler] %s 跳过：依赖 %s 今日未 success/degraded",
                        task.name, dep_type,
                    )
                    return False
        return True

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
    from scheduler.seed import _ensure_seed_tasks
    _ensure_seed_tasks()


async def stop_scheduler() -> None:
    if _scheduler is not None:
        await _scheduler.stop()
