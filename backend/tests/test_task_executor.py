# -*- coding: utf-8 -*-
"""TaskExecutor + CronScheduler 任务执行/去重单测（S011-A R2/R4）。

覆盖：
- 内置任务类型已注册（不联网执行；S041 加 daily_backtest_run 共 7 种）。
- execute_async 成功/失败/同步处理器各只产生一条 run 记录（R2：add_run 不重复，
  成功/失败走 update_run 而非二次 add_run）。
- count_running 去重辅助 + CronScheduler._tick 跳过执行中任务（R4 去重）。
- _run_task 完成后清理去重标志。
"""

import asyncio

import pytest

import scheduled_tasks as st
from scheduled_tasks import CronScheduler, ScheduledTask, TaskExecutor, TaskRun


def _run(coro):
    """同步跑协程（项目无 pytest-asyncio，沿用 asyncio.run 约定，见 test_portfolio.py）。"""
    return asyncio.run(coro)


# 内置任务类型（须与 TaskExecutor._executors 保持一致）。
# S041 新增 daily_backtest_run（每日回测快照）。
# S063 新增 sti_post_market（盘后 STI 定时计算）。
# S055 新增 seal_intraday_collect（盘中封单时序采集）。
# S004 新增 candidate_funnel_precompute（盘后漏斗预计算）。
_EXPECTED_TASK_TYPES = {
    "daily_data_refresh",
    "daily_review_notify",
    "limitup_precompute",
    "portfolio_refresh",
    "market_data_sync",
    "cleanup_old_runs",
    "daily_backtest_run",
    "sti_post_market",
    "seal_intraday_collect",
    "candidate_funnel_precompute",
    "s066_validation_checkpoint",
    "forward_test_daily",
    "forward_test_t1_settle",
}


def _make_task(task_type="test_ok", cron_expr="* * * * *", name=None):
    """构造一个不联网的测试任务（关闭通知以免触发 notification 服务副作用）。"""
    return ScheduledTask(
        name=name or ("t-" + task_type),
        task_type=task_type,
        cron_expr=cron_expr,
        payload={},
        notify_on_success=False,
        notify_on_failure=False,
    )


# ---------------------------------------------------------------------------
# 任务类型注册
class TestRegisteredTypes:
    def test_builtin_types_registered(self):
        executor = TaskExecutor()
        assert set(executor._executors) == _EXPECTED_TASK_TYPES

    def test_unknown_type_produces_failed_run(self, isolated_market_db):
        """未知类型不抛出——execute_async 内部捕获并落一条 failed run。"""
        executor = TaskExecutor()
        task = st._manager.create_task(_make_task(task_type="does_not_exist"))
        run = _run(executor.execute_async(task))
        assert run.status == "failed"
        assert "未知任务类型" in (run.error or "")
        # 仍只有一条 run（R2）
        assert len(st._manager.list_runs(task.id)) == 1


# ---------------------------------------------------------------------------
# add_run 不重复（R2）
class TestAddRunNoDuplicate:
    def test_success_single_run(self, isolated_market_db):
        executor = TaskExecutor()
        seen = []

        async def ok_handler(payload):
            seen.append(1)
            return {"ok": True}

        executor._executors["test_ok"] = ok_handler
        task = st._manager.create_task(_make_task("test_ok"))
        run = _run(executor.execute_async(task))

        assert run.status == "success"
        assert run.id is not None
        assert run.finished_at is not None
        assert seen == [1]

        runs = st._manager.list_runs(task.id)
        assert len(runs) == 1, "R2: 成功不应产生第二条 running 记录"
        assert runs[0].status == "success"
        assert runs[0].error is None

    def test_failure_single_run(self, isolated_market_db):
        executor = TaskExecutor()

        async def boom_handler(payload):
            raise RuntimeError("boom")

        executor._executors["test_boom"] = boom_handler
        task = st._manager.create_task(_make_task("test_boom"))
        run = _run(executor.execute_async(task))

        assert run.status == "failed"
        assert "boom" in (run.error or "")

        runs = st._manager.list_runs(task.id)
        assert len(runs) == 1, "R2: 失败也不应产生第二条 running 记录"
        assert runs[0].status == "failed"
        assert runs[0].error is not None

    def test_sync_handler_via_to_thread_single_run(self, isolated_market_db):
        """同步处理器经 asyncio.to_thread 执行，仍只一条 run。"""
        executor = TaskExecutor()

        def sync_handler(payload):
            return {"sync": True}

        executor._executors["test_sync"] = sync_handler
        task = st._manager.create_task(_make_task("test_sync"))
        run = _run(executor.execute_async(task))

        assert run.status == "success"
        assert run.result == {"sync": True}
        assert len(st._manager.list_runs(task.id)) == 1

    def test_task_status_updated_on_success(self, isolated_market_db):
        """成功后 scheduled_tasks.last_run_status 应被更新。"""
        executor = TaskExecutor()

        async def ok(payload):
            return {"ok": True}

        executor._executors["test_ok"] = ok
        task = st._manager.create_task(_make_task("test_ok"))
        _run(executor.execute_async(task))

        refreshed = st._manager.get_task(task.id)
        assert refreshed.last_run_status == "success"
        assert refreshed.last_run_at is not None


