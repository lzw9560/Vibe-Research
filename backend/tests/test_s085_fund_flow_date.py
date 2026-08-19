# -*- coding: utf-8 -*-
"""S085 A6 — stock_fund_flow_120d replay 误取今日单测（fund_flow 链）。

bug：fund_flow.py:27 `flows = astock.stock_fund_flow_120d(c)` 取最近 120 日，
用 flows[-1]（最新=今日）算 main_net_inflow → replay（as_of=历史日）时误取今日资金流，
与 as_of 不一致，污染 R2 因子。
修复：fund_flow 内部按 as_of 过滤 flows ≤ as_of（不改 stock_fund_flow_120d 签名，
topology/risk_models/前端直调不受影响）。

承重：main_net_inflow → R2 factor（不进最终胜率/结算，final_candidates 只读 DiagnosisCard）。
零回溯（main_net run 时算，不持久化）。risk_models:485 直调 stock_fund_flow_120d 不经 fund_flow，
单独记 todo。
"""
from __future__ import annotations

from candidate_funnel.sources import fund_flow


def _flows():
    return [
        {"date": "2026-08-14", "main_net": 1.0e8, "small_net": 0, "mid_net": 0, "large_net": 0, "super_net": 0},
        {"date": "2026-08-15", "main_net": 2.0e8, "small_net": 0, "mid_net": 0, "large_net": 0, "super_net": 0},
        {"date": "2026-08-16", "main_net": 3.0e8, "small_net": 0, "mid_net": 0, "large_net": 0, "super_net": 0},
        {"date": "2026-08-17", "main_net": 4.0e8, "small_net": 0, "mid_net": 0, "large_net": 0, "super_net": 0},
    ]


def test_main_net_uses_as_of_date_not_latest(monkeypatch):
    """replay as_of=2026-08-15 → main_net_inflow = 08-15 行（2e8），非最新 08-17（4e8）。"""
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: _flows())
    monkeypatch.setattr(fund_flow, "dragon_tiger_from_dict", lambda raw: type("D", (), {"institution_net": None})())
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    out = fund_flow.fetch_fund_flow(["600519"], "2026-08-15")
    # main_net_inflow = 2e8 / 1e4 = 2e4 万
    assert out["600519"]["main_net_inflow"] == 2.0e4, (
        f"replay as_of 应取 08-15 行（2e8），实得 {out['600519']['main_net_inflow']}（误取最新?）"
    )
    # _as_of 应反映 as_of（非最新 08-17）
    assert out["600519"]["_as_of"] == "2026-08-15"


def test_main_net_5d_uses_as_of_window(monkeypatch):
    """main_net_5d 用 ≤ as_of 的最后 5 行（非最新 5 行）。"""
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: _flows())
    monkeypatch.setattr(fund_flow, "dragon_tiger_from_dict", lambda raw: type("D", (), {"institution_net": None})())
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    # as_of=08-16 → flows ≤ 08-16 = [08-14,08-15,08-16]，main_net_5d = sum(3 行)/1e4
    out = fund_flow.fetch_fund_flow(["600519"], "2026-08-16")
    expected = round((1.0e8 + 2.0e8 + 3.0e8) / 10000.0, 1)
    assert out["600519"]["main_net_5d"] == expected


def test_as_of_none_keeps_latest_behavior(monkeypatch):
    """as_of 不传（盘后今日）→ 用最新行（既有行为，向后兼容）。"""
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: _flows())
    monkeypatch.setattr(fund_flow, "dragon_tiger_from_dict", lambda raw: type("D", (), {"institution_net": None})())
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    out = fund_flow.fetch_fund_flow(["600519"], "2099-12-31")  # 远未来 → 不过滤，用最新
    assert out["600519"]["main_net_inflow"] == 4.0e4  # 最新 08-17 = 4e8/1e4


def test_as_of_before_all_flows_missing(monkeypatch):
    """as_of 早于所有 flows → flows 过滤空 → main_net missing（不臆造）。"""
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: _flows())
    monkeypatch.setattr(fund_flow, "dragon_tiger_from_dict", lambda raw: type("D", (), {"institution_net": None})())
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    out = fund_flow.fetch_fund_flow(["600519"], "2026-07-01")  # 早于所有 flows
    assert out["600519"]["main_net_inflow"] is None
    assert "main_net_inflow" in out["600519"]["missing"]
