# -*- coding: utf-8 -*-
"""S017 P1-c 数据交叉验证误差门控单测。

落地 financial-data skill 的交叉验证契约：误差≤1% 取主源、1-5% 标记差异、
>5% 重大差异须查原始财报。纯函数、无网络、可复算。
"""
from data.validators import cross_validate, error_rate_pct, Verdict


def test_error_rate_pct_basic():
    assert error_rate_pct(100.0, 99.0) == 1.0
    assert error_rate_pct(100.0, 100.0) == 0.0


def test_error_rate_pct_handles_zero_primary():
    """主源为 0 时分母为 0 → 返回 None（不臆造，不除零）。"""
    assert error_rate_pct(0.0, 1.0) is None
    assert error_rate_pct(0.0, 0.0) is None


def test_cross_validate_consistent_within_1pct():
    """两源误差≤1% → 一致，取主源值。"""
    r = cross_validate(field="revenue", values={"sina": 100.0, "eastmoney": 99.5})
    assert r.verdict == Verdict.CONSISTENT
    assert r.adopted_value == 100.0
    assert r.max_deviation_pct == 0.5
    assert r.adopted_source == "sina"


def test_cross_validate_difference_1_to_5pct():
    """1-5% → 数据存在差异，注明两值，取主源但标记。"""
    r = cross_validate(field="net_profit", values={"sina": 100.0, "eastmoney": 96.0})
    assert r.verdict == Verdict.DIFFERENCE
    assert r.max_deviation_pct == 4.0
    assert r.adopted_value == 100.0


def test_cross_validate_major_over_5pct():
    """>5% → 重大差异，adopted=None（不得直接使用，须查原始财报）。"""
    r = cross_validate(field="roe", values={"sina": 100.0, "eastmoney": 50.0})
    assert r.verdict == Verdict.MAJOR_DIFFERENCE
    assert r.max_deviation_pct == 50.0
    assert r.adopted_value is None


def test_cross_validate_single_source_auto_consistent():
    """单一来源（无可交叉源）→ 标记 single_source，采用该源值。"""
    r = cross_validate(field="eps", values={"sina": 21.76})
    assert r.verdict == Verdict.SINGLE_SOURCE
    assert r.adopted_value == 21.76
    assert r.adopted_source == "sina"


def test_cross_validate_none_values_skipped():
    """None 值（源无该字段）跳过；仅一个有效源 → single_source。"""
    r = cross_validate(field="revenue", values={"sina": 100.0, "eastmoney": None})
    assert r.verdict == Verdict.SINGLE_SOURCE
    assert r.adopted_value == 100.0


def test_cross_validate_all_none_returns_unknown():
    r = cross_validate(field="revenue", values={"sina": None, "eastmoney": None})
    assert r.verdict == Verdict.UNKNOWN
    assert r.adopted_value is None


def test_cross_validate_three_sources_uses_max_deviation():
    """三源时取最大两源偏差定档，采用主源（第一个有效源）值。"""
    r = cross_validate(field="assets",
                       values={"sina": 100.0, "eastmoney": 99.0, "cninfo": 92.0})
    # 偏差：sina-eastmoney=1%, sina-cninfo=8%, eastmoney-cninfo=7.x%
    assert r.max_deviation_pct == 8.0  # sina vs cninfo
    assert r.verdict == Verdict.MAJOR_DIFFERENCE
