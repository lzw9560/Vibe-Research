# -*- coding: utf-8 -*-
"""P0-3 DSR/PBO/haircut/MinTRL 过拟合防护模块测试（从 skill-backtest-overfit fork，Bailey & Lopez de Prado 2014 文献实现）。"""
import numpy as np
from s44_verifier.overfit import (
    deflated_sharpe_ratio,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)
from s44_verifier.pbo import probability_of_backtest_overfitting
from s44_verifier.haircut import haircut_sharpe


def test_sharpe_ratio_basic():
    """正收益 → 正 Sharpe。"""
    r = np.array([0.01, 0.02, -0.01, 0.005, 0.015])
    assert sharpe_ratio(r) > 0


def test_sharpe_ratio_empty():
    """空/单元素 → nan。"""
    assert np.isnan(sharpe_ratio(np.array([])))
    assert np.isnan(sharpe_ratio(np.array([0.01])))


def test_psr_high_sr_high_prob():
    """高 SR + 大样本 → PSR 接近 1。"""
    psr = probabilistic_sharpe_ratio(observed_sr=2.0, benchmark_sr=0.0, n_obs=252, skew=0.0, kurtosis=3.0)
    assert psr > 0.95


def test_psr_low_sr_low_prob():
    """低 SR + 小样本 → PSR < 高 SR 大样本的 PSR。"""
    psr_low = probabilistic_sharpe_ratio(observed_sr=0.2, benchmark_sr=0.0, n_obs=10, skew=0.0, kurtosis=3.0)
    psr_high = probabilistic_sharpe_ratio(observed_sr=2.0, benchmark_sr=0.0, n_obs=252, skew=0.0, kurtosis=3.0)
    assert psr_low < psr_high


def test_dsr_deflated():
    """DSR with n_trials>1 → deflated（扣选择偏差，DSR < PSR）。"""
    r = np.random.RandomState(42).normal(0.001, 0.02, 252)
    result = deflated_sharpe_ratio(strategy_returns=r, n_trials=100)
    assert result.psr_vs_zero < 1.0
    assert result.deflated_sharpe_ratio <= result.psr_vs_zero  # DSR <= PSR（扣选择偏差）


def test_mintrl_basic():
    """MinTRL > 0（需要 N 期才显著）。"""
    mtrl = minimum_track_record_length(observed_sr=1.0, benchmark_sr=0.0, skew=0.0, kurtosis=3.0, confidence=0.95)
    assert mtrl > 0
    assert mtrl < 10000


def test_pbo_range():
    """PBO 在 [0,1]。"""
    rng = np.random.RandomState(42)
    trials = rng.normal(0, 0.01, (100, 50))
    result = probability_of_backtest_overfitting(trials)
    assert 0.0 <= result.pbo <= 1.0


def test_haircut_discount():
    """haircut Sharpe <= original（多重检验折扣）。"""
    result = haircut_sharpe(observed_sharpe_per_period=0.1, n_obs=252, n_tests=100, method="bonferroni")
    assert result.adjusted_sharpe <= 0.1
