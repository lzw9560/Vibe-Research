# -*- coding: utf-8 -*-
"""S031 T8：A 节调度收口单测。

覆盖：
- R3 WAL+busy_timeout（test_wal_pragma）
- R13 seed 幂等（test_seed_idempotent）
- R9 _tick 统一 BEIJING_TZ（test_tick_beijing_tz）
- R5 lifespan 优雅启停（test_lifespan_shutdown）
"""

import asyncio

import pytest

import scheduled_tasks as st
from scheduled_tasks import ScheduledTask


# ---------------------------------------------------------------------------
# R3：SQLite WAL + busy_timeout
def test_wal_pragma(isolated_market_db):
    """_ensure_tables 后 journal_mode=wal、busy_timeout=30000。"""
    conn = st._get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# R13：seed 默认任务幂等
def test_seed_idempotent(isolated_market_db):
    """_ensure_seed_tasks 调两次只建一行 limitup_precompute，cron 30 15 * * 0-4。"""
    st._ensure_seed_tasks()
    st._ensure_seed_tasks()
    tasks = [t for t in st._manager.list_tasks() if t.name == "limitup_precompute"]
    assert len(tasks) == 1
    assert tasks[0].cron_expr == "30 15 * * 0-4"  # 0=周一约定下工作日=Mon-Fri
    assert tasks[0].task_type == "limitup_precompute"
    assert tasks[0].payload == {"back_days": 3}
    assert tasks[0].enabled is True


# ---------------------------------------------------------------------------
# R9：_tick 的 now 带 BEIJING_TZ
def test_tick_beijing_tz(cron_scheduler, monkeypatch):
    """_tick 传给 cron_match 的 now 带 Asia/Shanghai tzinfo。"""
    from limitup_screener import BEIJING_TZ

    monkeypatch.setattr(st._manager, "list_tasks", lambda: [
        ScheduledTask(id=1, name="t", task_type="x", cron_expr="* * * * *", enabled=True)
    ])
    captured = []
    monkeypatch.setattr(st, "cron_match", lambda expr, dt: captured.append(dt) or False)
    asyncio.run(cron_scheduler._tick())
    assert captured, "cron_match 应被调用"
    assert captured[0].tzinfo == BEIJING_TZ


# ---------------------------------------------------------------------------
# R5：lifespan 优雅启停（mock 重启动作，只验 stop()+_portfolio_stop.set() 被调）
def test_lifespan_shutdown(monkeypatch):
    """lifespan：startup 调 start_scheduler+portfolio；shutdown 调 stop+set。"""
    import app as appmod

    calls: list[str] = []

    class FakeSched:
        def stop(self):
            calls.append("sched.stop")

    monkeypatch.setattr(appmod._st, "start_scheduler", lambda: calls.append("st.start_scheduler"))
    monkeypatch.setattr(appmod._st, "get_scheduler", lambda: FakeSched())
    monkeypatch.setattr(appmod.pf, "start_scheduler", lambda interval=1800: calls.append("pf.start_scheduler"))
    appmod.pf._portfolio_stop.clear()

    async def run():
        async with appmod.lifespan(appmod.app):
            assert "st.start_scheduler" in calls
            assert "pf.start_scheduler" in calls
            assert appmod.pf._portfolio_stop.is_set() is False

    asyncio.run(run())
    assert "sched.stop" in calls
    assert appmod.pf._portfolio_stop.is_set() is True
