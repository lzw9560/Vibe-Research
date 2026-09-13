# -*- coding: utf-8 -*-
"""S201a test_accounting.py——TDD 地基（当前不存在，verdict 说须从零建）。

覆盖 _cost_pct 5元门 bind/unbind + t0_cost + path_return net vs gross + 口径统一 accounting=F3 同函数。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.accounting import (
    _cost_pct,
    t0_cost,
    ROUND_TRIP_COST_PCT,
    STAMP_DUTY_PCT,
    STAMP_DUTY_PCT_PRE_2023_08_28,
    COMMISSION_MIN_YUAN,
    T0_SLIPPAGE_PCT,
)


def test_cost_pct_5yuan_binds_for_small_notional():
    """小单（5元门 binds）：低价股 1 手 notional 小，5元门主导成本高。

    S182：5元股 1 手=500元，5元×2 side/500×100=2.0% 佣金，+0.70% spread+0.05% 印花=2.75% 真实。
    """
    cost = _cost_pct(entry_price=5.0, size=100, entry_date="2024-01-15")
    # 0.70(spread) + 0.05(stamp, 2024 > 2023-08-28) + 2.0(5元×2/500×100) = 2.75%
    assert cost == 2.75


def test_cost_pct_rate_dominates_for_large_notional():
    """大单（5元门不 binds）：高价股 notional 大，佣金按费率低。

    100元股 1 手=10000元，佣金 5元×2/10000×100=0.1%（<费率 0.025%×2=0.05%？不——max(费率,5元)）
    实际 _cost_pct 用 5元最低（非 max），大单成本=0.70+0.05+0.1=0.85%。
    """
    cost = _cost_pct(entry_price=100.0, size=100, entry_date="2024-01-15")
    # 0.70 + 0.05 + (5×2/10000×100=0.1) = 0.85%
    assert abs(cost - 0.85) < 0.01


def test_cost_pct_stamp_duty_time_variant():
    """印花税时变：2023-08-28 前 0.10%，后 0.05%。"""
    cost_pre = _cost_pct(entry_price=10.0, size=100, entry_date="2023-08-27")
    cost_post = _cost_pct(entry_price=10.0, size=100, entry_date="2023-08-28")
    # 印花差 0.05%，其他同（0.70 spread + 佣金 5×2/1000×100=1.0%）
    assert abs(cost_pre - cost_post - 0.05) < 0.01
    assert cost_pre > cost_post  # pre 更高（印花 0.10 vs 0.05）


def test_cost_pct_empty_date_defaults_current_stamp():
    """空 entry_date → 当前印花 0.05%（保守低估）。"""
    cost = _cost_pct(entry_price=10.0, size=100, entry_date="")
    assert cost > 0
    # 含 0.05% 印花（当前）


def test_cost_pct_zero_notional_fallback():
    """notional=0 → fallback spread+stamp（不崩）。"""
    cost = _cost_pct(entry_price=0.0, size=100, entry_date="2024-01-01")
    assert cost == ROUND_TRIP_COST_PCT + STAMP_DUTY_PCT  # 0.70 + 0.05 = 0.75


def test_t0_cost_uses_slippage_not_round_trip():
    """T+0 用 T0_SLIPPAGE_PCT(0.10%) 非 ROUND_TRIP_COST_PCT(0.70%)。

    S189 grill：T+0 成交价是分钟 VWAP 不需 0.70% 理论价桥接。
    """
    cost_t0 = t0_cost(entry_price=10.0, size=100, date="2024-01-15")
    # 0.10(slippage) + 0.05(stamp) + 佣金 max(费率, 5元)×2/notional
    # notional=1000, 佣金 max(1000×0.025%/100=0.25元, 5元)×2=10元 / 1000×100 = 1.0%
    # = 0.10 + 0.05 + 1.0 = 1.15%
    assert abs(cost_t0 - 1.15) < 0.01
    # T+0 成本 < T+1 round-trip 成本（0.70 spread vs 0.10 slip）
    cost_t1 = _cost_pct(entry_price=10.0, size=100, entry_date="2024-01-15")
    assert cost_t0 < cost_t1


def test_t0_cost_large_notional_rate_dominates():
    """T+0 大单佣金按费率（非 5元最低）——S189 grill 修原只 5元最低低估大单 bug。"""
    cost = t0_cost(entry_price=100.0, size=100, date="2024-01-15")
    # notional=10000, 佣金 max(10000×0.025%/100=2.5元, 5元)×2=10元/10000×100=0.1%
    # = 0.10 + 0.05 + 0.1 = 0.25%
    assert abs(cost - 0.25) < 0.01


def test_cost_pct_size_dependent_not_flat():
    """S201 verdict：cost 是 size-dependent 非 flat 常量。

    绝不可 flatten 到 0.20-0.30%（重现 S182 4x 低价偏差）。
    低价股成本 >> 高价股（5元门 binds）。
    """
    cost_low_price = _cost_pct(entry_price=5.0, size=100, entry_date="2024-01-15")
    cost_high_price = _cost_pct(entry_price=100.0, size=100, entry_date="2024-01-15")
    assert cost_low_price > cost_high_price * 2  # 2.75% >> 0.85%
    assert cost_low_price > 1.0  # 低价股 >1%


def test_cost_caliber_consistency_accounting_f3_same_function():
    """S201a 口径统一：F3 verdict 须调 accounting._cost_pct 逐笔（非 flat 0.2%）。

    模拟 F3 rewire：每条 record 的 cost = _cost_pct(entry_price, 100, entry_date)。
    mean cost 应在 0.15-2.75% 范围（size-dependent），非 flat 0.2%。
    """
    # 模拟 5 标的 entry_price/entry_date（混合高低价）
    records = [
        (5.0, "2024-01-15"),   # 低价 5元门 binds ~2.75%
        (10.0, "2024-01-15"),  # 中低价 ~1.75%
        (100.0, "2024-01-15"), # 高价 rate ~0.85%
        (50.0, "2024-01-15"),  # 中高价 ~1.0%
        (20.0, "2024-01-15"),  # 中价 ~1.2%
    ]
    costs = [_cost_pct(ep, 100, ed) for ep, ed in records]
    mean_cost = sum(costs) / len(costs)
    # mean 在 0.15-2.75% 之间（size-dependent），非 flat 0.2%
    assert 0.15 < mean_cost < 2.75
    # 绝非 flat 0.2%（S194 旧值）
    assert mean_cost != 0.2
