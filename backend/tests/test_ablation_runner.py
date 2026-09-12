# -*- coding: utf-8 -*-
"""S194 R5 · ablation_runner v2 单测——融合分消融（adversarial verify 后重设计）。

v1（feature=值×权重 喂 ML）被 verify 报 CRITICAL：权重是 per-signal 常量，喂 ML 模型
（StandardScaler + 树阈值）被数学吃掉，模型看不见权重 → 测的是信号值本身预测力（= multifactor null
弱化重测），非 FS2 权重贡献。

v2：fusion_score = Σ(value×weight) 单一融合分（权重直接乘数）；消融 weight_j=0 → 看 IC 掉多少；
per-fold walk-forward（train-fold 算权重防 lookahead）+ delta 置换 p 值 + 跨信号 Bonferroni +
underpowered 区分 harmful/模糊 + 1 信号/0 折边界 guard。
"""
from __future__ import annotations

import numpy as np

from tools.ablation_runner import (
    ablate_fusion_composite,
    build_fusion_composite,
    composite_ablation_verdict,
    run_composite_ablation,
)


class TestBuildFusionComposite:
    def test_composite_is_weighted_sum(self):
        """fusion_score = Σ(value × weight)：2 信号 case {a:0.8,b:0.9} + weights {a:0.7,b:0.5} → 0.56+0.45=1.01。"""
        cases = [{"a": 0.8, "b": 0.9}, {"a": 0.6, "b": 0.4}]
        weights = {"a": 0.7, "b": 0.5}
        comp = build_fusion_composite(cases, weights)
        assert np.isclose(comp[0], 0.8 * 0.7 + 0.9 * 0.5)  # 1.01
        assert np.isclose(comp[1], 0.6 * 0.7 + 0.4 * 0.5)  # 0.62

    def test_missing_signal_value_treated_zero(self):
        """case 缺某信号 → 该项 0（信号未触发）。"""
        cases = [{"a": 0.8}, {"b": 0.9}]
        weights = {"a": 0.7, "b": 0.5}
        comp = build_fusion_composite(cases, weights)
        assert np.isclose(comp[0], 0.8 * 0.7)  # b 缺 → 0
        assert np.isclose(comp[1], 0.9 * 0.5)  # a 缺 → 0

    def test_ablate_zeros_target_weight(self):
        """ablate signal a → a 的权重设 0，融合分只剩 b 的贡献。"""
        cases = [{"a": 0.8, "b": 0.9}]
        weights = {"a": 0.7, "b": 0.5}
        full = build_fusion_composite(cases, weights)
        ablated = ablate_fusion_composite(cases, weights, "a")
        assert np.isclose(ablated[0], 0.9 * 0.5)  # a 权重 0 → 只剩 b
        assert np.isclose(full[0] - ablated[0], 0.8 * 0.7)  # a 的贡献差