# ---------------------------------------------------------------------------
# 去重（R4）
class TestDedup:
    def test_count_running_only_counts_running(self, isolated_market_db):
        task = st._manager.create_task(_make_task())
        st._manager.add_run(TaskRun(task_id=task.id, status="running"))
        assert st._manager.count_running(task.id) == 1

        # 非 running 的不计入
        st._manager.add_run(TaskRun(task_id=task.id, status="success"))
        assert st._manager.count_running(task.id) == 1

        # 再加一个 running
        st._manager.add_run(TaskRun(task_id=task.id, status="running"))
        assert st._manager.count_running(task.id) == 2

    def test_run_task_clears_running_flag(self, isolated_market_db):
        """_run_task 完成后必须从 _running_task_ids 移除。"""
        executor = TaskExecutor()

        async def ok(payload):
            return {"ok": True}

        executor._executors["test_ok"] = ok
        sched = CronScheduler(executor=executor)
        task = st._manager.create_task(_make_task("test_ok"))

        assert task.id not in sched._running_task_ids
        _run(sched._run_task(task))
        # 完成后标志已清理
        assert task.id not in sched._running_task_ids

    def test_tick_skips_running_task(self, isolated_market_db):
        """_tick 中，id 已在 _running_task_ids 的任务不重复触发。"""
        executor = TaskExecutor()
        calls = []

        async def slow(payload):
            calls.append("ran")
            return {"ok": True}

        executor._executors["test_ok"] = slow
        sched = CronScheduler(executor=executor)
        task = st._manager.create_task(_make_task("test_ok", cron_expr="* * * * *"))

        # 模拟该任务正在执行 → _tick 必须跳过（不 spawn _run_task）
        sched._running_task_ids.add(task.id)
        _run(sched._tick())
        assert calls == [], "R4: 执行中任务不应被重复触发"

        # 释放后直接 _run_task 应能执行（验证 handler 本身可用）
        sched._running_task_ids.discard(task.id)
        _run(sched._run_task(task))
        assert calls == ["ran"]

    def test_tick_triggers_when_not_running(self, isolated_market_db):
        """_tick 中，非执行中且 cron 命中的任务应被触发（fire-and-forget task）。"""
        executor = TaskExecutor()
        done = asyncio.Event()
        call_count = {"n": 0}

        async def ok(payload):
            call_count["n"] += 1
            done.set()
            return {"ok": True}

        executor._executors["test_ok"] = ok
        sched = CronScheduler(executor=executor)
        task = st._manager.create_task(_make_task("test_ok", cron_expr="* * * * *"))

        async def _drive():
            await sched._tick()
            # _tick 用 asyncio.create_task spawn _run_task，等它落地
            try:
                await asyncio.wait_for(done.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

        _run(_drive())
        assert call_count["n"] == 1, "非执行中且 cron 命中应触发一次"


# ---------------------------------------------------------------------------
# _loop 生产路径生命周期（硬阻回归：asyncio.run 每 tick 关循环取消 spawn 任务）
class TestLoopLifecycle:
    def test_loop_completes_fire_and_forget_task(self, isolated_market_db, monkeypatch):
        """生产路径：主循环 ticker 内，_tick spawn 的任务能跑完并落一条终态 run（S032 R6）。"""
        import scheduled_tasks as st
        monkeypatch.setattr(st, "_TICK_INTERVAL", 0.05)   # 缩短心跳
        executor = st.TaskExecutor()
        release = {"go": False}
        calls = {"n": 0}

        async def ok(payload):
            calls["n"] += 1
            # 轮询等放行：期间任务保持 running，验证后续 tick 被 R4 去重跳过
            while not release["go"]:
                await asyncio.sleep(0.01)
            # 结束心跳：_running 置 False + cancel ticker，杜绝放行后重放
            await sched.stop()
            return {"ok": True}

        executor._executors["test_ok"] = ok
        sched = st.CronScheduler(executor=executor)
        task = st._manager.create_task(_make_task("test_ok", cron_expr="* * * * *"))

        async def scenario():
            await sched.start()  # 主循环 ticker（S032 R6，无线程）
            loop = asyncio.get_running_loop()
            # 等 handler 真正执行
            deadline = loop.time() + 5.0
            while loop.time() < deadline and calls["n"] == 0:
                await asyncio.sleep(0.02)
            assert calls["n"] == 1, "任务应被心跳触发执行一次"
            # 再等几个心跳窗口，验证任务执行期间不被重复触发（R4 去重）
            await asyncio.sleep(0.2)
            assert calls["n"] == 1, "任务执行期间不应被重复触发"
            release["go"] = True  # 放行 handler → execute_async 收尾 update_run
            # 等 fire-and-forget 任务跑完（生产 stop 不等待，测试需终态 run）
            deadline = loop.time() + 5.0
            while loop.time() < deadline and sched._spawned:
                await asyncio.sleep(0.02)

        _run(scenario())

        assert calls["n"] == 1, "任务应恰好执行一次"
        runs = st._manager.list_runs(task.id)
        assert len(runs) == 1, "全程应只落一条 run 记录"
        assert runs[0].status == "success", "run 终态应为 success（不被取消卡 running）"
        assert runs[0].finished_at is not None
        refreshed = st._manager.get_task(task.id)
        assert refreshed.last_run_status == "success"

    def test_start_rebuilds_running_ids_from_db(self, isolated_market_db):
        """重启恢复：DB 已有 running 行 → await start() 后 _running_task_ids 含该任务 id。"""
        import scheduled_tasks as st
        task = st._manager.create_task(_make_task())
        st._manager.add_run(st.TaskRun(task_id=task.id, status="running"))
        sched = st.CronScheduler()

        async def scenario():
            await sched.start()
            try:
                assert task.id in sched._running_task_ids, "启动时应从 DB 重建 running 集合"
            finally:
                await sched.stop()

        _run(scenario())

    def test_tick_within_loop_not_cancelled(self, isolated_market_db, monkeypatch):
        """直接在长生命周期 loop 里跑 _tick，spawn 的任务不被取消。"""
        import scheduled_tasks as st
        executor = st.TaskExecutor()
        finished = asyncio.Event()

        async def ok(payload):
            finished.set()
            return {"ok": True}

        executor._executors["test_ok"] = ok
        sched = st.CronScheduler(executor=executor)
        task = st._manager.create_task(_make_task("test_ok", cron_expr="* * * * *"))

        async def drive():
            await sched._tick()                      # spawn _run_task（fire-and-forget）
            await asyncio.wait_for(finished.wait(), timeout=3.0)
            await asyncio.sleep(0.2)                 # 让 update_run 落地
            sched._running_task_ids.discard(task.id) # 清理，避免影响断言

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(drive())
        finally:
            loop.close()

        runs = st._manager.list_runs(task.id)
        assert len(runs) == 1 and runs[0].status == "success"


# ---------------------------------------------------------------------------
# §44 60 天复验检查点（提醒任务）
# ---------------------------------------------------------------------------
class _FakeConn:
    """假 conn：execute 返预设 count。"""
    def __init__(self, count):
        self._count = count

    def execute(self, q, *a):
        class _R:
            def fetchone(_self):
                return (self._count,)
        return _R()

    def close(self):
        pass


class TestS066ValidationCheckpoint:
    """§44 60 天复验检查点 executor（spec §13 ①/§44）。"""

    def test_not_due(self, monkeypatch):
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn(31))
        r = st._execute_s066_validation_checkpoint(None, {"threshold": 60})
        assert r["status"] == "not_due"
        assert r["eastmoney_live_days"] == 31
        assert r["target"] == 60

    def test_due_writes_checkpoint(self, monkeypatch, tmp_path):
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn(65))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path), raising=False)
        r = st._execute_s066_validation_checkpoint(None, {"threshold": 60})
        assert r["status"] == "due"
        assert r["eastmoney_live_days"] == 65
        assert "backfill" in r["action"]
        assert (tmp_path / "s066_60day_due.json").exists()


