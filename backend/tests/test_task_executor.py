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
# S075 新增 first_board_filter（盘后首板流筛选+评分）。
# S084 新增 derived_precompute（盘后 derived 异步预采集）。
# S089 新增 monthly_vacuum（月度 VACUUM + wal_checkpoint）。
# S090 新增 kline_refresh（baostock_kline_cache 日更）。
# S093 新增 daily_ai_summary（AI 盘后总结 stub）。
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
    "first_board_filter",
    "st_play_radar",  # S148 R3：ST-play radar 白名单（摘帽/重组/扭亏 carve-out）
    "s066_validation_checkpoint",
    "evaluation_backtest",  # S151 R3：评价层 30日首次/60日复验检查点
    "forward_test_daily",
    "forward_test_t1_settle",
    "first_board_t1_review",
    "first_board_quote_probe",
    "zt_history_snapshot",
    "derived_precompute",
    "monthly_vacuum",
    "kline_refresh",
    "daily_ai_summary",
    # S101 飞书多点通知
    "premarket_auction_notify",
    "premarket_open_notify",
    "premarket_t1_review",
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
    """S069 R2：T+1 收益回填 executor（temp DB + mock compute_returns）。"""

    def test_settles_non_none_leaves_none_and_stuck_marks_zero(self, tmp_path, monkeypatch):
        """seed NULL 日期 → compute(mock 混合有/无 next_bar) → 记非 None、留 None；
        全 None 的日期标 stuck（不重试）。"""
        import scheduled_tasks as st
        import strategies.forward_test as ft
        from strategies.forward_test import (
            record_daily_recommendations, record_universe_returns, _ensure_table, DailyRecommendation,
        )
        import sqlite3

        db = tmp_path / "ft.db"
        monkeypatch.setattr(ft, "_DB", str(db))
        monkeypatch.setattr("config.GENE_SCORES_DB_PATH", str(db))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-14")
        _ensure_table()
        # 08-13：000001 有 next_bar、000002 缺；08-12：全 None（→ stuck-mark）
        record_daily_recommendations("2026-08-13", [
            DailyRecommendation("2026-08-13", "000001", "A", "first_plate", 70.0),
            DailyRecommendation("2026-08-13", "000002", "B", "first_plate", 75.0),
        ])
        record_daily_recommendations("2026-08-12", [
            DailyRecommendation("2026-08-12", "000003", "C", "first_plate", 70.0),
        ])
        record_universe_returns("2026-08-13", {"000001": {}, "000002": {}})

        def fake_compute(sd, codes, strategy_params_map=None):  # S145: 接 strategy_params_map kwarg
            if sd == "2026-08-13":
                return {"000001": {"return_open2close": 2.5, "return_close2close": 2.0, "next_pctChg": 2.0},
                        "000002": {"return_open2close": None, "return_close2close": None, "next_pctChg": None}}
            return {"000003": {"return_open2close": None, "return_close2close": None, "next_pctChg": None}}
        monkeypatch.setattr("strategies.kline_returns.compute_returns_for_codes", fake_compute)

        r = st._execute_forward_test_t1_settle(None, {})
        conn = sqlite3.connect(str(db))
        n_settled = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE signal_date='2026-08-13' AND return_open2close IS NOT NULL"
        ).fetchone()[0]
        n_null = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE signal_date='2026-08-13' AND return_open2close IS NULL"
        ).fetchone()[0]
        conn.close()
        assert n_settled >= 1 and n_null >= 1  # 000001 settled、000002 留 NULL
        # 08-12 全 None → stuck-mark
        assert r["stuck"] >= 1
        assert any(d["signal_date"] == "2026-08-12" and d["total"] == 0 for d in r["dates_processed"])

    def test_nothing_to_settle(self, monkeypatch, tmp_path):
        """无 NULL<今日 → nothing_to_settle（不调 compute）。"""
        import scheduled_tasks as st
        monkeypatch.setattr("config.GENE_SCORES_DB_PATH", str(tmp_path / "empty.db"))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-14")
        # 建空表（无 NULL 行）
        import strategies.forward_test as ft
        monkeypatch.setattr(ft, "_DB", str(tmp_path / "empty.db"))
        ft._ensure_table()
        called = {"n": 0}
        monkeypatch.setattr("strategies.kline_returns.compute_returns_for_codes",
                            lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {})
        r = st._execute_forward_test_t1_settle(None, {})
        assert r["status"] == "nothing_to_settle"
        assert called["n"] == 0

    def test_stuck_excluded_before_limit_reaches_older_non_stuck(self, tmp_path, monkeypatch):
        """S151 fix：stuck 在 SQL LIMIT 前排除——newest 3 全 stuck 时够着非 stuck 旧日期。

        原 bug：ORDER BY DESC LIMIT 3 取 newest 3（全 stuck）→ post-filter 空 →
        nothing_to_settle，旧 non-stuck 日永不到（forward_test_backfill 重跑后 08-28~09-03
        stuck 卡住 08-17~08-27 non-stuck）。fix：SQL 内 NOT IN stuck 后 LIMIT。
        """
        import scheduled_tasks as st
        import strategies.forward_test as ft
        from strategies.forward_test import (
            record_daily_recommendations, _ensure_table, DailyRecommendation,
        )
        import json

        db = tmp_path / "ft.db"
        monkeypatch.setattr(ft, "_DB", str(db))
        monkeypatch.setattr("config.GENE_SCORES_DB_PATH", str(db))
        monkeypatch.setattr("vr_paths.resolve_data_dir", lambda: str(tmp_path))
        monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-30")
        _ensure_table()
        # 3 newest NULL dates 全 stuck + 1 older non-stuck（08-20）
        for d in ("2026-08-29", "2026-08-28", "2026-08-27", "2026-08-20"):
            record_daily_recommendations(d, [DailyRecommendation(d, "000001", "A", "first_plate", 70.0)])
        stuck = {d: "2026-09-04T15:50:00" for d in ("2026-08-29", "2026-08-28", "2026-08-27")}
        (tmp_path / "t1_stuck_dates.json").write_text(json.dumps(stuck), encoding="utf-8")

        # mock compute 返有 next_bar；record 返 len（不落盘也够验证 dates_processed）
        monkeypatch.setattr("strategies.kline_returns.compute_returns_for_codes",
            lambda sd, codes, strategy_params_map=None:
                {c: {"return_open2close": 1.0, "return_close2close": 1.0, "next_pctChg": 1.0} for c in codes})
        monkeypatch.setattr("strategies.forward_test.record_actual_returns", lambda d, r: len(r))
        monkeypatch.setattr("strategies.forward_test.record_universe_returns", lambda d, r: len(r))

        r = st._execute_forward_test_t1_settle(None, {})
        # 够着 non-stuck 旧日 08-20（非 nothing_to_settle；原 bug 返 nothing_to_settle）
        assert r.get("dates_processed"), f"应处理非 stuck 旧日，got {r}"
        assert any(d["signal_date"] == "2026-08-20" for d in r["dates_processed"])
