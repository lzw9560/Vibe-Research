# -*- coding: utf-8 -*-
"""S194 R5 · ablation_runner——F1 消融跑（只测 FS2，复用 multifactor walk-forward OOS 框架）。

spec §3 R5 + §4：ablation_runner 继承（实际是组合 import，非 OOP 继承）multifactor_combo_validation
的 walk-forward CV + Bonferroni + anti-feature-selection OOS 框架，FS2 权重作 feature 输入。

F1 消融只测 FS2（确定可 OOS，spec §2.1），FS1 AI 检索不参与（非确定，§44v2 verifier 套不上）。
跑法：full（含某信号 FS2 加权列）vs ablated（去该列）→ 对比 OOS ic_mean/ic_pval/lift_mean delta
= 该信号的增量贡献。⚠️ 统计功效约束（spec grill HIGH#4 + §6）：leave-one-out 小样本 n=1092
检测边际贡献功效低，须 underpowered 标「探索性不判冗余」（per §159 §44v2 应用规约，复刻 §44v1
假阴性纠错）—— ablation_verdict 套 reliability_tier tier gating。

feature 设计：feature[case, signal] = 信号值(case) × FS2 权重(signal) per-case。FS2 权重单独是
per-signal 常量无 per-case 方差 → 模型学不到（线性模型对常量缩放不敏感）；用「信号值 × 权重」
才有 per-case 方差。信号值由调用方从 trade_journal case 重建（重跑信号生成器，T5.3 实测时接），
本模块只接受重建后的 cases_signal_values + fs2_weights，不耦合信号源（YAGNI + 可单测）。

walk_forward_fn 注入：T5.1/T5.2 单测用 mock（不跑真模型）；T5.3 实测传 tools.multifactor_combo_validation.walk_forward_cv。
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from engine.bayesian_signal_weight import reliability_tier

# Bonferroni 校正阈值（与 multifactor_combo_validation.BONF_ALPHA=0.0125=0.05/4 一致）
BONF_ALPHA: float = 0.0125

# walk_forward_fn 签名（与 multifactor_combo_validation.walk_forward_cv 一致）
WalkForwardFn = Callable[[np.ndarray, np.ndarray, list[str], list[str], str], dict]


def build_ablation_matrix(
    cases_signal_values: list[dict],
    fs2_weights: dict[str, float],
    outcomes: list[float | None],
    dates: list[str],
    target_name: str = "fusion_return",
) -> tuple[np.ndarray, np.ndarray, list[str], list[str], str]:
    """per-case 信号值 × FS2 权重 → X 矩阵（喂 walk_forward_cv）。

    Args:
        cases_signal_values: per-case {signal_name: 信号值}（由调用方从 trade_journal 重建）。
        fs2_weights: {signal_name: FS2 后验权重}（来自 R3 bayesian_signal_weight）。
        outcomes: per-case 收益（y）；None 跳过该 case（不臆造，§1.2）。
        dates: per-case entry_date（walk-forward CV 按日 fold）。
        target_name: y 的语义标签。

    Returns:
        (X, y, dates_out, feature_names, target_name)。X 列序 = fs2_weights 键序；
        缺信号值→0（信号未触发该 case）；None outcome 的 case 全行跳过。
    """
    feature_names = list(fs2_weights.keys())
    # 过滤 None outcome（case + date + 信号值 三者同步跳）
    rows, ys, keep_dates = [], [], []
    for case_vals, y, d in zip(cases_signal_values, outcomes, dates):
        if y is None:
            continue
        row = [float(case_vals.get(sig, 0.0)) * fs2_weights[sig] for sig in feature_names]
        rows.append(row)
        ys.append(float(y))
        keep_dates.append(d)
    if not rows:
        return np.zeros((0, len(feature_names))), np.zeros(0), [], feature_names, target_name
    X = np.array(rows, dtype=float)
    y_arr = np.array(ys, dtype=float)
    return X, y_arr, keep_dates, feature_names, target_name


def run_signal_ablation(
    X: np.ndarray,
    y: np.ndarray,
    dates: list[str],
    feature_names: list[str],
    target_signal: str,
    walk_forward_fn: WalkForwardFn,
    target_name: str = "fusion_return",
) -> dict:
    """跑 F1 消融：full（含 target_signal 列）vs ablated（去该列）→ delta。

    调 walk_forward_fn 两遍（walk_forward_cv 注入，单测可 mock），对比每模型 ic_mean delta。
    delta_ic[model] = full[model].ic_mean - ablated[model].ic_mean（>0=信号正贡献，移除降 IC）。
    """
    full = walk_forward_fn(X, y, dates, feature_names, target_name)
    # 去掉 target_signal 列
    j = feature_names.index(target_signal)
    X_abl = np.delete(X, j, axis=1)
    feat_abl = [f for i, f in enumerate(feature_names) if i != j]
    ablated = walk_forward_fn(X_abl, y, dates, feat_abl, target_name)
    # delta per model（ablated 可能少模型，取交集）
    models = [m for m in full if m in ablated]
    delta_ic = {
        m: float(full[m].get("ic_mean", 0.0)) - float(ablated[m].get("ic_mean", 0.0))
        for m in models
    }
    return {
        "target_signal": target_signal,
        "full": full,
        "ablated": ablated,
        "delta_ic": delta_ic,
        "feature_names": list(feature_names),
    }


def ablation_verdict(
    full: dict,
    ablated: dict,
    n_total: int,
    n_days: int,
    bonf_alpha: float = BONF_ALPHA,
) -> dict:
    """F1 消融 verdict + underpowered gating（T5.2，spec §3 R5 + §6 风险）。

    tier = reliability_tier(n_total, n_days)（复刻 §44v2：n<30 insufficient / n_days<60 underpowered / ≥60 robust）。
    - insufficient/underpowered → verdict="exploratory"（小样本不判冗余，复刻 §44v1 假阴性纠错）；
    - robust + delta_ic>0 + full_pval<bonf → "contributes"（信号增量贡献正且显著）；
    - robust + delta_ic≤0 → "redundant_or_harmful"（移除后 IC 不降反升或不变）；
    - robust + delta>0 但非显著 → "no_contribution"。

    delta_ic = 跨模型均值（full.ic_mean - ablated.ic_mean）；full_pval = 跨模型最小 ic_pval（保守）。
    """
    tier = reliability_tier(n_total, n_days)
    models = [m for m in full if m in ablated]
    deltas = [
        float(full[m].get("ic_mean", 0.0)) - float(ablated[m].get("ic_mean", 0.0))
        for m in models
    ]
    delta_ic = sum(deltas) / len(deltas) if deltas else 0.0
    full_pval = min(
        (float(full[m].get("ic_pval", 1.0)) for m in full), default=1.0
    )

    if tier in ("insufficient", "underpowered"):
        verdict = "exploratory"
        caveat = f"{tier}: 小样本不判冗余（per §44v2 应用规约，复刻 §44v1 假阴性纠错）"
    elif delta_ic > 0 and full_pval < bonf_alpha:
        verdict = "contributes"
        caveat = f"robust: 信号增量贡献正且显著（delta_ic={delta_ic:.4f}, p={full_pval:.4f}）"
    elif delta_ic <= 0:
        verdict = "redundant_or_harmful"
        caveat = f"robust: 移除后 IC 不降反升或不变（delta_ic={delta_ic:.4f}），信号冗余或有害"
    else:
        verdict = "no_contribution"
        caveat = f"robust: 增量非显著（delta_ic={delta_ic:.4f}, p={full_pval:.4f}）"

    return {
        "verdict": verdict,
        "tier": tier,
        "delta_ic": delta_ic,
        "full_pval": full_pval,
        "caveat": caveat,
    }