class TestForwardTestDaily:
    """S069 R1：每日 forward_test picks+universe 记录 executor。"""

    def test_wires_weather_and_shape(self, monkeypatch):
        """executor 接 build_context weather + run_daily_forward_test，返 picks/universe 形状；weather 透传。"""
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-14")
        monkeypatch.setattr("sentiment_context.build_context",
                            lambda d: type("Ctx", (), {"weather_state": "晴天"})())
        calls = {}

        def fake_run(date, weather_state=None):
            calls["date"] = date
            calls["weather"] = weather_state
            return {"recommendations": 20, "universe_codes": 59}

        monkeypatch.setattr("strategies.forward_test.run_daily_forward_test", fake_run)
        r = st._execute_forward_test_daily(None, {})
        assert r["signal_date"] == "2026-08-14"
        assert r["weather"] == "晴天"
        assert r["picks"] == 20 and r["universe_codes"] == 59
        assert calls["weather"] == "晴天"  # weather 透传给 run_daily_forward_test

    def test_build_context_failure_falls_back_to_none_weather(self, monkeypatch):
        """build_context 异常 → weather=None（不阻断 picks 记录）。"""
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-14")

        def boom(d):
            raise RuntimeError("sti unavailable")

        monkeypatch.setattr("sentiment_context.build_context", boom)
        monkeypatch.setattr("strategies.forward_test.run_daily_forward_test",
                            lambda date, weather_state=None: {"recommendations": 5, "universe_codes": 10})
        r = st._execute_forward_test_daily(None, {})
        assert r["weather"] is None
        assert r["picks"] == 5  # 仍记 picks（weather=None 退化下界）


