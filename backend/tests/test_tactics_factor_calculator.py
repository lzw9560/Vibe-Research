# -*- coding: utf-8 -*-
"""test_tactics_factor_calculator —— 反量化战法因子计算+归一化测试（S235 T10）。

覆盖 spec §5.2 + tasks T10 钉死的边界值。AAA 结构。

注：conftest.py 已把 backend/ 加进 sys.path，tactics 是包（有 __init__.py），
故直接 `from tactics.factor_calculator import`。
"""
from __future__ import annotations
import math

from tactics.factor_calculator import (
    calc_vwap,
    calc_turnover_rate,
    calc_vol_ratio,
    calc_amount_ratio,
    calc_close_position,
    calc_prev_drop,
    normalize_factor,
)


def _approx(a: float, b: float, tol: float = 1e-4) -> bool:
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


# ---------------------------------------------------------------------------
# calc_vwap
# ---------------------------------------------------------------------------

def test_vwap_typical():
    # Arrange: O=10 H=11 L=9 C=10.5 → (10+11+9+2*10.5)/4 = 51/4 = 12.75
    # 注：plan 公式 (O+H+L+2C)/4 当 OHLC 全相等时=1.25×price（非 price 自身），
    # 因权重和=5 而除数=4。此为 plan.md 草案公式，S235 完成时提请用户复核是否应改 /5。
    snap = {"open_price": 10, "high_price": 11, "low_price": 9, "close_price": 10.5}
    # Act
    v = calc_vwap(snap)
    # Assert
    assert _approx(v, 12.75)


def test_vwap_all_high_edge():
    # 全高价：O=H=L=C=20 → (20+20+20+40)/4 = 100/4 = 25（=1.25×20）
    snap = {"open_price": 20, "high_price": 20, "low_price": 20, "close_price": 20}
    assert _approx(calc_vwap(snap), 25.0)


def test_vwap_all_low_edge():
    # 全低价：O=H=L=C=5 → (5+5+5+10)/4 = 25/4 = 6.25（=1.25×5，同上公式特性）
    snap = {"open_price": 5, "high_price": 5, "low_price": 5, "close_price": 5}
    assert _approx(calc_vwap(snap), 6.25)


def test_vwap_missing_fields():
    # 缺字段按 0
    assert _approx(calc_vwap({}), 0.0)


# ---------------------------------------------------------------------------
# calc_turnover_rate
# ---------------------------------------------------------------------------

def test_turnover_rate_basic():
    # amount=1.2e8, float_mv=1e9 → 0.12
    snap = {"amount": 1.2e8}
    assert _approx(calc_turnover_rate(snap, float_mv=1e9), 0.12)


def test_turnover_rate_from_snapshot_mv():
    snap = {"amount": 2e8, "float_mv": 1e9}
    assert _approx(calc_turnover_rate(snap), 0.20)


def test_turnover_rate_zero_mv_returns_zero():
    assert calc_turnover_rate({"amount": 1e8}, float_mv=0) == 0.0
    assert calc_turnover_rate({"amount": 1e8}) == 0.0


# ---------------------------------------------------------------------------
# calc_vol_ratio
# ---------------------------------------------------------------------------

def test_vol_ratio_at_anchor():
    # 竞价量 4500，5日开盘均量 1000 → 4.5
    auction = {"volume": 4500}
    assert _approx(calc_vol_ratio(auction, [1000, 1000, 1000, 1000, 1000]), 4.5)


def test_vol_ratio_2x():
    # 2.0 → 归一化 0.44
    auction = {"volume": 2000}
    vr = calc_vol_ratio(auction, [1000, 1000, 1000, 1000, 1000])
    assert _approx(vr, 2.0)
    assert _approx(normalize_factor("vol_ratio", vr), 0.4444, tol=1e-3)


def test_vol_ratio_empty_prev():
    assert calc_vol_ratio({"volume": 100}, []) == 0.0


# ---------------------------------------------------------------------------
# calc_amount_ratio
# ---------------------------------------------------------------------------

def test_amount_ratio_at_anchor():
    # 竞价额 1e7, 前日成交额 1e8 → 0.10
    auction = {"amount": 1e7}
    assert _approx(calc_amount_ratio(auction, 1e8), 0.10)
    assert _approx(normalize_factor("amount_ratio", 0.10), 1.0)


def test_amount_ratio_zero_prev():
    assert calc_amount_ratio({"amount": 1e7}, 0) == 0.0


# ---------------------------------------------------------------------------
# calc_close_position
# ---------------------------------------------------------------------------

def test_close_position_at_anchor():
    # 0.7 → 归一化 1.0
    snap = {"low_price": 0, "high_price": 10, "close_price": 7}
    cp = calc_close_position(snap)
    assert _approx(cp, 0.7)
    assert _approx(normalize_factor("close_position", cp), 1.0)


