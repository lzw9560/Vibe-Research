# -*- coding: utf-8 -*-
"""S194 R5 · ablation_runner 单测——F1 消融矩阵 + delta + underpowered verdict。

纯逻辑测试（walk_forward_cv 注入 mock，不跑真模型——T5.3 实测才跑真 walk_forward_cv）：
- build_ablation_matrix：per-case 信号值 × FS2 权重 → X；缺信号→0；None outcome 跳过。
- run_signal_ablation：调 walk_forward_fn 两遍（full vs 去 target_signal 列）→ delta。
- ablation_verdict（T5.2）：reliability_tier underpowered gating + delta+pval → verdict（spec §44v2 小样本不判冗余）。
"""
from __future__ import annotations

import numpy as np

from tools.ablation_runner import (
    ablation_verdict,
    build_ablation_matrix,
    run_signal_ablation,
)


def _mock_walk_forward(canned_full: dict, canned_ablated: dict, call_log: list):
    """造一个 mock walk_forward_fn：按是否含 target_signal 列返 full 或 ablated stats，并记调用。"""

    def _fn(X, y, dates, feature_names, target_name):
        call_log.append({"X_shape": tuple(X.shape), "feature_names": list(feature_names)})
        # 若 feature_names 不含 target_signal（ablated）→ 返 ablated stats
        target = "breakout"  # 测试里固定 target
        if target not in feature_names:
            return dict(canned_ablated)
        return dict(canned_full)

    return _fn


class TestBuildAblationMatrix:
    def test_x_shape_and_weighted_values(self):
        """3 case × 2 signal，weights={gap:0.7,breakout:0.5} → X 3×2，X[i,j]=value×weight。"""
        cases = [
            {"gap": 0.8, "breakout": 0.9},
            {"gap": 0.6, "breakout": 0.4},
            {"gap": 0.7, "breakout": 0.95},
        ]
        weights = {"gap": 0.7, "breakout": 0.5}
        outcomes = [0.02, -0.01, 0.03]
        dates = ["2026-09-10", "2026-09-10", "2026-09-11"]
        X, y, dates_out, feat_names, target = build_ablation_matrix(cases, weights, outcomes, dates)
        assert X.shape == (3, 2)
        assert feat_names == ["gap", "breakout"]
        # X[0,0]=0.8×0.7=0.56, X[0,1]=0.9×0.5=0.45
        assert np.isclose(X[0, 0], 0.56)
        assert np.isclose(X[0, 1], 0.45)
        assert np.allclose(y, [0.02, -0.01, 0.03])
        assert dates_out == dates

    def test_missing_signal_value_defaults_zero(self):
        """case 缺某信号值 → 该列 0（信号未触发）。"""
        cases = [{"gap": 0.8}, {"breakout": 0.9}]  # case0 缺 breakout, case1 缺 gap
        weights = {"gap": 0.7, "breakout": 0.5}
        X, y, _, feat_names, _ = build_ablation_matrix(cases, weights, [0.01, 0.02], ["d1", "d2"])
        assert X[0, 1] == 0.0  # case0 breakout 缺 → 0
        assert X[1, 0] == 0.0  # case1 gap 缺 → 0

    def test_none_outcome_filtered(self):
        """outcome=None 的 case 跳过（不臆造 y）。"""
        cases = [{"gap": 0.8}, {"gap": 0.6}, {"gap": 0.7}]
        weights = {"gap": 0.7}
        outcomes = [0.01, None, 0.03]  # case1 None → 跳
        dates = ["d1", "d2", "d3"]
        X, y, dates_out, _, _ = build_ablation_matrix(cases, weights, outcomes, dates)
        assert X.shape == (2, 1)  # 只剩 2 case
        assert len(y) == 2
        assert dates_out == ["d1", "d3"]  # 跳 d2


