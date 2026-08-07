# -*- coding: utf-8 -*-
"""S034：SettlementEngine 接线单测（settled_at + recorder + 端点结算）。

所有 winrate 写入经 tmp db 注入——绝不碰用户真实 winrate.db（67 条手录记录）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def tmp_winrate(monkeypatch, tmp_path):
    """把 settlement_recorder._get_tracker 注入 tmp winrate.db。"""
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


# ---------------------------------------------------------------------------
# R2：settlement_summary 纯函数
# ---------------------------------------------------------------------------


def test_settlement_summary_math():
    import settlement_recorder as sr

    s = sr.settlement_summary(10.0, 11.0, "2026-08-01", "2026-08-04T15:00:00")
    assert s["return_pct"] == 10.0
    assert s["won"] is True
    assert s["hold_days"] == 3

    s = sr.settlement_summary(10.0, 9.5, "2026-08-01", "2026-08-02T15:00:00")
    assert s["return_pct"] == -5.0
    assert s["won"] is False

    # entry 为 0/None 不崩
    assert sr.settlement_summary(0.0, 11.0, "2026-08-01", "2026-08-02T15:00:00")["return_pct"] == 0.0


# ---------------------------------------------------------------------------
# R2：record_settlement
# ---------------------------------------------------------------------------


def _state_row(**overrides):
    base = {
        "code": "600001", "name": "测试甲", "trade_date": "2026-08-03",
        "status": "settled", "reason": "",
        "entry_price": 10.0, "exit_price": 11.0, "strategy": "首板挖掘",
        "settled_at": None, "created_at": "", "updated_at": "",
    }
    base.update(overrides)
    return base


def test_record_settlement_writes_winrate(tmp_winrate, monkeypatch):
    import settlement_recorder as sr

    monkeypatch.setattr(
        "limitup_screener.data.load_gene_scores",
        lambda d: [SimpleNamespace(code="600001", total_score=82.5)],
    )
    summary = sr.record_settlement(_state_row())
    assert summary is not None
    assert summary["return_pct"] == 10.0
    assert summary["won"] is True

    rows = _winrate_rows(tmp_winrate)
    assert len(rows) == 1
    r = rows[0]
    assert r["stock_code"] == "600001"
    assert r["entry_price"] == 10.0
    assert r["exit_price"] == 11.0
    assert r["return_pct"] == 10.0
    assert r["is_win"] == 1
    assert r["strategy_used"] == "首板挖掘"
    assert r["entry_date"] == "2026-08-03"  # 候选日≈信号日（诚实近似口径）
    assert r["gene_score"] == 82.5  # 基因 DB 回查真实分值


def test_record_settlement_missing_price_returns_none(tmp_winrate):
    import settlement_recorder as sr

    assert sr.record_settlement(_state_row(entry_price=None)) is None
    assert sr.record_settlement(_state_row(exit_price=None)) is None
    assert _winrate_rows(tmp_winrate) == []


def test_record_settlement_gene_fallback_zero(tmp_winrate, monkeypatch):
    """基因 DB 无该日数据 → gene_score 兜底 0.0，不报错。"""
    import settlement_recorder as sr

    monkeypatch.setattr("limitup_screener.data.load_gene_scores", lambda d: None)
    summary = sr.record_settlement(_state_row())
    assert summary is not None
    assert _winrate_rows(tmp_winrate)[0]["gene_score"] == 0.0


# ---------------------------------------------------------------------------
# R1/R4：repo settled_at 扩列 + 重入清零
# ---------------------------------------------------------------------------


def test_settled_at_column_and_mark(isolated_market_db):
    import workflow_state_repo as wsr

    conn = wsr._get_connection()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_state)").fetchall()}
        assert "settled_at" in cols
    finally:
        conn.close()

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    assert wsr.get_state("600001", "2026-08-07")["settled_at"] is None
    wsr.mark_settled("600001", "2026-08-07", "2026-08-07T15:00:00")
    assert wsr.get_state("600001", "2026-08-07")["settled_at"] == "2026-08-07T15:00:00"


def test_reentry_candidate_clears_settled_at(isolated_market_db):
    """settled→candidate 重入清 settled_at（新轮可再结算）。"""
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    for target in ("watching", "monitoring", "holding", "settled"):
        assert wsr.transition("600001", "2026-08-07", target, "")[0]
    wsr.mark_settled("600001", "2026-08-07", "2026-08-07T15:00:00")

    # 重入：settled→candidate
    assert wsr.transition("600001", "2026-08-07", "candidate", "新一轮")[0]
    assert wsr.get_state("600001", "2026-08-07")["settled_at"] is None


# ---------------------------------------------------------------------------
# R3/R5：端点结算接线 + 单股摘要
# ---------------------------------------------------------------------------


def _client_chain_to(client, code, date, upto):
    """candidate 起步，推进到 upto（含）。"""
    chain = ["watching", "monitoring", "holding", "settled"]
    for target in chain[: chain.index(upto) + 1]:
        r = client.post("/api/workflow/state/transition", json={"code": code, "date": date, "target": target})
        assert r.status_code == 200, r.text


def test_transition_settled_settles_and_records(tmp_winrate, isolated_market_db, monkeypatch):
    """settled 流转（价齐）→ winrate 记录 + settled_at + 响应 settlement 摘要。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    monkeypatch.setattr(
        "limitup_screener.data.load_gene_scores",
        lambda d: [SimpleNamespace(code="600001", total_score=88.0)],
    )
    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    client = TestClient(appmod.app)
    _client_chain_to(client, "600001", "2026-08-07", "monitoring")

    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "holding", "entry_price": 10.0, "strategy": "首板挖掘"})
    assert r.status_code == 200
    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "settled", "exit_price": 11.0})
    assert r.status_code == 200
    settlement = r.json()["data"]["settlement"]
    assert settlement["recorded"] is True
    assert settlement["return_pct"] == 10.0

    rows = _winrate_rows(tmp_winrate)
    assert len(rows) == 1 and rows[0]["return_pct"] == 10.0
    assert wsr.get_state("600001", "2026-08-07")["settled_at"]

    # 单股端点附 settlement 摘要（重算同值）
    r = client.get("/api/workflow/state/600001", params={"date": "2026-08-07"})
    data = r.json()["data"]
    assert data["settlement"]["return_pct"] == 10.0
    assert data["settlement"]["won"] is True


