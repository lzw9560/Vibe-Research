# -*- coding: utf-8 -*-
"""S248 depends_on 门控宽限重试测试（TDD RED → GREEN）。

覆盖：dep running 时下游 cron 命中不 fire 但加 _pending_retry / dep 满足后窗口内补 fire /
窗口过期放弃 / 无 dep 不影响 / dep 满足不进 pending / _run_task 清 pending。

根因实证（2026-11-11）：kline_refresh 跑 70 分钟（平日 3 分钟），candidate_funnel_precompute
17:25 tick 时 dep 仍 running → 单发精确分钟门控失败 → 链断当日 0 run。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scheduler.cron_runner import CronScheduler
from scheduler.models import ScheduledTask


def _task(id: int = 1, cron_expr: str = "25 17 * * *", depends_on: str | None = "kline_refresh") -> ScheduledTask:
    return ScheduledTask(
        id=id, name=f"task{id}", task_type=f"task{id}",
        cron_expr=cron_expr, depends_on=depends_on, enabled=True,
    )


def _sched() -> CronScheduler:
    s = CronScheduler(executor=MagicMock())
    s._pending_retry.clear()
    return s


@pytest.fixture
def sched() -> CronScheduler:
    return _sched()


@pytest.fixture
def dep_unsatisfied(monkeypatch):
    """dep 今日未 success/degraded（上游 running）。"""
    monkeypatch.setattr(CronScheduler, "_deps_satisfied", lambda self, deps: False)
    monkeypatch.setattr("scheduler.db._TASK_TIMEOUTS", {"kline_refresh": 10800})


@pytest.fixture
def dep_satisfied(monkeypatch):
    monkeypatch.setattr(CronScheduler, "_deps_satisfied", lambda self, deps: True)
    monkeypatch.setattr("scheduler.db._TASK_TIMEOUTS", {"kline_refresh": 10800})


class TestDepRetry:
    def test_dep_running_no_fire_but_pending(self, sched, dep_unsatisfied):
        """cron 命中 + dep 未满足 → False + 加入 _pending_retry（窗口=10800+300=11100s）。"""
        t = _task(id=1, cron_expr="25 17 * * *", depends_on="kline_refresh")
        now = datetime(2026, 11, 11, 17, 25)  # cron 命中
        assert sched._should_run(t, now) is False
        assert 1 in sched._pending_retry
        deadline, deps = sched._pending_retry[1]
        assert deadline == now + timedelta(seconds=11100)
        assert deps == "kline_refresh"

    def test_dep_satisfied_retries_fire_within_window(self, sched, dep_unsatisfied, monkeypatch):
        """cron 不命中 + 窗口内 dep 满足 → True（补 fire）+ 清 pending。"""
        t = _task(id=1, cron_expr="25 17 * * *", depends_on="kline_refresh")
        fire_time = datetime(2026, 11, 11, 17, 25)
        sched._should_run(t, fire_time)  # cron 命中但 dep 未满足 → pending
        assert 1 in sched._pending_retry
        # 后续 tick（cron 不命中 18:30）dep 满足 → 补 fire
        monkeypatch.setattr(CronScheduler, "_deps_satisfied", lambda self, deps: True)
        later = datetime(2026, 11, 11, 18, 30)
        assert sched._should_run(t, later) is True
        assert 1 not in sched._pending_retry

    def test_retry_window_expire_no_fire(self, sched, dep_unsatisfied):
        """窗口过期 → False + 清 pending。"""
        t = _task(id=1, cron_expr="25 17 * * *", depends_on="kline_refresh")
        fire_time = datetime(2026, 11, 11, 17, 25)
        sched._should_run(t, fire_time)  # pending
        expired = fire_time + timedelta(seconds=11100 + 60)  # 窗口 + 1min
        assert sched._should_run(t, expired) is False
        assert 1 not in sched._pending_retry

    def test_no_dep_unaffected(self, sched):
        """无 depends_on → cron_match 行为不变，不进 pending。"""
        t = _task(id=2, cron_expr="25 17 * * *", depends_on=None)
        assert sched._should_run(t, datetime(2026, 11, 11, 17, 25)) is True
        assert sched._should_run(t, datetime(2026, 11, 11, 17, 26)) is False
        assert 2 not in sched._pending_retry

    def test_dep_satisfied_no_pending(self, sched, dep_satisfied):
        """cron 命中 + dep 满足 → True + 不进 pending（正常 fire）。"""
        t = _task(id=3, cron_expr="25 17 * * *", depends_on="kline_refresh")
        assert sched._should_run(t, datetime(2026, 11, 11, 17, 25)) is True
        assert 3 not in sched._pending_retry

    def test_run_task_clears_pending(self, sched, dep_unsatisfied):
        """_run_task 完成后清 _pending_retry（防已 fire 残留）。"""
        t = _task(id=4, cron_expr="25 17 * * *", depends_on="kline_refresh")
        sched._pending_retry[4] = (datetime(2026, 11, 11, 17, 25), "kline_refresh")

        async def fake_exec(task):
            return MagicMock()

        sched._executor.execute_async = fake_exec
        asyncio.run(sched._run_task(t))
        assert 4 not in sched._pending_retry
