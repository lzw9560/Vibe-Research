# -*- coding: utf-8 -*-
"""S041：回测趋势看板单测（快照表 + trend 端点 + 幂等写入）。

复用 S031 的 isolated_market_db（重定向 scheduled_tasks._DB_PATH 到 tmp 库），
不碰真实 backend/data/market_data.db。
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# A1：快照表 DDL + 幂等写入
# ---------------------------------------------------------------------------


def test_snapshot_table_created(isolated_market_db):
    """_ensure_tables 后 backtest_daily_snapshots 表 + UNIQUE(snapshot_date, engine) 存在。"""
    import scheduled_tasks as st

    conn = st._get_connection()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(backtest_daily_snapshots)").fetchall()}
        for c in (
            "id", "snapshot_date", "engine", "hit_rate", "avg_return",
            "max_drawdown", "sharpe_ratio", "total_signals",
            "percentile_json", "strategy_breakdown_json", "created_at",
        ):
            assert c in cols, f"缺列 {c}"
        # UNIQUE 约束存在
        idxs = conn.execute("PRAGMA index_list(backtest_daily_snapshots)").fetchall()
        # sqlite_autoindex_* 体现 UNIQUE 约束；schema 里也有显式 idx_backtest_snapshots_date
        assert any(i["unique"] for i in idxs), "应有 UNIQUE 约束（snapshot_date+engine）"
    finally:
        conn.close()


def _lite_result():
    """构造一个最小 BacktestResult-like 对象（免跑真实回测）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        hit_rate=0.65,
        avg_return=2.3,
        max_drawdown=-5.1,
        sharpe_ratio=1.2,
        total_signals=42,
        percentile_analysis={"p50": 2.0, "p90": 8.5},
    )


def _strat_results():
    """构造一个 list[StrategyBacktestResult-like]。"""
    from types import SimpleNamespace

    return [
        SimpleNamespace(
            strategy_code="limit_up_breakout", strategy_name="涨停突破",
            win_rate=0.55, avg_return=3.2, sample_size=10, available_days=20, skipped=1,
        ),
        SimpleNamespace(
            strategy_code="low_volume_pullback", strategy_name="缩量回踩",
            win_rate=0.48, avg_return=1.8, sample_size=8, available_days=20, skipped=0,
        ),
    ]


def test_save_snapshot_lite_and_strategy(isolated_market_db):
    """lite + strategy 各写一行 → 字段正确落库。"""
    import scheduled_tasks as st

    st._save_snapshot("2026-08-08", "lite", _lite_result())
    st._save_snapshot("2026-08-08", "strategy", _strat_results())

    conn = st._get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM backtest_daily_snapshots ORDER BY engine"
        ).fetchall()
        assert len(rows) == 2

        lite = dict(rows[0])
        assert lite["engine"] == "lite"
        assert lite["hit_rate"] == 0.65
        assert lite["avg_return"] == 2.3
        assert lite["max_drawdown"] == -5.1
        assert lite["sharpe_ratio"] == 1.2
        assert lite["total_signals"] == 42
        assert json.loads(lite["percentile_json"]) == {"p50": 2.0, "p90": 8.5}
        assert lite["strategy_breakdown_json"] is None

        strat = dict(rows[1])
        assert strat["engine"] == "strategy"
        assert strat["hit_rate"] is None  # strategy 行不填这些
        breakdown = json.loads(strat["strategy_breakdown_json"])
        assert len(breakdown) == 2
        assert breakdown[0]["strategy_name"] == "涨停突破"
        assert breakdown[0]["win_rate"] == 0.55
        assert breakdown[1]["strategy_code"] == "low_volume_pullback"
    finally:
        conn.close()


def test_save_snapshot_idempotent_same_day(isolated_market_db):
    """同天重跑 lite → 行数不变，值覆盖（AC A3）。"""
    import scheduled_tasks as st

    st._save_snapshot("2026-08-08", "lite", _lite_result())
    # 改值再写——应覆盖
    from types import SimpleNamespace

    updated = SimpleNamespace(
        hit_rate=0.70, avg_return=3.0, max_drawdown=-4.0, sharpe_ratio=1.5,
        total_signals=50, percentile_analysis={"p50": 2.5},
    )
    st._save_snapshot("2026-08-08", "lite", updated)

    conn = st._get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM backtest_daily_snapshots WHERE engine='lite'"
        ).fetchall()
        assert len(rows) == 1  # 幂等，不新增
        r = dict(rows[0])
        assert r["hit_rate"] == 0.70  # 值被覆盖
        assert r["total_signals"] == 50
    finally:
        conn.close()


def test_get_backtest_snapshots_returns_asc(isolated_market_db):
    """多日快照 → 按 snapshot_date 升序返回，JSON 已反序列化。"""
    import scheduled_tasks as st

    st._save_snapshot("2026-08-07", "lite", _lite_result())
    st._save_snapshot("2026-08-08", "lite", _lite_result())
    st._save_snapshot("2026-08-09", "strategy", _strat_results())

    rows = st.get_backtest_snapshots(days=90)
    assert len(rows) == 3
    # 升序：08-07 < 08-08 < 08-09
    dates = [r["snapshot_date"] for r in rows]
    assert dates == sorted(dates)
    assert dates[0] == "2026-08-07"
    # JSON 反序列化
    strat_row = [r for r in rows if r["engine"] == "strategy"][0]
    assert isinstance(strat_row["strategy_breakdown_json"], list)
    lite_row = [r for r in rows if r["engine"] == "lite"][0]
    assert isinstance(lite_row["percentile_json"], dict)


