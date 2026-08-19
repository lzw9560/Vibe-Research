# -*- coding: utf-8 -*-
"""S085 A4/A3 — 盘前所有因子取 T-1（S084 盘前边界实现缺口）单测。

bug：funnel.py 盘前传 date=T 给 fetch_activity → tencent 当日路径 →
prev_amount_yi/K线派生 None（放量比降级，limitup_strategy:922 承重）。
修复（S084「盘前所有因子取 T-1」intent）：盘前（date>=today）fetch_activity 用 yesterday_date
走 kline T-1 路径（算 prev_amount_yi/K线派生）；历史日（date<today）保 date（replay 取该日）。

承重：盘前所有因子语义变 T-1（price/change/turnover/eight_standards/战法全 T-1），影响选股分。
S084 territory semantic 改。tests 跑 run_funnel/diagnose 都用历史日（已走 kline，不受盘前分支影响）。
"""
from __future__ import annotations

from datetime import date
from unittest import mock

from candidate_funnel import funnel as fmod
from candidate_funnel.models import ThresholdConfig


def _mock_sources(activity_capture: list):
    """仿 test_s049 范式 mock 全 source，activity 用 side_effect 捕获 date 参数。"""
    def fake_fa(codes, d):
        activity_capture.append(d)
        return {c: {"name": "X", "_as_of": d} for c in codes}
    return (
        mock.patch.object(fmod.sources.gene, "fetch_genes", return_value={"600519": {"name": "X"}}),
        mock.patch.object(fmod.sources.board_ladder, "fetch_board_ladder", return_value={"lianban_stocks": []}),
        mock.patch.object(fmod.sources.activity, "fetch_activity", side_effect=fake_fa),
        mock.patch.object(fmod.sources.fund_flow, "fetch_fund_flow", return_value={"600519": {}}),
        mock.patch.object(fmod.sources.auction, "fetch_auction", return_value={}),
        mock.patch.object(fmod.sources.catalyst, "fetch_catalyst", return_value={}),
        mock.patch.object(fmod, "_fetch_sentiment_phase", return_value=None),
    )


def test_pre_market_activity_uses_yesterday_not_today():
    """盘前（date=today）→ fetch_activity 收 yesterday_date（T-1），非 today。"""
    today = date.today().isoformat()
    cap: list = []
    patches = _mock_sources(cap)
    for p in patches:
        p.start()
    try:
        fmod.diagnose("600519", today, ThresholdConfig())
    finally:
        for p in patches:
            p.stop()
    assert cap, "fetch_activity 未被调用"
    assert cap[0] != today, f"盘前应用 yesterday_date，实得 today={cap[0]}"
    assert cap[0] < today, f"yesterday 应 < today，实得 {cap[0]}"


def test_historical_activity_uses_date():
    """历史日（date<today）→ fetch_activity 收 date（replay 取该日，不走 yesterday）。"""
    cap: list = []
    patches = _mock_sources(cap)
    for p in patches:
        p.start()
    try:
        fmod.diagnose("600519", "2026-08-10", ThresholdConfig())
    finally:
        for p in patches:
            p.stop()
    assert cap[0] == "2026-08-10", f"历史日应传 date，实得 {cap[0]}"
