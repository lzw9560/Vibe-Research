# -*- coding: utf-8 -*-
"""S032：调度收口第二轮单测。

覆盖：
- R10 状态落库：workflow_state_repo（幂等/不回退/合法非法流转/history）
- R10 盘前接线：run() 落 candidate/filtered + 落库失败不阻塞主流程
- R10 端点：GET /api/workflow/state、POST transition、GET history
- R6 调度主循环：CronScheduler async start/stop + ticker 挂主循环触发任务
- R6.4+R8 portfolio：_refresh_once 异常日志不吞 + _refresh_loop 主循环存活
"""
from __future__ import annotations

import asyncio
import logging

import pytest


# ---------------------------------------------------------------------------
# R10.1/R10.2：workflow_state_repo
# ---------------------------------------------------------------------------


def test_repo_tables_wal(isolated_market_db):
    """建表后 journal_mode=wal；两表存在。"""
    import workflow_state_repo as wsr

    conn = wsr._get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "workflow_state" in tables
        assert "workflow_state_history" in tables
    finally:
        conn.close()


def test_ensure_candidate_insert_if_absent(isolated_market_db):
    """同日重复 ensure 不重复建行；不覆盖已进阶状态。"""
    import workflow_state_repo as wsr

    assert wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "基因达标") is True
    assert wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "基因达标") is False  # 已存在
    # 用户已推进到 watching 后，盘前重跑不得回退
    ok, _ = wsr.transition("600001", "2026-08-07", "watching", "手动观察")
    assert ok is True
    assert wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "基因达标") is False
    state = wsr.get_state("600001", "2026-08-07")
    assert state["status"] == "watching"


def test_ensure_filtered(isolated_market_db):
    import workflow_state_repo as wsr

    assert wsr.ensure_filtered("600002", "测试乙", "2026-08-07", "基因得分未达标") is True
    state = wsr.get_state("600002", "2026-08-07")
    assert state["status"] == "filtered"
    assert state["reason"] == "基因得分未达标"


def test_transition_legal_chain_and_history(isolated_market_db):
    """candidate→watching→monitoring→holding→settled 全链合法 + history 逐条留痕。"""
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600003", "测试丙", "2026-08-07", "")
    for target in ("watching", "monitoring", "holding", "settled"):
        ok, _ = wsr.transition("600003", "2026-08-07", target, f"->{target}")
        assert ok is True, target

    history = wsr.get_history("600003", "2026-08-07")
    # 初始 pending→candidate + 4 次手动流转 = 5 条
    assert len(history) == 5
    assert history[0]["from_status"] == "pending"
    assert history[0]["to_status"] == "candidate"
    assert [h["to_status"] for h in history[1:]] == ["watching", "monitoring", "holding", "settled"]


def test_transition_illegal_rejected(isolated_market_db):
    """candidate 直接跳 holding 非法 → 返回 False + 状态不变。"""
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600004", "测试丁", "2026-08-07", "")
    ok, detail = wsr.transition("600004", "2026-08-07", "holding", "跳级")
    assert ok is False
    assert "candidate" in detail  # 说明里带当前态
    assert wsr.get_state("600004", "2026-08-07")["status"] == "candidate"


def test_transition_unknown_state_and_missing_row(isolated_market_db):
    import workflow_state_repo as wsr

    ok, detail = wsr.transition("600005", "2026-08-07", "bogus_state", "")
    assert ok is False
    ok, detail = wsr.transition("699999", "2026-08-07", "watching", "")
    assert ok is False  # 无记录


def test_list_states_by_date(isolated_market_db):
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "甲", "2026-08-07", "")
    wsr.ensure_candidate("600002", "乙", "2026-08-07", "")
    wsr.ensure_filtered("600003", "丙", "2026-08-07", "未达标")
    wsr.ensure_candidate("600001", "甲", "2026-08-06", "")

    rows = wsr.list_states("2026-08-07")
    assert len(rows) == 3
    statuses = {r["status"] for r in rows}
    assert statuses == {"candidate", "filtered"}


# ---------------------------------------------------------------------------
# R10.3：PreMarketWorkflow.run() 接线
# ---------------------------------------------------------------------------


def _fake_screener_result(qualified_codes=("600001",), filtered_codes=("600009",)):
    """构造最小 ScreenerResult 替身（只含 run() 用到的字段）。"""
    from types import SimpleNamespace

    qualified = [SimpleNamespace(code=c, name=f"股{c}", total_score=80.0) for c in qualified_codes]
    all_scores = qualified + [SimpleNamespace(code=c, name=f"股{c}", total_score=30.0) for c in filtered_codes]
    return SimpleNamespace(date="2026-08-07", qualified=qualified, high_gene=[], gene_scores=all_scores)


def test_run_persists_candidate_and_filtered(isolated_market_db, monkeypatch):
    """run() 后：qualified→candidate 行、filtered_out→filtered 行。"""
    import pre_market_workflow as pmw
    import workflow_state_repo as wsr

    fake = _fake_screener_result()
    monkeypatch.setattr(pmw, "get_screener_result", _async_result(fake))
    monkeypatch.setattr(pmw.StrategyMatcher, "match", lambda self, s, weather_state=None: [])
    monkeypatch.setattr(pmw.PositionAdvisor, "advise_batch", lambda self, sigs, weather_state=None: [])

    report = asyncio.run(pmw.PreMarketWorkflow("2026-08-07").run())
    assert len(report.candidates) == 1

    assert wsr.get_state("600001", "2026-08-07")["status"] == "candidate"
    assert wsr.get_state("600009", "2026-08-07")["status"] == "filtered"


