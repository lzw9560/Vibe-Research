# -*- coding: utf-8 -*-
"""S201a/S201b test_accounting.py——TDD 地基。

覆盖 _cost_pct 5元门 bind/unbind + t0_cost + path_return net vs gross + 口径统一 accounting=F3 同函数。
S201b：RTC 0.70→0.15（0.10% slippage + 0.05% residual half-spread）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.accounting import (
    _cost_pct,
    t0_cost,
    path_return,
    STOP_SLIPPAGE_EPS,
    ROUND_TRIP_COST_PCT,
    STAMP_DUTY_PCT,
    STAMP_DUTY_PCT_PRE_2023_08_28,
    COMMISSION_MIN_YUAN,
    T0_SLIPPAGE_PCT,
)
from engine.decision import Trades, FILL_T_PLUS_1_OPEN, FILL_ACCEPTED


def test_round_trip_cost_pct_is_0_15():
    """S201b：RTC 0.70→0.15（0.10 slippage + 0.05 residual half-spread）。"""
    assert ROUND_TRIP_COST_PCT == 0.15


def test_cost_pct_5yuan_binds_for_small_notional():
    """小单（5元门 binds）：低价股 1 手 notional 小，5元门主导成本高。

    S201b RTC=0.15：5元股 1手=500元，5元×2 side/500×100=2.0% 佣金，
    +0.15%(spread+slip) +0.05%(stamp) = 2.20% 真实。
    """
    cost = _cost_pct(entry_price=5.0, size=100, entry_date="2024-01-15")
    # 0.15(spread+slip) + 0.05(stamp, 2024 > 2023-08-28) + 2.0(5元×2/500×100) = 2.20%
    assert abs(cost - 2.20) < 0.01


def test_cost_pct_rate_dominates_for_large_notional():
    """大单（5元门不 binds）：高价股 notional 大，佣金按费率低。

    S201b RTC=0.15：100元股 1手=10000元，佣金 5元×2/10000×100=0.1%，
    +0.15% + 0.05% = 0.30%。
    """
    cost = _cost_pct(entry_price=100.0, size=100, entry_date="2024-01-15")
    # 0.15 + 0.05 + (5×2/10000×100=0.1) = 0.30%
    assert abs(cost - 0.30) < 0.01


def test_cost_pct_stamp_duty_time_variant():
    """印花税时变：2023-08-28 前 0.10%，后 0.05%。"""
    cost_pre = _cost_pct(entry_price=10.0, size=100, entry_date="2023-08-27")
    cost_post = _cost_pct(entry_price=10.0, size=100, entry_date="2023-08-28")
    # 印花差 0.05%，其他同（0.15 spread + 佣金 5×2/1000×100=1.0%）
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
    assert cost == ROUND_TRIP_COST_PCT + STAMP_DUTY_PCT  # 0.15 + 0.05 = 0.20


def test_t0_cost_uses_slippage_not_round_trip():
    """T+0 用 T0_SLIPPAGE_PCT(0.10%) 非 ROUND_TRIP_COST_PCT(0.15%)。

    S189 grill：T+0 成交价是分钟 VWAP 不需 0.70% 理论价桥接。
    """
    cost_t0 = t0_cost(entry_price=10.0, size=100, date="2024-01-15")
    # 0.10(slippage) + 0.05(stamp) + 佣金 max(费率, 5元)×2/notional
    # notional=1000, 佣金 max(1000×0.025%/100=0.25元, 5元)×2=10元 / 1000×100 = 1.0%
    # = 0.10 + 0.05 + 1.0 = 1.15%
    assert abs(cost_t0 - 1.15) < 0.01
    # T+0 成本 < T+1 round-trip 成本（0.15 spread vs 0.10 slip）
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
    assert cost_low_price > cost_high_price * 2  # 2.20% >> 0.30%
    assert cost_low_price > 1.0  # 低价股 >1%


def test_cost_caliber_consistency_accounting_f3_same_function():
    """S201a 口径统一：F3 verdict 须调 accounting._cost_pct 逐笔（非 flat 0.2%）。

    模拟 F3 rewire：每条 record 的 cost = _cost_pct(entry_price, 100, entry_date)。
    mean cost 应在 0.15-2.20% 范围（size-dependent），非 flat 0.2%。
    """
    # 模拟 5 标的 entry_price/entry_date（混合高低价）
    records = [
        (5.0, "2024-01-15"),   # 低价 5元门 binds ~2.20%
        (10.0, "2024-01-15"),  # 中低价 ~1.20%
        (100.0, "2024-01-15"), # 高价 rate ~0.30%
        (50.0, "2024-01-15"),  # 中高价 ~0.40%
        (20.0, "2024-01-15"),  # 中价 ~0.70%
    ]
    costs = [_cost_pct(ep, 100, ed) for ep, ed in records]
    mean_cost = sum(costs) / len(costs)
    # mean 在 0.15-2.20% 之间（size-dependent），非 flat 0.2%
    assert 0.15 < mean_cost < 2.20
    # 绝非 flat 0.2%（S194 旧值）
    assert mean_cost != 0.2


# ── S201b stage 2: stop gap-through-aware fill（修硬编码 gross=float(stop_pct)）──


def _make_trades(entry_price: float = 10.0, signal_date: str = "2026-01-01") -> Trades:
    """构造已 filled Trades（entry_price 预填，供 path_return 用）。"""
    return Trades(
        code="test_stop",
        signal_date=signal_date,
        fill_type=FILL_T_PLUS_1_OPEN,
        direction="long",
        size=100,
        entry_price=entry_price,
        fill_status=FILL_ACCEPTED,
    )


def _bar(date: str, o: float, h: float, l: float, c: float) -> dict:
    """构造单根 OHLCV bar。"""
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": 10000}


def test_stop_gap_through_fills_at_open():
    """S201b stage 2: 开盘已穿止损（gap-through）→ fill=open（比止损位更差）。

    旧硬编码 gross=float(stop_pct)=-4.0%（假设精确止损位成交，乐观）。
    gap-through 时 open 在止损位以下，真实成交价更差。
    """
    entry = 10.0
    stop_pct = -4.0  # stop_level = 10.0 * 0.96 = 9.6
    bars = [
        _bar("2026-01-01", 10.0, 10.2, 9.8, 10.1),   # signal
        _bar("2026-01-02", 10.0, 10.3, 9.9, 10.2),    # T+1 entry
        _bar("2026-01-03", 9.5, 9.8, 9.3, 9.6),       # T+2: open=9.5 <= stop_level=9.6 → gap-through
        _bar("2026-01-04", 9.7, 10.0, 9.5, 9.8),     # T+3
    ]
    pr = path_return(_make_trades(entry), bars, stop_pct, 8.0, 3, apply_cost=False)
    assert pr is not None
    assert pr.exit_reason == "stop"
    # fill at open=9.5, gross = (9.5-10.0)/10.0*100 = -5.0%（比硬编码 -4.0% 更差）
    assert pr.gross_return_pct == pytest.approx(-5.0, abs=0.01)
    assert pr.exit_price == pytest.approx(9.5, abs=0.001)
    # 绝非旧硬编码 -4.0%
    assert pr.gross_return_pct < -4.0


def test_stop_normal_touch_fills_at_stop_level_with_slippage():
    """S201b stage 2: 正常触止损（low 碰止损位，open 在止损位以上）→ fill=stop*(1-eps)。

    正常触止损时 fill 在止损位附近，加微小滑点（STOP_SLIPPAGE_EPS）。
    """
    entry = 10.0
    stop_pct = -4.0  # stop_level = 9.6
    bars = [
        _bar("2026-01-01", 10.0, 10.2, 9.8, 10.1),   # signal
        _bar("2026-01-02", 10.0, 10.3, 9.9, 10.2),    # T+1 entry
        _bar("2026-01-03", 9.8, 10.0, 9.5, 9.7),      # T+2: open=9.8 > stop, low=9.5 <= stop → normal touch
        _bar("2026-01-04", 9.7, 10.0, 9.5, 9.8),      # T+3
    ]
    pr = path_return(_make_trades(entry), bars, stop_pct, 8.0, 3, apply_cost=False)
    assert pr is not None
    assert pr.exit_reason == "stop"
    # fill = stop_level * (1 - eps) = 9.6 * (1 - 0.001) = 9.5904
    expected_fill = 9.6 * (1 - STOP_SLIPPAGE_EPS)
    expected_gross = (expected_fill - entry) / entry * 100
    assert pr.gross_return_pct == pytest.approx(expected_gross, abs=0.01)
    assert pr.exit_price == pytest.approx(expected_fill, abs=0.001)
    # 比硬编码 -4.0% 略差（滑点）
    assert pr.gross_return_pct < -4.0


def test_stop_locked_down_bar_carries_to_next_bar():
    """S201b2: 一字跌停（high==low 且 ≤ stop）→ stop 触发 pending，下个 tradeable bar 填 open。

    locked-down bar 无法成交（无买家），但 stop 已触发（price 已穿 stop）→ pending market sell
    填下个 tradeable bar 的集合竞价 open（非重新评估 trigger）。修 S201b carry 丢 trigger bug。
    """
    entry = 10.0
    stop_pct = -4.0  # stop_level = 9.6
    bars = [
        _bar("2026-01-01", 10.0, 10.2, 9.8, 10.1),   # signal
        _bar("2026-01-02", 10.0, 10.3, 9.9, 10.2),    # T+1 entry
        _bar("2026-01-03", 9.0, 9.0, 9.0, 9.0),       # T+2: 一字跌停 9.0 <= stop 9.6 → pending_stop
        _bar("2026-01-04", 9.8, 10.0, 9.5, 9.7),      # T+3: tradeable → pending fill=open=9.8
        _bar("2026-01-05", 9.7, 10.0, 9.5, 9.8),      # T+4
    ]
    pr = path_return(_make_trades(entry), bars, stop_pct, 8.0, 3, apply_cost=False)
    assert pr is not None
    assert pr.exit_reason == "stop"
    # exit_date 是 T+3（bars[3]）：T+2 locked → pending，T+3 tradeable 填 open
    assert pr.exit_date == "2026-01-04"
    # pending market sell 填 T+3 open=9.8（overnight recovery 后 open>stop → 填 recovered open，诚实）
    expected_fill = 9.8  # T+3 open（非 stop×(1-eps)——stop 已 pending，填下 bar open）
    expected_gross = (expected_fill - entry) / entry * 100  # (9.8-10)/10 = -2.0%
    assert pr.exit_price == pytest.approx(expected_fill, abs=0.001)
    assert pr.gross_return_pct == pytest.approx(expected_gross, abs=0.01)


def test_stop_locked_below_then_recovery_triggers_pending_fill():
    """S201b2: locked-below-stop bar 后跟 recovery → stop 须触发(pending)，填下 bar open。

    bug: _is_sellable_bar False 在 locked-below-stop bar 跳过整个 trigger 检查 →
    若下 bar recovery(open>stop, low>stop)，stop 永不触发 → max_hold 乐观泄露。
    修: locked-below-stop → pending_stop，下 tradeable bar 填 open。
    """
    entry = 10.0
    stop_pct = -4.0  # stop_level = 9.6
    bars = [
        _bar("2026-01-01", 10.0, 10.2, 9.8, 10.1),   # signal
        _bar("2026-01-02", 10.0, 10.3, 9.9, 10.2),    # T+1 entry
        _bar("2026-01-03", 9.0, 9.0, 9.0, 9.0),       # T+2: 一字跌停 9.0 <= stop 9.6 → pending
        _bar("2026-01-04", 10.2, 10.3, 10.1, 10.25),  # T+3: recovery open=10.2 > stop → pending fill open
        _bar("2026-01-05", 10.1, 10.2, 10.0, 10.15),  # T+4
    ]
    pr = path_return(_make_trades(entry), bars, stop_pct, 8.0, 3, apply_cost=False)
    assert pr is not None
    assert pr.exit_reason == "stop"  # bug 时会 max_hold
    assert pr.exit_date == "2026-01-04"  # T+3
    assert pr.exit_price == pytest.approx(10.2, abs=0.001)  # pending fill at T+3 open
    assert pr.gross_return_pct == pytest.approx(2.0, abs=0.01)  # (10.2-10)/10*100 = +2.0%


def test_take_profit_unchanged_by_stop_fix():
    """S201b stage 2: take-side 不碰（limit sell 触及即成交，fill 在限价水平已 realistic）。

    verdict #3：take gap-through 会高估盈利=制造假 robust_edge。只修 stop-side。
    """
    entry = 10.0
    bars = [
        _bar("2026-01-01", 10.0, 10.2, 9.8, 10.1),   # signal
        _bar("2026-01-02", 10.0, 10.3, 9.9, 10.2),    # T+1 entry
        _bar("2026-01-03", 10.5, 10.9, 10.4, 10.8),   # T+2: high=10.9 >= take_level=10.8 → take
        _bar("2026-01-04", 9.7, 10.0, 9.5, 9.8),      # T+3
    ]
    pr = path_return(_make_trades(entry), bars, -4.0, 8.0, 3, apply_cost=False)
    assert pr is not None
    assert pr.exit_reason == "take"
    # take gross 仍是硬编码 take_profit_pct=8.0（不变）
    assert pr.gross_return_pct == pytest.approx(8.0, abs=0.01)
    assert pr.exit_price == pytest.approx(10.8, abs=0.001)


def test_cost_caliber_unified_no_hardcoded_0_70():
    """S201b 回归：accounting.py 不残留 0.70 作 ROUND_TRIP_COST_PCT 值。

    0.70 是旧美股假设 spread 0.60% + slippage 0.10%，已降为 0.15。
    """
    assert ROUND_TRIP_COST_PCT != 0.70
    assert ROUND_TRIP_COST_PCT == 0.15
