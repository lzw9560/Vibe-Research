# -*- coding: utf-8 -*-
"""S202 IC/IR + get_kline + 行业中性化 测试。"""
from __future__ import annotations

import numpy as np
import pytest

from s44_verifier.ic_ir import (
    get_kline,
    compute_ic,
    compute_ic_ir,
    _newey_west_std,
    layered_backtest,
    ic_ir_verdict,
    industry_demean,
    industry_neutralize,
)


# ── get_kline ──────────────────────────────────────────────────────────────

def test_get_kline_empty_code():
    assert get_kline("") == []
    assert get_kline("   ") == []


def test_get_kline_invalid_freq():
    assert get_kline("600519", freq="1min") == []


def test_get_kline_returns_list():
    """baostock 可能未装——返 [] 不崩。"""
    bars = get_kline("600519", start="2026-01-01", end="2026-01-10")
    assert isinstance(bars, list)


# ── compute_ic ──────────────────────────────────────────────────────────────

def test_compute_ic_perfect_positive():
    fv = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    fr = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    ic = compute_ic(fv, fr)
    assert ic > 0.9  # 完美正相关


def test_compute_ic_perfect_negative():
    fv = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    fr = np.array([0.05, 0.04, 0.03, 0.02, 0.01])
    ic = compute_ic(fv, fr)
    assert ic < -0.9


def test_compute_ic_too_few():
    assert compute_ic(np.array([1.0, 2.0]), np.array([0.1, 0.2])) == 0.0


def test_compute_ic_with_nan():
    fv = np.array([1.0, np.nan, 3.0, 4.0, 5.0, 6.0])
    fr = np.array([0.01, 0.02, np.nan, 0.04, 0.05, 0.06])
    ic = compute_ic(fv, fr)
    assert isinstance(ic, float)


# ── Newey-West HAC std ─────────────────────────────────────────────────────

def test_newey_west_std_basic():
    series = [0.01, 0.02, 0.03, 0.04, 0.05]
    std = _newey_west_std(series)
    assert std > 0


def test_newey_west_std_too_short():
    assert _newey_west_std([0.01]) == 0.0


# ── compute_ic_ir ──────────────────────────────────────────────────────────

def test_ic_ir_positive():
    ics = [0.04, 0.05, 0.03, 0.06, 0.04, 0.05, 0.03, 0.06, 0.04, 0.05]
    ir, std = compute_ic_ir(ics)
    assert ir > 0
    assert std > 0


def test_ic_ir_too_short():
    ir, std = compute_ic_ir([0.01])
    assert ir == 0.0 and std == 0.0


# ── layered_backtest ──────────────────────────────────────────────────────

def test_layered_monotonic_up():
    fv = np.arange(50, dtype=float)
    fr = np.arange(50, dtype=float) * 0.001  # 单调递增
    result = layered_backtest(fv, fr, n_groups=5)
    assert result["monotonic"] is True
    assert result["group_means"][-1] > result["group_means"][0]


def test_layered_no_monotonic():
    np.random.seed(42)
    fv = np.random.rand(50)
    fr = np.random.rand(50)
    result = layered_backtest(fv, fr, n_groups=5)
    assert isinstance(result["monotonic"], bool)
    assert len(result["group_means"]) == 5


def test_layered_too_few():
    result = layered_backtest(np.array([1.0, 2.0]), np.array([0.1, 0.2]), n_groups=5)
    assert result["monotonic"] is False


# ── ic_ir_verdict ──────────────────────────────────────────────────────────

def test_verdict_strong_factor():
    ics = [0.05] * 30
    v = ic_ir_verdict(ics, 30)
    assert v["verdict"] == "strong_factor"
    assert v["mean_ic"] > 0.03


def test_verdict_weak_low_ic():
    ics = [0.01] * 30
    v = ic_ir_verdict(ics, 30)
    assert v["verdict"] == "weak_or_noise"


def test_verdict_insufficient_panels():
    ics = [0.05] * 10
    v = ic_ir_verdict(ics, 10)
    assert v["verdict"] == "weak_or_noise"


# ── industry_demean / neutralize ──────────────────────────────────────────

def test_industry_demean_basic():
    fv = np.array([10.0, 12.0, 5.0, 7.0, 20.0, 22.0])
    ind = np.array(["电子", "电子", "医药", "医药", "金融", "金融"])
    res = industry_demean(fv, ind)
    # 电子 median=11, 医药 median=6, 金融 median=21
    assert abs(res[0] - (-1.0)) < 0.01  # 10-11
    assert abs(res[2] - (-1.0)) < 0.01  # 5-6
    assert abs(res[4] - (-1.0)) < 0.01  # 20-21


def test_industry_demean_single_industry():
    fv = np.array([1.0, 2.0, 3.0])
    ind = np.array(["all", "all", "all"])
    res = industry_demean(fv, ind)
    assert abs(res.sum()) < 0.01  # demean 后和≈0


def test_industry_neutralize_with_size():
    fv = np.array([10.0, 12.0, 5.0, 7.0, 20.0, 22.0])
    ind = np.array(["A", "A", "B", "B", "C", "C"])
    size = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    res = industry_neutralize(fv, ind, size_proxy=size)
    assert len(res) == len(fv)
    # 不全 NaN
    assert not np.all(np.isnan(res))


def test_industry_neutralize_no_size():
    fv = np.array([10.0, 12.0, 5.0, 7.0])
    ind = np.array(["A", "A", "B", "B"])
    res = industry_neutralize(fv, ind, size_proxy=None)
    assert len(res) == 4