def test_run_survives_state_persistence_failure(isolated_market_db, monkeypatch, caplog):
    """落库抛异常时 run() 仍正常返回 report（隔离）。"""
    import pre_market_workflow as pmw

    fake = _fake_screener_result()
    monkeypatch.setattr(pmw, "get_screener_result", _async_result(fake))
    monkeypatch.setattr(pmw.StrategyMatcher, "match", lambda self, s, weather_state=None: [])
    monkeypatch.setattr(pmw.PositionAdvisor, "advise_batch", lambda self, sigs, weather_state=None: [])

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("workflow_state_repo.ensure_candidate", boom)

    with caplog.at_level(logging.WARNING):
        report = asyncio.run(pmw.PreMarketWorkflow("2026-08-07").run())
    assert len(report.candidates) == 1  # 主流程不受影响
    assert any("状态落库" in r.getMessage() for r in caplog.records)


def _async_result(value):
    async def _fake(*args, **kwargs):
        return value
    return _fake


# ---------------------------------------------------------------------------
# R10.4：端点
# ---------------------------------------------------------------------------


def test_state_endpoints(isolated_market_db, monkeypatch):
    """GET state / POST transition / GET history 三端点冒烟。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "基因达标")

    client = TestClient(appmod.app)

    r = client.get("/api/workflow/state", params={"date": "2026-08-07"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["date"] == "2026-08-07"
    assert body["data"]["states"][0]["code"] == "600001"

    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "watching", "reason": "手动观察"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "watching"

    # 非法流转 → 400 + 当前态/允许目标
    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "settled", "reason": "跳级"})
    assert r.status_code == 400
    assert "allowed_targets" in r.json()["detail"]

    r = client.get("/api/workflow/state/600001/history", params={"date": "2026-08-07"})
    assert r.status_code == 200
    history = r.json()["data"]["history"]
    assert [h["to_status"] for h in history] == ["candidate", "watching"]


# ---------------------------------------------------------------------------
# R6：CronScheduler async start/stop + 主循环触发
# ---------------------------------------------------------------------------


def test_scheduler_start_stop_on_main_loop(isolated_market_db, monkeypatch):
    """async start 在主循环建 ticker task；stop cancel 生效、无线程。"""
    import scheduled_tasks as st

    monkeypatch.setattr(st, "_TICK_INTERVAL", 0.01)
    sched = st.CronScheduler()

    async def scenario():
        await sched.start()
        assert sched._task is not None and not sched._task.done()
        await asyncio.sleep(0.05)
        await sched.stop()
        assert sched._running is False
        assert sched._task is None

    asyncio.run(scenario())
    assert not hasattr(sched, "_thread") or getattr(sched, "_thread", None) is None


def test_scheduler_tick_fires_task_on_main_loop(isolated_market_db, monkeypatch):
    """ticker 挂主循环后，cron 命中的任务经 execute_async 真实触发。"""
    import scheduled_tasks as st
    from scheduled_tasks import ScheduledTask

    monkeypatch.setattr(st, "_TICK_INTERVAL", 0.01)
    sched = st.CronScheduler()

    fired: list[int] = []

    async def fake_execute_async(task):
        fired.append(task.id)
        from scheduled_tasks import TaskRun
        return TaskRun(task_id=task.id or 0, status="success")

    monkeypatch.setattr(sched._executor, "execute_async", fake_execute_async)
    monkeypatch.setattr(st._manager, "list_tasks", lambda: [
        ScheduledTask(id=11, name="t", task_type="x", cron_expr="* * * * *", enabled=True)])

    async def scenario():
        await sched.start()
        await asyncio.sleep(0.05)  # ≥1 tick
        await sched.stop()

    asyncio.run(scenario())
    assert fired, "cron 命中任务应被触发"
    assert 11 in fired


# ---------------------------------------------------------------------------
# R6.4 + R8：portfolio 主循环刷新 + 异常日志
# ---------------------------------------------------------------------------


def test_refresh_once_logs_exception(monkeypatch, caplog):
    """R8：刷新异常 → warning 日志，不向上抛。"""
    import portfolio as pf

    async def boom():
        raise RuntimeError("refresh boom")

    monkeypatch.setattr(pf, "_refresh_snapshot", boom)
    with caplog.at_level(logging.WARNING, logger="vibe-research"):
        asyncio.run(pf._refresh_once())  # 不得抛
    assert any("refresh boom" in r.getMessage() for r in caplog.records)


def test_refresh_loop_survives_and_ticks(monkeypatch):
    """R6.4：_refresh_loop 挂主循环持续 tick（异常存活契约由 _refresh_once 保证，见上测）。"""
    import portfolio as pf

    ticks = {"n": 0}

    async def counting_refresh():
        ticks["n"] += 1

    monkeypatch.setattr(pf, "_refresh_once", counting_refresh)

    async def scenario():
        task = asyncio.get_running_loop().create_task(pf._refresh_loop(0.01))
        await asyncio.sleep(0.05)  # 多 tick
        assert not task.done(), "异常后循环不得终止"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert ticks["n"] >= 2


def test_portfolio_no_threading_left():
    """R6.4：portfolio 不再持有线程/Event（_portfolio_stop 移除）。"""
    import portfolio as pf

    assert not hasattr(pf, "_portfolio_stop")
    import inspect
    assert inspect.iscoroutinefunction(pf.start_scheduler)