def test_close_position_03():
    # 0.3 → 归一化 0.43
    snap = {"low_price": 0, "high_price": 10, "close_price": 3}
    cp = calc_close_position(snap)
    assert _approx(cp, 0.3)
    assert _approx(normalize_factor("close_position", cp), 0.4286, tol=1e-3)


def test_close_position_one_word_board():
    # 一字板 H==L → 1.0
    snap = {"low_price": 10, "high_price": 10, "close_price": 10}
    assert calc_close_position(snap) == 1.0


# ---------------------------------------------------------------------------
# calc_prev_drop
# ---------------------------------------------------------------------------

def test_prev_drop_5pct():
    # 前日 close 9.5 vs prev 10 → -0.05
    klines = [{"close_price": 10}, {"close_price": 9.5}]
    assert _approx(calc_prev_drop(klines), -0.05)
    assert normalize_factor("prev_drop", -0.05) == 1.0  # gate 满足


def test_prev_drop_below_threshold():
    # 跌 3% → gate 不满足
    klines = [{"close_price": 10}, {"close_price": 9.7}]
    assert _approx(calc_prev_drop(klines), -0.03)
    assert normalize_factor("prev_drop", -0.03) == 0.0


def test_prev_drop_insufficient_klines():
    assert calc_prev_drop([{"close_price": 9.5}]) == 0.0
    assert calc_prev_drop([]) == 0.0


# ---------------------------------------------------------------------------
# normalize_factor 边界（gap_pct plateau + turnover_rate 区间）
# ---------------------------------------------------------------------------

def test_gap_pct_plateau_2_to_5_full():
    # spec T10: 2→1.0, 5→1.0, 1→0, 6→0
    assert _approx(normalize_factor("gap_pct", 2.0), 1.0)
    assert _approx(normalize_factor("gap_pct", 3.5), 1.0)
    assert _approx(normalize_factor("gap_pct", 5.0), 1.0)


def test_gap_pct_decay_edges():
    assert _approx(normalize_factor("gap_pct", 1.0), 0.0)
    assert _approx(normalize_factor("gap_pct", 6.0), 0.0)


def test_gap_pct_outside_clamped():
    assert normalize_factor("gap_pct", 0.0) == 0.0
    assert normalize_factor("gap_pct", 7.0) == 0.0


def test_turnover_rate_plateau():
    # 12-22% → 1.0
    assert _approx(normalize_factor("turnover_rate", 0.12), 1.0)
    assert _approx(normalize_factor("turnover_rate", 0.17), 1.0)
    assert _approx(normalize_factor("turnover_rate", 0.22), 1.0)


def test_turnover_rate_decay():
    # <12% 线性上升（floor 6%）；>22% 线性下降（ceil 30%）
    assert _approx(normalize_factor("turnover_rate", 0.06), 0.0)
    assert normalize_factor("turnover_rate", 0.30) == 0.0
    # 9% 介于 6-12 → (9-6)/(12-6)=0.5
    assert _approx(normalize_factor("turnover_rate", 0.09), 0.5)
    # 26% 介于 22-30 → (30-26)/(30-22)=0.5
    assert _approx(normalize_factor("turnover_rate", 0.26), 0.5)


def test_unknown_factor_returns_zero():
    assert normalize_factor("nonexistent_factor", 999) == 0.0


def test_normalize_none_value():
    assert normalize_factor("vol_ratio", None) == 0.0
    assert normalize_factor("gap_pct", "not-a-number") == 0.0


# ---------------------------------------------------------------------------
# gate 类硬条件
# ---------------------------------------------------------------------------

def test_gate_factors_bool():
    assert normalize_factor("above_vwap", True) == 1.0
    assert normalize_factor("above_vwap", False) == 0.0
    assert normalize_factor("ice_point", True) == 1.0
    assert normalize_factor("ice_point", False) == 0.0
    assert normalize_factor("bid_increasing", 1) == 1.0
    assert normalize_factor("bid_increasing", 0) == 0.0


# ---------------------------------------------------------------------------
# breakout_high / sector_resonance / 降级因子
# ---------------------------------------------------------------------------

def test_breakout_high_full():
    assert normalize_factor("breakout_high", 0.995) == 1.0
    assert normalize_factor("breakout_high", 1.0) == 1.0


def test_breakout_high_partial():
    # 0.80 → 用比值
    assert _approx(normalize_factor("breakout_high", 0.80), 0.80)


def test_sector_resonance():
    assert _approx(normalize_factor("sector_resonance", 2), 1.0)
    assert _approx(normalize_factor("sector_resonance", 1), 0.5)


def test_proxy_factors_clamped():
    assert _approx(normalize_factor("big_order_proxy", 0.6), 0.6)
    assert normalize_factor("big_order_proxy", 1.5) == 1.0
    assert normalize_factor("big_order_proxy", -0.3) == 0.0
