# -*- coding: utf-8 -*-
"""S085 A2d — dragon_tiger_board 传 date（修 replay 误取今日龙虎榜）单测。

bug：fund_flow.py:48 调 `dragon_tiger_board(c)` 不传 date → eastmoney 默认今日 →
replay（as_of=历史日）时误取今日龙虎榜，与 as_of 不一致，污染 R2 因子 + dim7 评分。
修复：传 `dragon_tiger_board(c, trade_date=as_of)`——盘前 as_of=T→T 日未出榜返 T-1 最近；
replay as_of=H→查到 H（修 replay 误取）。

承重：dragon_tiger_inst_net → R2 factor + first_board_filter dim7。改 date 语义不改返回结构，
向后兼容（mock 须跟 dragon_tiger_board 真实签名 code/trade_date/look_back）。
"""
from __future__ import annotations

from candidate_funnel.sources import fund_flow


def test_dragon_tiger_board_receives_as_of_as_trade_date(monkeypatch):
    """fund_flow 把 as_of 透传给 dragon_tiger_board 的 trade_date（修 replay 误取今日）。"""
    captured: dict = {}

    def _fake_board(code, trade_date=None, look_back=30):
        captured["code"] = code
        captured["trade_date"] = trade_date
        return {"institution": {"net_amt": 3e8}, "records": []}

    monkeypatch.setattr(fund_flow.astock, "dragon_tiger_board", _fake_board)
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: [])
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    # Act — as_of=历史日（replay 场景）
    fund_flow.fetch_fund_flow(["600519"], "2026-07-15")
    # Assert — dragon_tiger_board 收到 trade_date=as_of（不是默认今日）
    assert captured["trade_date"] == "2026-07-15", (
        f"replay as_of 应透传给 dragon_tiger_board trade_date，实得 {captured.get('trade_date')}"
    )


def test_dragon_tiger_inst_net_still_returned(monkeypatch):
    """改 date 语义不改返回结构——institution_net 仍正确映射。"""
    monkeypatch.setattr(
        fund_flow.astock, "dragon_tiger_board",
        lambda c, trade_date=None, look_back=30: {"institution": {"net_amt": 2.5e8}, "records": []},
    )
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: [])
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    out = fund_flow.fetch_fund_flow(["600519"], "2026-08-18")
    assert out["600519"]["dragon_tiger_inst_net"] == 2.5e8


def test_dragon_tiger_missing_label_when_no_records(monkeypatch):
    """dragon_tiger_board 返空（无上榜）→ institution_net=None + missing 标注（不臆造）。"""
    monkeypatch.setattr(
        fund_flow.astock, "dragon_tiger_board",
        lambda c, trade_date=None, look_back=30: {"institution": {"net_amt": None}, "records": []},
    )
    monkeypatch.setattr(fund_flow.astock, "stock_fund_flow_120d", lambda c: [])
    monkeypatch.setattr(fund_flow, "fetch_northbound", lambda c, d=None: None)
    monkeypatch.setattr(fund_flow, "fetch_dt_hot_money_relay", lambda c, d=None: None)

    out = fund_flow.fetch_fund_flow(["600519"], "2026-08-18")
    assert out["600519"]["dragon_tiger_inst_net"] is None
    assert "dragon_tiger_inst_net" in out["600519"]["missing"]
