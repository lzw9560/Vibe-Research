# -*- coding: utf-8 -*-
"""S092 T3：scheduled-tasks today_status 后端推算单测。

覆盖 today_status 推算逻辑（R18，后端算不前端算）：
1. 昨天 success → pending（非今日）
2. 今天 success → done
3. 今天 failed → error
4. running → running（不管日期）
5. null last_run_at → pending

mock 惯例跟随 test_s031_scheduled_tasks.py：monkeypatch st._manager 的 list_tasks/get_task，
构造 ScheduledTask dataclass 对象。last_run_at 用相对于真实今天（北京时间）的 ISO 串，
不 mock datetime.now，保证测试稳定。
"""
from datetime import datetime, timedelta

import pytest

import scheduled_tasks as st
from scheduled_tasks import ScheduledTask
from vr_paths import BEIJING_TZ

from routers import scheduled_tasks as router_mod


def _today_bj_iso() -> str:
    """今天北京日期的 naive ISO 串（与生产 last_run_at 格式一致：无时区后缀）。"""
    return datetime.now(BEIJING_TZ).date().isoformat() + "T15:30:00"


def _yesterday_bj_iso() -> str:
    return (datetime.now(BEIJING_TZ).date() - timedelta(days=1)).isoformat() + "T15:30:00"


def _make_task(
    last_run_at: str | None,
    last_run_status: str | None,
    *,
    id_: int = 1,
    name: str = "test_task",
) -> ScheduledTask:
    """构造完整 ScheduledTask dataclass（属性齐全，匹配 router 返回字段）。"""
    return ScheduledTask(
        id=id_,
        name=name,
        description="",
        task_type="daily_data_refresh",
        cron_expr="0 15 * * 0-4",
        payload={},
        enabled=True,
        notify_on_success=False,
        notify_on_failure=True,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


# ---------------------------------------------------------------------------
# list_scheduled_tasks：today_status 推算五场景
class TestListTodayStatus:
    @pytest.mark.parametrize("status_iso,expected", [
        ("yesterday_success", "pending"),
        ("today_success", "done"),
        ("today_failed", "error"),
        ("running_any_date", "running"),
        ("null_last_run", "pending"),
    ])
    def test_today_status_branches(self, monkeypatch, status_iso, expected):
        """五场景一次性参数化：覆盖 today_status 四值 + pending 两来源。"""
        today = _today_bj_iso()
        yesterday = _yesterday_bj_iso()

        if status_iso == "yesterday_success":
            task = _make_task(yesterday, "success")
        elif status_iso == "today_success":
            task = _make_task(today, "success")
        elif status_iso == "today_failed":
            task = _make_task(today, "failed")
        elif status_iso == "running_any_date":
            # running 不管日期（这里用昨天验证日期不影响 running）
            task = _make_task(yesterday, "running")
        elif status_iso == "null_last_run":
            task = _make_task(None, None)
        else:
            raise AssertionError(status_iso)

        monkeypatch.setattr(st._manager, "list_tasks", lambda: [task])

        result = asyncio_run(router_mod.list_scheduled_tasks())

        assert result["data"][0]["today_status"] == expected
        # 顺便验证其他字段仍存在（不被 today_status 引入破坏）
        assert result["data"][0]["id"] == 1
        assert result["data"][0]["last_run_at"] == task.last_run_at
        assert result["data"][0]["last_run_status"] == task.last_run_status

    def test_running_with_today_date_still_running(self, monkeypatch):
        """running 状态即使 last_run_at 是今天，也返 running（不因日期改判 done）。"""
        task = _make_task(_today_bj_iso(), "running")
        monkeypatch.setattr(st._manager, "list_tasks", lambda: [task])
        result = asyncio_run(router_mod.list_scheduled_tasks())
        assert result["data"][0]["today_status"] == "running"

    def test_multiple_tasks_mixed_status(self, monkeypatch):
        """多任务混合：验证每个任务 today_status 独立推算，不互相串。"""
        today = _today_bj_iso()
        yesterday = _yesterday_bj_iso()
        tasks = [
            _make_task(today, "success", id_=1, name="done_today"),
            _make_task(yesterday, "success", id_=2, name="pending_yest"),
            _make_task(today, "failed", id_=3, name="error_today"),
            _make_task(yesterday, "running", id_=4, name="running"),
            _make_task(None, None, id_=5, name="never_run"),
        ]
        monkeypatch.setattr(st._manager, "list_tasks", lambda: tasks)
        result = asyncio_run(router_mod.list_scheduled_tasks())
        statuses = [item["today_status"] for item in result["data"]]
        assert statuses == ["done", "pending", "error", "running", "pending"]


# ---------------------------------------------------------------------------
# get_scheduled_task：单个任务详情同样带 today_status
class TestGetTodayStatus:
    def test_today_success_returns_done(self, monkeypatch):
        today = _today_bj_iso()
        task = _make_task(today, "success")
        monkeypatch.setattr(st._manager, "get_task", lambda tid: task)
        result = asyncio_run(router_mod.get_scheduled_task(1))
        assert result["data"]["today_status"] == "done"
        assert result["data"]["id"] == 1

    def test_null_last_run_returns_pending(self, monkeypatch):
        task = _make_task(None, None)
        monkeypatch.setattr(st._manager, "get_task", lambda tid: task)
        result = asyncio_run(router_mod.get_scheduled_task(1))
        assert result["data"]["today_status"] == "pending"

    def test_get_task_not_found_raises_404(self, monkeypatch):
        """get_task 返回 None 时仍抛 404（today_status 引入不破坏原契约）。"""
        from fastapi import HTTPException

        monkeypatch.setattr(st._manager, "get_task", lambda tid: None)
        with pytest.raises(HTTPException) as exc_info:
            asyncio_run(router_mod.get_scheduled_task(999))
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 辅助：跑 async router 函数（项目无 async fixture 依赖时用 asyncio.run）
def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
