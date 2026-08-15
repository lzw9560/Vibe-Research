# -*- coding: utf-8 -*-
"""S068：工作流触发与结算正确性。

- A2：TestClient 走真实 ASGI 路径触发 refresh，断言 200（锁 R1：原 sync `def` +
      `asyncio.create_task` 经 ASGI 线程池执行必抛 RuntimeError → 500）。
- A3：threading 真并发 holding→settled → 恰好 1 winrate / 1 ok / 1 history（锁 R3 承重）。
      TestClient 是同步串行的，两个“并发”请求会串行化、在旧代码上也只写 1 条（假信心），
      故改用 threading 在 repo/router 层真并发——回退 R3 的 `WHERE status=?` 守卫后此测试会写 N 条而失败。
- A5：settlement_summary 条件修复（entry=0 不除零；正常价不变；exit=None → 0.0）。

所有 winrate 写入经 tmp db 注入——绝不碰用户真实 winrate.db（沿用 S034 隔离）。
"""
from __future__ import annotations

import threading

import pytest


# ── 共用夹具 ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_winrate(monkeypatch, tmp_path):
    """把 settlement_recorder._get_tracker 注入 tmp winrate.db（绝不碰真实库）。"""
    import settlement_recorder as sr
    from win_rate_tracker import WinRateTracker

    tracker = WinRateTracker(db_path=str(tmp_path / "winrate.db"))
    monkeypatch.setattr(sr, "_get_tracker", lambda: tracker)
    return tracker


def _winrate_rows(tmp_winrate):
    import sqlite3

    conn = sqlite3.connect(tmp_winrate.db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM winrate_records ORDER BY id").fetchall()]
    conn.close()
    return rows


def _chain_to_holding(code="600001", date="2026-08-07"):
    """candidate 起步串行推到 holding（带 entry_price=10.0），供并发 settled 测试起步。"""
    import workflow_state_repo as wsr

    wsr.ensure_candidate(code, "测试甲", date, "")
    for target in ("watching", "monitoring", "holding"):
        ok, _ = wsr.transition(code, date, target, "", entry_price=10.0)
        assert ok, f"串行流转到 {target} 失败"


# ── A2：refresh 经 TestClient 真实 ASGI 路径返 200（锁 R1） ─────────────────


def test_refresh_returns_200_via_testclient(monkeypatch):
    """原 sync `def refresh_pre_market` + `asyncio.create_task` 经 Starlette 线程池执行
    必抛 RuntimeError(no running event loop) → 500。改 `async def` 后经 TestClient 应 200。

    真实 `create_task`（不 mock）——200 本身即证明 create_task 未抛（R1）。
    _cache/_pending_collections 注入 test-local 实例，避免污染模块全局态。
    """
    from fastapi.testclient import TestClient
    import app as appmod
    from routers import workflow as wf

    async def noop_collect(run_id, target_date):
        pass

    monkeypatch.setattr(wf, "_collect", noop_collect)
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    monkeypatch.setattr(wf, "_cache", {
        "run_id": None, "status": "idle", "factors": None, "data_date": None,
        "as_of": None, "market_emotion": None, "sentiment_context": None, "error": None,
    })
    monkeypatch.setattr(wf, "_pending_collections", set())

    client = TestClient(appmod.app)
    r = client.post("/api/workflow/pre-market/refresh", params={"date": "2026-08-07"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["run_id"]


# ── A3：threading 真并发 settled → 恰好 1 winrate（锁 R3 承重） ───────────────


def test_concurrent_settled_single_winrate(isolated_market_db, tmp_winrate, monkeypatch):
    """8 线程并发 holding→settled（带 exit_price=11）→ 恰好 1 settlement recorded / 1 winrate。

    R3 的 `WHERE status=?` 原子抢占使仅 1 个请求 ok=True 到达 _settle_on_transition；
    其余在 UPDATE 处 rowcount=0 → 400。回退 R3 守卫（去 `AND status=?`）后此测试会写多条而失败，
    证其区分力（TestClient 串行测无此区分力——旧代码串行下第二请求在 validation 阶段就被挡、也只写 1 条）。
    """
    from fastapi import HTTPException
    from routers import workflow as wf

    monkeypatch.setattr("limitup_screener.data.load_gene_scores", lambda d: None)
    _chain_to_holding()

    outcomes: list = []

    def one():
        req = wf._TransitionRequest(
            code="600001", date="2026-08-07", target="settled", exit_price=11.0,
        )
        try:
            r = wf.transition_workflow_state(req)
            outcomes.append(r["data"]["settlement"]["recorded"])
        except HTTPException:
            outcomes.append(False)

    threads = [threading.Thread(target=one) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert sum(1 for o in outcomes if o is True) == 1, f"应恰好 1 个 recorded=True，实际 {outcomes}"
    rows = _winrate_rows(tmp_winrate)
    assert len(rows) == 1, f"应恰好 1 条 winrate，实际 {len(rows)}"
    assert rows[0]["return_pct"] == 10.0

    import workflow_state_repo as wsr
    assert wsr.get_state("600001", "2026-08-07")["settled_at"] is not None


# ── A3b：threading 真并发 transition() → 恰好 1 ok / 1 history（R3 纯测） ─────


def test_concurrent_transition_atomic(isolated_market_db):
    """8 线程并发 wsr.transition(holding→settled) → 恰好 1 ok=True / 1 history 行。

    不经 router/结算，纯测 R3 的 `WHERE status=?` 原子抢占——回退守卫后会写 8 ok/8 history 而失败。
    """
    import workflow_state_repo as wsr

    _chain_to_holding()

    oks: list[bool] = []

    def one():
        ok, _ = wsr.transition("600001", "2026-08-07", "settled", "", exit_price=11.0)
        oks.append(ok)

    threads = [threading.Thread(target=one) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert sum(oks) == 1, f"应恰好 1 个 ok=True，实际 {sum(oks)}"
    conn = wsr._get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM workflow_state_history "
            "WHERE code='600001' AND trade_date='2026-08-07' AND to_status='settled'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1, f"应恰好 1 行 settled history，实际 {n}"


# ── A5：settlement_summary 条件修复 ────────────────────────────────────────


def test_settlement_summary_condition_fix():
    """R4：`entry_price not in (None, 0) and exit_price is not None` 显式守卫。

    原 `entry_price and exit_price is not None`（实为 `entry_price and (exit_price is not None)`）
    对正常价偶合正确，entry=0 靠短路侥幸绕过除零——现显式守卫，行为不变但意图明确。
    """
    import settlement_recorder as sr

    # 正常价不变
    s = sr.settlement_summary(10.0, 11.0, "2026-08-01T09:30:00", "2026-08-04T15:00:00")
    assert s["return_pct"] == 10.0
    assert s["won"] is True
    # entry=0 不除零、不抛异常
    assert sr.settlement_summary(0.0, 11.0, "2026-08-01", "2026-08-02")["return_pct"] == 0.0
    # exit=None → return_pct 0.0（不进入除法分支）
    assert sr.settlement_summary(10.0, None, "2026-08-01", "2026-08-02")["return_pct"] == 0.0
    # 时刻缺失 → hold_days 0
    assert sr.settlement_summary(10.0, 11.0, None, None)["hold_days"] == 0
