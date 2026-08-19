# -*- coding: utf-8 -*-
"""S085 A2d 残留 — first_board_filter score_dim7 dragon_tiger 传 date 单测。

bug：score_dim7_institution(candidate, date) 有 date 参数，但 :977 `dragon_tiger_board(code)`
不传 date → replay（date=H）误取今日龙虎榜，score_dim7 评分用错日机构净额。
修复：传 `dragon_tiger_board(code, trade_date=date)`（同 A2d fund_flow 范式）。

承重：score_dim7_institution → dim7 机构评分（权重 10%）。replay 误取今日→评分错。
risk_models 的 dragon_tiger/fflow 不传 date 不算 bug（实时风险取最新对，update_one_day_risk_realtime
是 V2.0.2 动态化实时评分，无 replay 场景）。
"""
from __future__ import annotations

from unittest import mock

from strategies import first_board_filter as fbf


def test_score_dim7_passes_date_to_dragon_tiger(monkeypatch):
    """score_dim7 的 date 透传给 dragon_tiger_board 的 trade_date（修 replay 误取今日）。"""
    captured: dict = {}

    def fake_dt_board(code, trade_date=None, look_back=30):
        captured["code"] = code
        captured["trade_date"] = trade_date
        return {"institution": {"net_amt": 3e8}, "records": []}

    monkeypatch.setattr(fbf, "dragon_tiger_board", fake_dt_board, raising=False)
    # score_dim7 内部 from astock import dragon_tiger_board → mock astock.dragon_tiger_board
    import astock
    monkeypatch.setattr(astock, "dragon_tiger_board", fake_dt_board)

    # Act — date=2026-07-15（replay 场景）
    score, raw = fbf.score_dim7_institution({"code": "600519"}, "2026-07-15")
    # Assert — dragon_tiger_board 收到 trade_date=date（不是默认今日）
    assert captured.get("trade_date") == "2026-07-15", (
        f"score_dim7 date 应透传给 dragon_tiger_board trade_date，实得 {captured.get('trade_date')}"
    )


def test_score_dim7_date_yyyymmdd_converted_to_iso(monkeypatch):
    """date=YYYYMMDD（实际 rank_candidates 传的格式）→ 转 ISO 给 dragon_tiger_board
    （否则 strptime %Y-%m-%d ValueError→except→静默 50 中性，agent 调查发现）。"""
    import astock
    captured: dict = {}
    def fake_dt(code, trade_date=None, look_back=30):
        captured["trade_date"] = trade_date
        return {"institution": {"net_amt": 3e8}, "records": []}
    monkeypatch.setattr(astock, "dragon_tiger_board", fake_dt)
    # Act — date=20260715（YYYYMMDD，实际格式）
    fbf.score_dim7_institution({"code": "600519"}, "20260715")
    # Assert — 转 ISO 传给 dragon_tiger_board（不是裸 YYYYMMDD）
    assert captured.get("trade_date") == "2026-07-15", (
        f"YYYYMMDD 须转 ISO，实得 {captured.get('trade_date')}"
    )


def test_score_dim7_returns_none_when_no_code(monkeypatch):
    """无 code → 50 中性 + raw（不调 dragon_tiger）。"""
    import astock
    called = []
    monkeypatch.setattr(astock, "dragon_tiger_board",
                        lambda c, trade_date=None, look_back=30: called.append(c) or {})
    score, raw = fbf.score_dim7_institution({}, "2026-08-18")
    assert score == 50.0
    assert not called  # 无 code 不调