class TestRunCompositeAblation:
    def test_delta_ic_computed_with_mock_ic(self):
        """注入 ic_fn 返 canned IC，验 delta = full_ic - ablated_ic per fold。"""
        cases = [{"a": 0.8, "b": 0.9}, {"a": 0.6, "b": 0.4}, {"a": 0.7, "b": 0.8}]
        weights = {"a": 0.7, "b": 0.5}
        outcomes = [0.01, -0.02, 0.03]
        dates = ["d1", "d2", "d3"]
        # mock ic: full=0.10, ablated=0.05 → delta=+0.05 per fold
        call_count = [0]
        def mock_ic(scores, y):
            call_count[0] += 1
            return 0.10 if call_count[0] % 2 == 1 else 0.05  # 交替 full/ablated
        r = run_composite_ablation(cases, weights, outcomes, dates, "a", ic_fn=mock_ic)
        assert np.isclose(r["delta_ic"], 0.05)
        assert r["n_folds"] == 3

    def test_one_signal_graceful_no_crash(self):
        """仅 1 信号消融：ablated 融合分全 0（权重设 0），IC=0，delta=full_ic，不崩（v1 会崩）。"""
        cases = [{"a": 0.8}, {"a": 0.6}]
        weights = {"a": 0.7}
        def mock_ic(scores, y):
            return 0.10 if any(s != 0 for s in scores) else 0.0
        r = run_composite_ablation(cases, weights, [0.01, 0.02], ["d1", "d2"], "a", ic_fn=mock_ic)
        assert r["n_folds"] == 2  # 没崩
        assert np.isclose(r["delta_ic"], 0.10)  # full=0.10, ablated=0 → delta=0.10

    def test_reliability_fn_called_per_fold_with_train_mask(self):
        """reliability_fn 注入 → 每 fold 用 train-fold 数据算权重（防 lookahead）。"""
        cases = [{"a": 0.8}, {"a": 0.6}, {"a": 0.7}]
        weights = {"a": 0.5}
        reliability_calls = []
        def rel_fn(train_cases):
            reliability_calls.append(len(train_cases))
            return {"a": 0.5}  # 简化：返同权重
        def mock_ic(scores, y):
            return 0.10
        run_composite_ablation(cases, weights, [0.01, 0.02, 0.03], ["d1", "d2", "d3"], "a",
                               ic_fn=mock_ic, reliability_fn=rel_fn)
        assert len(reliability_calls) == 3  # 3 fold 各调一次
        # 每 fold train = 除该日外全部（leave-one-day-out）
        assert reliability_calls[0] == 2  # d1 fold: train d2+d3 = 2 case


class TestCompositeAblationVerdict:
    def test_robust_contributes(self):
        """robust + delta>0 + delta_pval<alpha/K → contributes。"""
        v = composite_ablation_verdict(delta_ic=0.05, delta_pval=0.001, n_total=200, n_days=64, K=4)
        assert v["verdict"] == "contributes"
        assert v["adjusted_alpha"] < 0.0125  # alpha/K 缩了

    def test_robust_harmful(self):
        """robust + delta<0 + 显著 → harmful（移除后预测力升，信号有害）。"""
        v = composite_ablation_verdict(delta_ic=-0.05, delta_pval=0.001, n_total=200, n_days=64, K=4)
        assert v["verdict"] == "harmful"

    def test_robust_no_contribution_when_delta_non_significant(self):
        """robust + delta 非显著 → no_contribution（不判冗余也不判贡献）。"""
        v = composite_ablation_verdict(delta_ic=0.05, delta_pval=0.5, n_total=200, n_days=64, K=4)
        assert v["verdict"] == "no_contribution"

    def test_underpowered_exploratory_positive_delta(self):
        """underpowered + delta>0 → exploratory（正但样本不够，不判贡献）。"""
        v = composite_ablation_verdict(delta_ic=0.05, delta_pval=0.001, n_total=40, n_days=35, K=4)
        assert v["verdict"] == "exploratory"  # tier underpowered 不判贡献
        assert "正" in v["caveat"] or "+" in v["caveat"]  # 标 delta 方向

    def test_underpowered_distinguishes_harmful(self):
        """underpowered + delta<0 → exploratory_harmful（区分有害 vs 模糊，v1 一视同仁的 bug 修）。"""
        v = composite_ablation_verdict(delta_ic=-0.05, delta_pval=0.001, n_total=40, n_days=35, K=4)
        assert v["verdict"] == "exploratory_harmful"
        assert "负" in v["caveat"] or "-" in v["caveat"]

    def test_insufficient_exploratory(self):
        """n<30 → insufficient → exploratory（先验主导）。"""
        v = composite_ablation_verdict(delta_ic=0.05, delta_pval=0.001, n_total=10, n_days=5, K=4)
        assert v["tier"] == "insufficient"
        assert v["verdict"] == "exploratory"

    def test_cross_signal_bonferroni_shrinks_alpha(self):
        """K 信号 → adjusted_alpha = bonf_alpha/K（跨信号多重比较校正，v1 缺）。"""
        v4 = composite_ablation_verdict(0.05, 0.001, 200, 64, K=4)
        v8 = composite_ablation_verdict(0.05, 0.001, 200, 64, K=8)
        assert v8["adjusted_alpha"] < v4["adjusted_alpha"]  # K 越大 alpha 越严
