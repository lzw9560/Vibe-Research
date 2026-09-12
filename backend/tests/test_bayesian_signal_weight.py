# -*- coding: utf-8 -*-
"""S194 R3 · bayesian_signal_weight 单测——Beta-Bernoulli 后验权重 + underpowered 分级。

纯函数 beta_bernoulli_weight：Beta-Bernoulli 共轭后验均值（闭式，无 scipy）= 信号 reliability 权重。
延伸 S180 bayesian_arm_size 的 Beta-Bernoulli 模式——arm_size 用 ppf(0.05) 保守仓位 sizing，
signal_weight 用后验均值作融合权重（spec §3 R3「每信号先验→后验权重」）。

BayesianSignalWeight 类：per-signal 专家先验 + weight/weights 方法。
reliability_tier：复刻 §44v2 underpowered 分级（n<30 insufficient 先验主导 / n_days<60 underpowered 不判 / ≥60 robust）。
"""
from __future__ import annotations

import math

from engine.bayesian_signal_weight import (
    BayesianSignalWeight,
    beta_bernoulli_weight,
    reliability_tier,
)


class TestBetaBernoulliWeight:
    def test_no_data_returns_prior_mean(self):
        """无数据（0 succ 0 fail）→ 后验=先验，Beta(1,1) 均值 0.5（中性，先验主导）。"""
        assert beta_bernoulli_weight(0, 0) == 0.5

    def test_all_success_high_weight(self):
        """10 succ 0 fail → (1+10)/(1+1+10+0)=11/12≈0.917（数据主导，高 reliability）。"""
        assert math.isclose(beta_bernoulli_weight(10, 0), 11 / 12, rel_tol=1e-9)

    def test_all_fail_low_weight(self):
        """0 succ 10 fail → (1+0)/(1+1+0+10)=1/12≈0.083（低 reliability）。"""
        assert math.isclose(beta_bernoulli_weight(0, 10), 1 / 12, rel_tol=1e-9)

    def test_symmetric_success_fail_neutral(self):
        """5 succ 5 fail → (1+5)/(1+1+5+5)=6/12=0.5（对称，中性）。"""
        assert beta_bernoulli_weight(5, 5) == 0.5

    def test_one_positive_trial_slight_uptick(self):
        """1 succ 0 fail → 2/3≈0.667（一次正试验，从 0.5 略升，少样本先验仍拉向 0.5）。"""
        assert math.isclose(beta_bernoulli_weight(1, 0), 2 / 3, rel_tol=1e-9)

    def test_informative_prior_pulls_toward_prior(self):
        """Beta(2,2) 先验（峰在 0.5）+ 10 succ 0 fail → 12/14≈0.857（先验把极端数据拉回 0.5）。"""
        assert math.isclose(beta_bernoulli_weight(10, 0, prior_alpha=2.0, prior_beta=2.0), 12 / 14, rel_tol=1e-9)

    def test_conservative_prior_biases_low(self):
        """Beta(1,3) 先验（偏悲观）+ 0 数据 → 1/4=0.25（专家先验主导，无数据时低权重）。"""
        assert beta_bernoulli_weight(0, 0, prior_alpha=1.0, prior_beta=3.0) == 0.25

    def test_data_overwhelms_prior_with_enough_n(self):
        """100 succ 0 fail + Beta(1,3) → 101/104≈0.971（数据够多后验压过先验）。"""
        assert math.isclose(beta_bernoulli_weight(100, 0, prior_alpha=1.0, prior_beta=3.0), 101 / 104, rel_tol=1e-9)


class TestReliabilityTier:
    def test_insufficient_sample(self):
        """n<30 → insufficient（先验主导，spec §44v2）。"""
        assert reliability_tier(n_total=10, n_days=5) == "insufficient"

    def test_underpowered(self):
        """n≥30 但 n_days<60 → underpowered（探索性不判冗余）。"""
        assert reliability_tier(n_total=40, n_days=35) == "underpowered"

    def test_robust(self):
        """n≥30 且 n_days≥60 → robust（可判）。"""
        assert reliability_tier(n_total=200, n_days=64) == "robust"

    def test_insufficient_short_circuits_regardless_of_days(self):
        """n<30 即使 n_days 大也 insufficient（样本太少先验主导）。"""
        assert reliability_tier(n_total=20, n_days=120) == "insufficient"

    def test_boundary_n30_underpowered(self):
        """n=30 边界 → underpowered（n≥30 进 underpowered 分支，n_days<60）。"""
        assert reliability_tier(n_total=30, n_days=40) == "underpowered"

    def test_boundary_n_days60_robust(self):
        """n_days=60 边界 → robust（≥60）。"""
        assert reliability_tier(n_total=50, n_days=60) == "robust"


class TestBayesianSignalWeight:
    def test_default_prior_beta_1_1(self):
        """无 priors 配置 → 默认 Beta(1,1)，weight(0,0)=0.5。"""
        bsw = BayesianSignalWeight()
        assert bsw.weight("gap", 0, 0) == 0.5

    def test_per_signal_prior_used(self):
        """priors={'breakout': (2,2)} → breakout 用 Beta(2,2) 先验。"""
        bsw = BayesianSignalWeight(priors={"breakout": (2.0, 2.0)})
        assert bsw.weight("breakout", 0, 0) == 0.5  # 2/4
        assert math.isclose(bsw.weight("breakout", 10, 0), 12 / 14, rel_tol=1e-9)

    def test_unconfigured_signal_falls_back_default(self):
        """未配先验的信号 → 默认 Beta(1,1)。"""
        bsw = BayesianSignalWeight(priors={"breakout": (2.0, 2.0)})
        assert bsw.weight("ofi", 10, 0) == 11 / 12  # ofi 用默认 Beta(1,1)

    def test_weights_batch(self):
        """weights({signal: (succ, fail)}) → {signal: weight} 批量产出（spec §3 R3 输出）。"""
        bsw = BayesianSignalWeight(priors={"breakout": (2.0, 2.0)})
        out = bsw.weights({"gap": (10, 0), "ofi": (0, 0), "breakout": (5, 5)})
        assert set(out.keys()) == {"gap", "ofi", "breakout"}
        assert math.isclose(out["gap"], 11 / 12, rel_tol=1e-9)
        assert out["ofi"] == 0.5
        assert out["breakout"] == 0.5  # (2+5)/(2+2+5+5)=7/14

    def test_weights_empty(self):
        """空 reliability → 空 weights。"""
        assert BayesianSignalWeight().weights({}) == {}