class TestRunSignalAblation:
    def test_ablation_drops_target_column(self):
        """run_signal_ablation(target=breakout) → ablated 调用收到的 X 无 breakout 列。"""
        cases = [{"gap": 0.8, "breakout": 0.9}, {"gap": 0.6, "breakout": 0.4}]
        weights = {"gap": 0.7, "breakout": 0.5}
        X, y, dates, feat_names, target = build_ablation_matrix(cases, weights, [0.01, 0.02], ["d1", "d2"])
        call_log: list = []
        fn = _mock_walk_forward(
            canned_full={"Ridge": {"ic_mean": 0.10, "ic_pval": 0.001, "lift_mean": 1.5}},
            canned_ablated={"Ridge": {"ic_mean": 0.05, "ic_pval": 0.05, "lift_mean": 1.2}},
            call_log=call_log,
        )
        result = run_signal_ablation(X, y, dates, feat_names, "breakout", fn, target_name=target)
        assert len(call_log) == 2  # full + ablated
        # full 调用收 2 列
        assert call_log[0]["feature_names"] == ["gap", "breakout"]
        assert call_log[0]["X_shape"] == (2, 2)
        # ablated 调用收 1 列（去 breakout）
        assert call_log[1]["feature_names"] == ["gap"]
        assert call_log[1]["X_shape"] == (2, 1)

    def test_delta_ic_computed(self):
        """full ic_mean=0.10, ablated ic_mean=0.05 → delta_ic=+0.05（breakout 正贡献）。"""
        cases = [{"gap": 0.8, "breakout": 0.9}, {"gap": 0.6, "breakout": 0.4}]
        weights = {"gap": 0.7, "breakout": 0.5}
        X, y, dates, feat_names, target = build_ablation_matrix(cases, weights, [0.01, 0.02], ["d1", "d2"])
        call_log: list = []
        fn = _mock_walk_forward(
            canned_full={"Ridge": {"ic_mean": 0.10, "ic_pval": 0.001, "lift_mean": 1.5}},
            canned_ablated={"Ridge": {"ic_mean": 0.05, "ic_pval": 0.05, "lift_mean": 1.2}},
            call_log=call_log,
        )
        result = run_signal_ablation(X, y, dates, feat_names, "breakout", fn, target_name=target)
        assert np.isclose(result["delta_ic"]["Ridge"], 0.05)
        assert result["target_signal"] == "breakout"


class TestAblationVerdict:
    def test_insufficient_returns_exploratory(self):
        """n_total<30 → insufficient → verdict=exploratory（不判冗余）。"""
        full = {"Ridge": {"ic_mean": 0.10, "ic_pval": 0.001}}
        abl = {"Ridge": {"ic_mean": 0.05, "ic_pval": 0.05}}
        v = ablation_verdict(full, abl, n_total=10, n_days=5)
        assert v["tier"] == "insufficient"
        assert v["verdict"] == "exploratory"

    def test_underpowered_returns_exploratory(self):
        """n≥30 但 n_days<60 → underpowered → exploratory（复刻 §44v1 假阴性纠错）。"""
        full = {"Ridge": {"ic_mean": 0.10, "ic_pval": 0.001}}
        abl = {"Ridge": {"ic_mean": 0.05, "ic_pval": 0.05}}
        v = ablation_verdict(full, abl, n_total=40, n_days=35)
        assert v["tier"] == "underpowered"
        assert v["verdict"] == "exploratory"

    def test_robust_contributes(self):
        """robust + delta_ic>0 + full_pval<bonf → contributes。"""
        full = {"Ridge": {"ic_mean": 0.10, "ic_pval": 0.001}}
        abl = {"Ridge": {"ic_mean": 0.05, "ic_pval": 0.05}}
        v = ablation_verdict(full, abl, n_total=200, n_days=64)
        assert v["tier"] == "robust"
        assert v["verdict"] == "contributes"
        assert v["delta_ic"] > 0

    def test_robust_redundant_when_delta_negative(self):
        """robust + delta_ic≤0（移除后 IC 不降反升）→ redundant_or_harmful。"""
        full = {"Ridge": {"ic_mean": 0.05, "ic_pval": 0.001}}
        abl = {"Ridge": {"ic_mean": 0.10, "ic_pval": 0.05}}  # ablated 更高 → delta<0
        v = ablation_verdict(full, abl, n_total=200, n_days=64)
        assert v["verdict"] == "redundant_or_harmful"

    def test_robust_no_contribution_when_non_significant(self):
        """robust + delta>0 但 full_pval≥bonf（非显著）→ no_contribution。"""
        full = {"Ridge": {"ic_mean": 0.10, "ic_pval": 0.5}}  # 非显著
        abl = {"Ridge": {"ic_mean": 0.05, "ic_pval": 0.6}}
        v = ablation_verdict(full, abl, n_total=200, n_days=64)
        assert v["verdict"] == "no_contribution"

    def test_caveat_documents_underpowered(self):
        """exploratory verdict 的 caveat 标注 underpowered 原因（spec §44v2 诚实标注）。"""
        full = {"Ridge": {"ic_mean": 0.10, "ic_pval": 0.001}}
        abl = {"Ridge": {"ic_mean": 0.05, "ic_pval": 0.05}}
        v = ablation_verdict(full, abl, n_total=40, n_days=35)
        assert "underpowered" in v["caveat"]
        assert "不判" in v["caveat"]
