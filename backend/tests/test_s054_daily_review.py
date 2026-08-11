# -*- coding: utf-8 -*-
"""S054 W0：盘后三问 daily-review 端点测试。

fixture 造快照 + workflow_state → 验证三问三分支 + 无快照日 + 上一交易日回溯 +
K 线缺失排除 + bought 占位「待判定」。零外呼（mock _calc_next_day_return / snapshot_store / wsr）。
"""
from __future__ import annotations

from unittest import mock

import pytest

from win_rate_tracker import WinRateTracker
from routers.win_rate import _daily_review_impl


@pytest.fixture
def tmp_tracker(tmp_path) -> WinRateTracker:
    return WinRateTracker(db_path=str(tmp_path / "winrate.db"))


def test_no_snapshot_returns_honest(tmp_tracker, monkeypatch):
    """无快照日 → no_snapshot=true，pushed/bought/missed 全空。"""
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: None)
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return", lambda *a, **k: 0.0)

    result = _daily_review_impl("2026-08-11", tmp_tracker)
    assert result["no_snapshot"] is True
    assert result["pushed"] == []
    assert result["bought"] == []
    assert result["missed"] == []


def test_three_buckets_with_snapshot(tmp_tracker, monkeypatch):
    """有快照：pushed 3 只 / bought 1 只 holding / missed 2 只。"""
    snap = {"final_candidates": [
        {"code": "600519", "name": "贵州茅台", "gene_score": 70},
        {"code": "000001", "name": "平安银行", "gene_score": 65},
        {"code": "300750", "name": "宁德时代", "gene_score": 60},
    ]}
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap if d == "2026-08-11" else None)
    monkeypatch.setattr("workflow_state_repo.list_states",
                        lambda d: [{"code": "600519", "status": "holding", "name": "贵州茅台", "entry_price": 1800.0}])
    monkeypatch.setattr("backtest_lite._calc_next_day_return", lambda *a, **k: 0.0)
    monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-08")

    result = _daily_review_impl("2026-08-11", tmp_tracker)
    assert result["no_snapshot"] is False
    assert len(result["pushed"]) == 3
    assert result["pushed"][0]["code"] == "600519"
    assert result["pushed"][0]["gene_score"] == 70
    assert len(result["bought"]) == 1
    assert result["bought"][0]["code"] == "600519"
    assert result["bought"][0]["placeholder"] == "待判定"
    assert result["bought"][0]["entry_price"] == 1800.0
    bought_codes = {b["code"] for b in result["bought"]}
    missed_codes = {m["code"] for m in result["missed"]}
    assert bought_codes == {"600519"}
    assert missed_codes == {"000001", "300750"}


def test_prev_day_missed_next_day_return(tmp_tracker, monkeypatch):
    """上一交易日漏单次日收益 + 汇总（n/win_rate/avg_return）。"""
    today_snap = {"final_candidates": [{"code": "600519"}]}
    prev_snap = {"final_candidates": [
        {"code": "000001"}, {"code": "300750"}, {"code": "002594"}
    ]}
    snap_map = {"2026-08-11": today_snap, "2026-08-08": prev_snap}
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap_map.get(d))
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])
    # 000001 +5% / 300750 -3% / 002594 0.0（K 线缺）
    def fake_ret(code, d, cache=None):
        return {"000001": 0.05, "300750": -0.03, "002594": 0.0}.get(code, 0.0)
    monkeypatch.setattr("backtest_lite._calc_next_day_return", fake_ret)
    monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-08")

    result = _daily_review_impl("2026-08-11", tmp_tracker)
    pdm = result["prev_day_missed"]
    assert len(pdm["items"]) == 2  # 002594 K 线缺排除
    assert result["missing_kline"] == 1
    assert pdm["summary"]["n"] == 2
    assert pdm["summary"]["win_rate"] == 0.5
    assert pdm["summary"]["signal_date"] == "2026-08-08"


def test_prev_day_missed_empty_when_no_prev_snapshot(tmp_tracker, monkeypatch):
    """上一交易日无快照 → prev_day_missed 空态。"""
    snap = {"final_candidates": [{"code": "600519"}]}
    monkeypatch.setattr("snapshot_store.load_snapshot",
                        lambda d: snap if d == "2026-08-11" else None)
    monkeypatch.setattr("workflow_state_repo.list_states", lambda d: [])
    monkeypatch.setattr("backtest_lite._calc_next_day_return", lambda *a, **k: 0.0)
    monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-08")

    result = _daily_review_impl("2026-08-11", tmp_tracker)
    assert result["prev_day_missed"]["items"] == []
    assert result["prev_day_missed"]["summary"] is None


def test_bought_placeholder_label(tmp_tracker, monkeypatch):
    """bought 逐只带占位标签「待判定」——不展示 live 临时票根（Q7）。"""
    snap = {"final_candidates": [{"code": "600519"}]}
    monkeypatch.setattr("snapshot_store.load_snapshot", lambda d: snap)
    monkeypatch.setattr("workflow_state_repo.list_states",
                        lambda d: [{"code": "600519", "status": "holding", "name": "贵州茅台", "entry_price": 1800.0, "strategy": "first_plate"}])
    monkeypatch.setattr("backtest_lite._calc_next_day_return", lambda *a, **k: 0.0)
    monkeypatch.setattr("vr_paths.last_trading_date_str", lambda d=None: "2026-08-08")

    result = _daily_review_impl("2026-08-11", tmp_tracker)
    assert result["bought"][0]["placeholder"] == "待判定"
    assert "ticket" not in result["bought"][0].get("placeholder", "").lower()
