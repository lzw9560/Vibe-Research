# -*- coding: utf-8 -*-
"""S050 W0：票根关联三分支 + edge_family/holding_period 推断 + 异常兜底。

mock snapshot_store.load_snapshot + strategies.strategy_backtest.list_trades，
验证 record_settlement 写入 winrate_records 的 signal_source/signal_ref/edge_family 字段。
所有写入经 tmp db——绝不碰用户真实 winrate.db。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.fixture
def tmp_winrate(monkeypatch, tmp_path):
    """把 settlement_recorder._get_tracker 注入 tmp winrate.db。"""
    import settlement_recorder as sr
    from win_rate_tracker import WinRateTracker

    tracker = WinRateTracker(db_path=str(tmp_path / "winrate.db"))
    monkeypatch.setattr(sr, "_get_tracker", lambda: tracker)
    return tracker


def _state(**overrides):
    """构造 settled 状态行（价格齐备）。"""
    base = {
        "code": "600519", "name": "贵州茅台", "trade_date": "2026-07-01",
        "entry_price": 10.0, "exit_price": 11.0, "strategy": "first_plate",
        "attention_mode": "A",
    }
    base.update(overrides)
    return base


def _winrate_row(tmp_winrate):
    import sqlite3
    conn = sqlite3.connect(tmp_winrate.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM winrate_records ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def test_ticket_snapshot_hit_funnel_candidate(tmp_winrate, monkeypatch):
    """分支 1：快照 final_candidates 含 code → funnel_candidate + momentum_premium + T+1。"""
    import settlement_recorder as sr

    snap = {"final_candidates": [{"code": "600519", "name": "贵州茅台"}]}
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap)
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 80.0)

    sr.record_settlement(_state())
    row = _winrate_row(tmp_winrate)
    assert row["signal_source"] == "funnel_candidate"
    assert row["signal_ref"] == "funnel:final"
    assert row["edge_family"] == "momentum_premium"
    assert row["target_holding_period"] == "T+1"


def test_ticket_strategy_hit_when_not_in_snapshot(tmp_winrate, monkeypatch):
    """分支 2：快照未命中但战法 trades 命中 → strategy_hit + signal_ref=战法码。"""
    import settlement_recorder as sr

    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: None)
    trades = {"trades": [{"date": "2026-07-01", "code": "600519", "name": "茅台", "won": True}]}
    monkeypatch.setattr("strategies.strategy_backtest.list_trades", lambda s, lookback_days=60: trades)
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 60.0)

    sr.record_settlement(_state(strategy="first_plate"))
    row = _winrate_row(tmp_winrate)
    assert row["signal_source"] == "strategy_hit"
    assert row["signal_ref"] == "first_plate"
    assert row["target_holding_period"] == "T+1"  # 动量战法


def test_ticket_value_strategy_mean_reversion(tmp_winrate, monkeypatch):
    """value 类战法命中 → edge_family=mean_reversion + 20-60d。"""
    import settlement_recorder as sr

    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: None)
    trades = {"trades": [{"date": "2026-07-01", "code": "600519", "name": "茅台", "won": True}]}
    monkeypatch.setattr("strategies.strategy_backtest.list_trades", lambda s, lookback_days=60: trades)
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 0.0)

    sr.record_settlement(_state(strategy="value_rebound"))
    row = _winrate_row(tmp_winrate)
    assert row["signal_source"] == "strategy_hit"
    assert row["signal_ref"] == "value_rebound"
    assert row["edge_family"] == "mean_reversion"
    assert row["target_holding_period"] == "20-60d"


def test_ticket_feeling_when_both_miss(tmp_winrate, monkeypatch):
    """分支 3：快照与战法皆未命中 → feeling + edge_family/period 空。"""
    import settlement_recorder as sr

    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: {"final_candidates": []})
    monkeypatch.setattr("strategies.strategy_backtest.list_trades", lambda s, lookback_days=60: {"trades": []})
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 0.0)

    sr.record_settlement(_state(strategy="first_plate"))
    row = _winrate_row(tmp_winrate)
    assert row["signal_source"] == "feeling"
    assert row["signal_ref"] in ("", None)
    assert row["edge_family"] in ("", None)


def test_ticket_exception_fallback_feeling(tmp_winrate, monkeypatch):
    """快照与战法查找均异常 → 兜底 feeling（不阻塞结算）。"""
    import settlement_recorder as sr

    def boom_snap(d):
        raise RuntimeError("snap io error")

    def boom_trades(s, lookback_days=60):
        raise RuntimeError("trades io error")

    monkeypatch.setattr("snapshot_store.load_snapshot", boom_snap)
    monkeypatch.setattr("strategies.strategy_backtest.list_trades", boom_trades)
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 0.0)

    # 不抛异常即通过
    result = sr.record_settlement(_state())
    assert result is not None  # 结算摘要仍返
    row = _winrate_row(tmp_winrate)
    assert row["signal_source"] == "feeling"


def test_attention_mode_passthrough(tmp_winrate, monkeypatch):
    """attention_mode 从 state 行透传 winrate_records（缺省 'A'）。"""
    import settlement_recorder as sr

    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: None)
    monkeypatch.setattr("strategies.strategy_backtest.list_trades", lambda s, lookback_days=60: {"trades": []})
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 0.0)

    sr.record_settlement(_state(attention_mode="B"))
    row = _winrate_row(tmp_winrate)
    assert row["attention_mode"] == "B"


def test_attention_mode_default_A_when_missing(tmp_winrate, monkeypatch):
    """state 无 attention_mode 字段（旧行）→ 缺省 'A'。"""
    import settlement_recorder as sr

    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: None)
    monkeypatch.setattr("strategies.strategy_backtest.list_trades", lambda s, lookback_days=60: {"trades": []})
    monkeypatch.setattr(sr, "_lookup_gene_score", lambda code, date: 0.0)

    state = _state()
    del state["attention_mode"]  # 旧行无此字段
    sr.record_settlement(state)
    row = _winrate_row(tmp_winrate)
    assert row["attention_mode"] == "A"