def test_transition_settled_missing_price_skips(tmp_winrate, isolated_market_db):
    """缺价 settled → 流转成功、不结算、不落 settled_at、reason 明确。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    client = TestClient(appmod.app)
    _client_chain_to(client, "600001", "2026-08-07", "monitoring")
    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "holding"})  # 不带 entry_price
    assert r.status_code == 200
    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "settled", "exit_price": 11.0})
    assert r.status_code == 200
    settlement = r.json()["data"]["settlement"]
    assert settlement["recorded"] is False
    assert "价" in settlement["reason"]
    assert _winrate_rows(tmp_winrate) == []
    assert wsr.get_state("600001", "2026-08-07")["settled_at"] is None


def test_reentry_allows_second_settlement(tmp_winrate, isolated_market_db, monkeypatch):
    """settled→candidate 重入后再 settled → 第二条 winrate 记录（新轮）。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    monkeypatch.setattr("limitup_screener.data.load_gene_scores", lambda d: None)
    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    client = TestClient(appmod.app)

    _client_chain_to(client, "600001", "2026-08-07", "monitoring")
    client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "holding", "entry_price": 10.0})
    client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "settled", "exit_price": 11.0})
    assert len(_winrate_rows(tmp_winrate)) == 1

    # 重入新轮：settled→candidate→watching→monitoring→holding→settled
    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "candidate", "reason": "新一轮"})
    assert r.status_code == 200
    _client_chain_to(client, "600001", "2026-08-07", "monitoring")
    client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "holding", "entry_price": 12.0})
    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "settled", "exit_price": 11.4})
    assert r.status_code == 200
    assert r.json()["data"]["settlement"]["recorded"] is True

    rows = _winrate_rows(tmp_winrate)
    assert len(rows) == 2
    assert rows[1]["entry_price"] == 12.0
    assert rows[1]["return_pct"] == -5.0
