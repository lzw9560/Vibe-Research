# -*- coding: utf-8 -*-
"""S038：settled 流转自动拉市价填 exit_price 单测（market / manual / null 三分支）。

复用 S034 测试风格：tmp_winrate 注入 + isolated_market_db 隔离 + TestClient 端到端。
绝不碰用户真实 winrate.db（67 条手录记录）。
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


def _client_chain_to(client, code, date, upto):
    """candidate 起步，推进到 upto（含）。"""
    chain = ["watching", "monitoring", "holding", "settled"]
    for target in chain[: chain.index(upto) + 1]:
        r = client.post("/api/workflow/state/transition", json={"code": code, "date": date, "target": target})
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# R1：fetch_current_price 纯函数（A2）
# ---------------------------------------------------------------------------


def test_fetch_current_price_returns_price(monkeypatch):
    """mock tencent_quote 返有价 → 返 price。"""
    import market_price

    monkeypatch.setattr(
        market_price.astock, "tencent_quote",
        lambda codes: {"600519": {"price": "1800.50", "name": "贵州茅台"}},
    )
    assert market_price.fetch_current_price("600519") == 1800.5


def test_fetch_current_price_empty_returns_none(monkeypatch):
    """mock tencent_quote 返空 dict → 返 None。"""
    import market_price

    monkeypatch.setattr(market_price.astock, "tencent_quote", lambda codes: {})
    assert market_price.fetch_current_price("600519") is None


def test_fetch_current_price_exception_returns_none(monkeypatch):
    """mock tencent_quote 抛异常 → 返 None（不抛，兜底）。"""
    import market_price

    def _boom(codes):
        raise RuntimeError("网络炸")

    monkeypatch.setattr(market_price.astock, "tencent_quote", _boom)
    assert market_price.fetch_current_price("600519") is None


# ---------------------------------------------------------------------------
# R2/R3/R4：端点三分支（market / manual / null）
# ---------------------------------------------------------------------------


def test_settle_market_auto_fill(tmp_winrate, isolated_market_db, monkeypatch):
    """分支 1：auto_fill=true + exit_price=None → 拉价成功，source="market"。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    monkeypatch.setattr(
        "limitup_screener.data.load_gene_scores",
        lambda d: [SimpleNamespace(code="600519", total_score=90.0)],
    )
    # mock 拉价（端点 import 路径：backend.market_price.astock.tencent_quote）
    monkeypatch.setattr(
        "market_price.astock.tencent_quote",
        lambda codes: {"600519": {"price": "1800.50", "name": "贵州茅台"}},
    )
    wsr.ensure_candidate("600519", "贵州茅台", "2026-08-07", "")
    client = TestClient(appmod.app)
    _client_chain_to(client, "600519", "2026-08-07", "monitoring")

    r = client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "holding", "entry_price": 100.0})
    assert r.status_code == 200
    r = client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "settled", "auto_fill_exit_price": True})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    settlement = data["settlement"]
    assert settlement["recorded"] is True
    assert settlement["exit_price_source"] == "market"
    assert data["exit_price"] == 1800.5  # 拉到价经 transition 落库后回读
    assert settlement["return_pct"] == round(((1800.5 - 100.0) / 100.0) * 100, 2)

    rows = _winrate_rows(tmp_winrate)
    assert len(rows) == 1
    assert rows[0]["exit_price"] == 1800.5
    assert wsr.get_state("600519", "2026-08-07")["settled_at"]


def test_settle_manual_exit_price_no_fetch(tmp_winrate, isolated_market_db, monkeypatch):
    """分支 2：exit_price 手填 → 不调 tencent_quote，source="manual"。"""
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    import app as appmod
    import market_price
    import workflow_state_repo as wsr

    monkeypatch.setattr(
        "limitup_screener.data.load_gene_scores",
        lambda d: [SimpleNamespace(code="600519", total_score=90.0)],
    )
    # mock 整个 fetch_current_price：手填分支不应被调用
    mock_fetch = MagicMock(return_value=9999.0)
    monkeypatch.setattr(market_price, "fetch_current_price", mock_fetch)
    wsr.ensure_candidate("600519", "贵州茅台", "2026-08-07", "")
    client = TestClient(appmod.app)
    _client_chain_to(client, "600519", "2026-08-07", "monitoring")

    client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "holding", "entry_price": 100.0})
    r = client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "settled",
        "exit_price": 1850.0, "auto_fill_exit_price": True})
    assert r.status_code == 200, r.text
    settlement = r.json()["data"]["settlement"]
    assert settlement["recorded"] is True
    assert settlement["exit_price_source"] == "manual"
    assert r.json()["data"]["exit_price"] == 1850.0
    mock_fetch.assert_not_called()  # 手填优先，零拉价调用

    rows = _winrate_rows(tmp_winrate)
    assert len(rows) == 1 and rows[0]["exit_price"] == 1850.0


def test_settle_market_fetch_fails_fallback(tmp_winrate, isolated_market_db, monkeypatch):
    """分支 3：拉价失败（空/异常）→ fallback S034 缺价跳过，recorded=False，source=None。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    monkeypatch.setattr(
        "limitup_screener.data.load_gene_scores",
        lambda d: [SimpleNamespace(code="600519", total_score=90.0)],
    )
    # mock 拉价返空
    monkeypatch.setattr("market_price.astock.tencent_quote", lambda codes: {})
    wsr.ensure_candidate("600519", "贵州茅台", "2026-08-07", "")
    client = TestClient(appmod.app)
    _client_chain_to(client, "600519", "2026-08-07", "monitoring")

    client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "holding", "entry_price": 100.0})
    r = client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "settled", "auto_fill_exit_price": True})
    assert r.status_code == 200, r.text
    settlement = r.json()["data"]["settlement"]
    assert settlement["recorded"] is False
    assert settlement["exit_price_source"] is None
    assert "价" in settlement["reason"]
    assert _winrate_rows(tmp_winrate) == []
    assert wsr.get_state("600519", "2026-08-07")["settled_at"] is None


def test_settle_no_auto_fill_flag_keeps_s034_behavior(tmp_winrate, isolated_market_db, monkeypatch):
    """不传 auto_fill_exit_price → 保持 S034 原行为（exit_price 缺则跳过，source=None）。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import market_price
    import workflow_state_repo as wsr

    monkeypatch.setattr(
        "limitup_screener.data.load_gene_scores",
        lambda d: [SimpleNamespace(code="600519", total_score=90.0)],
    )
    # 不传 flag 时即使能拉到价也不应拉（S034 兼容）
    monkeypatch.setattr(
        market_price, "fetch_current_price",
        lambda code: 9999.0,
    )
    wsr.ensure_candidate("600519", "贵州茅台", "2026-08-07", "")
    client = TestClient(appmod.app)
    _client_chain_to(client, "600519", "2026-08-07", "monitoring")

    client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "holding", "entry_price": 100.0})
    r = client.post("/api/workflow/state/transition", json={
        "code": "600519", "date": "2026-08-07", "target": "settled"})  # 不带 exit_price，不带 flag
    assert r.status_code == 200, r.text
    settlement = r.json()["data"]["settlement"]
    assert settlement["recorded"] is False
    assert settlement["exit_price_source"] is None
    assert _winrate_rows(tmp_winrate) == []
