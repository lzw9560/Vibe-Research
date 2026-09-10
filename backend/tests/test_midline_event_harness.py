# -*- coding: utf-8 -*-
"""TDD tests for S182 midline_event_harness.build_return_series per-trade real cost.

T1.1 flat cost=0.0070 → costs=[0.70, 0.70]（percentage points，向后兼容）
T1.2 cost=None → per-trade _cost_pct，低价股 costs[0] > 1.0（非 0.70 flat）
T1.3 unit mismatch guard: cost=None + 低价股，ret > -1.0（忘 /100 会 ret=-2.70 荒谬）
"""
from __future__ import annotations

import pytest

from tools.midline_event_harness import build_return_series


def _make_cache():
    """构造 4 天日历 + 2 code kline_cache（高价股 + 低价股）。"""
    calendar = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    kline_cache = {
        "000001": [  # 高价股 10 元档
            {"date": "2026-01-05", "open": 10.0, "close": 10.2, "volume": 100},
            {"date": "2026-01-06", "open": 10.2, "close": 10.5, "volume": 100},
            {"date": "2026-01-07", "open": 10.5, "close": 10.8, "volume": 100},
            {"date": "2026-01-08", "open": 10.8, "close": 11.0, "volume": 100},
        ],
        "000002": [  # 低价股 5 元档（测 5 元最低佣金击穿）
            {"date": "2026-01-05", "open": 5.0, "close": 5.1, "volume": 100},
            {"date": "2026-01-06", "open": 5.1, "close": 5.0, "volume": 100},
            {"date": "2026-01-07", "open": 5.0, "close": 5.0, "volume": 100},
            {"date": "2026-01-08", "open": 5.0, "close": 5.0, "volume": 100},
        ],
    }
    return calendar, kline_cache


def test_build_return_series_flat_cost():
    """T1.1: cost=0.0070 flat，ret = exit/entry - 1.0 - 0.007，costs=[0.70, 0.70]。"""
    # Arrange
    calendar, kline_cache = _make_cache()
    events = [
        {"pub_date": "2026-01-05", "code": "000001"},
        {"pub_date": "2026-01-06", "code": "000001"},
    ]
    # Act
    returns, dates, guards, costs = build_return_series(
        events, kline_cache, calendar, horizon=1, cost_pct=0.0070,
    )
    # Assert
    assert guards["n_valid"] == 2
    assert costs == pytest.approx([0.70, 0.70])  # percentage points，flat 0.0070 × 100
    # event1: entry=10.2 (01-06), exit=10.8 (01-07) → 10.8/10.2-1-0.007 ≈ 0.0518
    assert abs(returns[0] - (10.8 / 10.2 - 1.0 - 0.0070)) < 1e-9


def test_build_return_series_per_trade_cost():
    """T1.2: cost=None → per-trade _cost_pct，低价股 costs[0] > 1.0（非 flat 0.70）。"""
    # Arrange
    calendar, kline_cache = _make_cache()
    events = [{"pub_date": "2026-01-05", "code": "000002"}]
    # Act
    returns, dates, guards, costs = build_return_series(
        events, kline_cache, calendar, horizon=1, cost_pct=None,
    )
    # Assert
    assert guards["n_valid"] == 1
    assert len(costs) == 1
    # 5 元股 notional=510，5 元最低佣金 ×2/notional×100 + 0.70% 滑点 + 0.05% 印花 ≈ 2.7%
    assert costs[0] > 1.0, f"低价股 real cost 应 >1.0% pp，got {costs[0]}"
    assert costs[0] != 0.70, "per-trade cost 不应等于 flat 0.70"


def test_unit_mismatch_guard():
    """T1.3: cost=None + 低价股，ret > -1.0（忘 /100 会 ret=gross-2.70 荒谬负值）。"""
    # Arrange
    calendar, kline_cache = _make_cache()
    events = [{"pub_date": "2026-01-05", "code": "000002"}]
    # Act
    returns, dates, guards, costs = build_return_series(
        events, kline_cache, calendar, horizon=1, cost_pct=None,
    )
    # Assert
    assert len(returns) == 1
    # 正确（/100）：ret = gross - 0.0275 ≈ -0.047，远 > -1.0
    # 忘 /100 bug：ret = gross - 2.75 ≈ -2.77，< -1.0 荒谬
    assert returns[0] > -1.0, f"ret={returns[0]} 荒谬（< -1.0），疑似忘 /100"