# ---------------------------------------------------------------------------
# B1：trend 端点
# ---------------------------------------------------------------------------


def test_trend_endpoint_returns_sequence(isolated_market_db):
    """GET /api/backtest/trend?days=90 → {data: [...]} 按日期升序。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import scheduled_tasks as st

    st._save_snapshot("2026-08-07", "lite", _lite_result())
    st._save_snapshot("2026-08-08", "lite", _lite_result())
    st._save_snapshot("2026-08-09", "strategy", _strat_results())

    client = TestClient(appmod.app)
    r = client.get("/api/backtest/trend", params={"days": 90})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 3
    dates = [d["snapshot_date"] for d in data]
    assert dates == sorted(dates)
    # engine 字段存在
    engines = {d["engine"] for d in data}
    assert engines == {"lite", "strategy"}


def test_trend_endpoint_days_filter(isolated_market_db):
    """days=1 → 只返最近 1 天的快照。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import scheduled_tasks as st

    st._save_snapshot("2026-08-07", "lite", _lite_result())
    st._save_snapshot("2026-08-08", "lite", _lite_result())
    # 用一条很近的日期确保 days=1 至少截到它
    st._save_snapshot("2099-12-31", "lite", _lite_result())

    client = TestClient(appmod.app)
    r = client.get("/api/backtest/trend", params={"days": 1})
    assert r.status_code == 200
    data = r.json()["data"]
    # 至少包含 2099-12-31（date('now','-1 days') 之后）；不包含 08-07
    dates = {d["snapshot_date"] for d in data}
    assert "2099-12-31" in dates
    assert "2026-08-07" not in dates


def test_trend_endpoint_empty(isolated_market_db):
    """空表 → 返空数组，不报错。"""
    from fastapi.testclient import TestClient
    import app as appmod

    client = TestClient(appmod.app)
    r = client.get("/api/backtest/trend", params={"days": 90})
    assert r.status_code == 200
    assert r.json()["data"] == []


# ---------------------------------------------------------------------------
# A3：list_task_types 含 daily_backtest_run
# ---------------------------------------------------------------------------


def test_list_task_types_includes_backtest(isolated_market_db):
    """GET /api/scheduled-tasks/types 含 daily_backtest_run。"""
    from fastapi.testclient import TestClient
    import app as appmod

    client = TestClient(appmod.app)
    r = client.get("/api/scheduled-tasks/types")
    assert r.status_code == 200
    types = r.json()["data"]
    assert "daily_backtest_run" in types


# ---------------------------------------------------------------------------
# A2：_execute_daily_backtest_run（mock 两个回测函数，免真实数据）
# ---------------------------------------------------------------------------


def test_execute_daily_backtest_run_writes_two_rows(isolated_market_db, monkeypatch):
    """_execute_daily_backtest_run → 跑 lite+strategy，存 2 行（mock 免真实回测）。"""
    import scheduled_tasks as st

    # mock run_backtest_async（async）—— asyncio.run 调它
    async def _fake_run(start, end):
        return _lite_result()

    monkeypatch.setattr("backtest_lite.run_backtest_async", _fake_run)
    monkeypatch.setattr("strategies.strategy_backtest.run_strategy_backtest", lambda lb: _strat_results())

    result = st.TaskExecutor()._execute_daily_backtest_run({"lookback_days": 30})

    assert "lite" in result and "strategy" in result
    assert result["lite"]["hit_rate"] == 0.65
    assert result["strategy"]["strategies"] == 2
    # 落库 2 行
    conn = st._get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) FROM backtest_daily_snapshots").fetchone()[0]
        assert n == 2
    finally:
        conn.close()


def test_execute_daily_backtest_run_idempotent(isolated_market_db, monkeypatch):
    """同 payload 跑两次 → 行数仍 2（幂等，AC A3）。"""
    import scheduled_tasks as st

    async def _fake_run(start, end):
        return _lite_result()

    monkeypatch.setattr("backtest_lite.run_backtest_async", _fake_run)
    monkeypatch.setattr("strategies.strategy_backtest.run_strategy_backtest", lambda lb: _strat_results())

    ex = st.TaskExecutor()
    ex._execute_daily_backtest_run({"lookback_days": 30})
    ex._execute_daily_backtest_run({"lookback_days": 30})

    conn = st._get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) FROM backtest_daily_snapshots").fetchone()[0]
        assert n == 2  # 同天覆盖
    finally:
        conn.close()


def test_execute_daily_backtest_run_survives_lite_failure(isolated_market_db, monkeypatch):
    """lite 抛异常 → 不阻断 strategy，仍写 strategy 行，results 记 error。"""
    import scheduled_tasks as st

    async def _boom(start, end):
        raise RuntimeError("网络炸")

    monkeypatch.setattr("backtest_lite.run_backtest_async", _boom)
    monkeypatch.setattr("strategies.strategy_backtest.run_strategy_backtest", lambda lb: _strat_results())

    result = st.TaskExecutor()._execute_daily_backtest_run({"lookback_days": 30})

    assert "error" in str(result["lite"])
    assert result["strategy"]["strategies"] == 2
    conn = st._get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM backtest_daily_snapshots WHERE engine='strategy'"
        ).fetchone()[0]
        assert n == 1
        n_lite = conn.execute(
            "SELECT COUNT(*) FROM backtest_daily_snapshots WHERE engine='lite'"
        ).fetchone()[0]
        assert n_lite == 0
    finally:
        conn.close()