class TestForwardTestT1Settle:
    """S069 R2：T+1 收益回填 executor。"""

    def test_finds_null_signal_date_and_records_non_none_returns(self, monkeypatch):
        """找最新 NULL signal_date<今日 → compute_returns → 仅记非 None 的（缺 next_bar 留 NULL）。"""
        import scheduled_tasks as st

        # 假 conn：signal_date 查询 + codes 查询
        class _FakeConn:
            def execute(self, q, *a):
                class _R:
                    def fetchone(_s):
                        return ("2026-08-13",)  # 最新 NULL signal_date
                    def fetchall(_s):
                        return [("000001",), ("000002",), ("000003",)]  # 3 codes
                return _R()
            def close(self): pass
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn())
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-14")

        # compute_returns：000001 有 next_bar，000002 缺（None），000003 有
        monkeypatch.setattr("strategies.kline_returns.compute_returns_for_codes",
                            lambda sd, codes: {
                                "000001": {"return_open2close": 2.5, "return_close2close": 2.0, "next_pctChg": 2.0},
                                "000002": {"return_open2close": None, "return_close2close": None, "next_pctChg": None},
                                "000003": {"return_open2close": -1.0, "return_close2close": -0.5, "next_pctChg": -0.5},
                            })
        recorded_picks = {}
        recorded_uni = {}
        monkeypatch.setattr("strategies.forward_test.record_actual_returns",
                            lambda sd, r: recorded_picks.update(r) or len(r))
        monkeypatch.setattr("strategies.forward_test.record_universe_returns",
                            lambda sd, r: recorded_uni.update(r) or len(r))

        r = st._execute_forward_test_t1_settle(None, {})
        assert r["signal_date"] == "2026-08-13"
        # 仅非 None 的被记（000001 + 000003），000002 缺 next_bar 留 NULL 不记
        assert set(recorded_picks.keys()) == {"000001", "000003"}
        assert set(recorded_uni.keys()) == {"000001", "000003"}

    def test_nothing_to_settle_when_no_null(self, monkeypatch):
        """无 NULL signal_date<今日 → nothing_to_settle（不调 compute）。"""
        import scheduled_tasks as st

        class _FakeConn:
            def execute(self, q, *a):
                class _R:
                    def fetchone(_s):
                        return None  # 无 NULL signal_date
                return _R()
            def close(self): pass
        monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: _FakeConn())
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-14")
        called = {"n": 0}
        monkeypatch.setattr("strategies.kline_returns.compute_returns_for_codes",
                            lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {})

        r = st._execute_forward_test_t1_settle(None, {})
        assert r["status"] == "nothing_to_settle"
        assert called["n"] == 0  # 未调 compute
