# -*- coding: utf-8 -*-
"""S194 R5 · ablation_runner v2（融合分消融）——adversarial verify 后重设计。

v1（feature=信号值×FS2权重 喂 ML walk_forward_cv）被 7 视角 verify 报 CRITICAL：
FS2 权重是 per-signal 正常量，喂 ML 模型后被数学吃掉（Ridge StandardScaler 消常量缩放 +
树阈值分裂对正常量缩放不变），模型看不见权重 → 消融测的是信号值本身预测力（= 已证否的
multifactor null 弱化重测），非 FS2 权重贡献。verdict 还用 full_pval（错假设）+ 1 信号崩 +
underpowered 不分有害/模糊。

v2 重设计（per verify recommended_fix）：
- build_fusion_composite：fusion_score = Σ_j(signal_value_j × weight_j) 单一融合分（权重直接乘数，
  无模型再训练能吃掉 → 真测 FS2 权重贡献）。
- run_composite_ablation：full 融合分 vs ablated（weight_j=0）融合分，per-fold walk-forward
  （leave-one-day-out，train-fold 算权重防 lookahead，reliability_fn 注入）+ per-fold delta
  （full_ic - ablated_ic）+ 置换 p 值（复用 multifactor._permutation_pval sign-flip）。
- composite_ablation_verdict：delta_pval（非 full_pval）+ 跨信号 Bonferroni（alpha/K）+
  underpowered 区分 harmful（delta<0）vs exploratory（delta>0）+ 边界 guard（1 信号不崩、0 折 insufficient）。

不喂 walk_forward_cv 模型——融合分自身即预测分数，IC = spearman(融合分, y)，无模型 wash out。
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from engine.bayesian_signal_weight import reliability_tier

# Bonferroni 基础 alpha（与 multifactor_combo_validation.BONF_ALPHA=0.0125 一致）
BONF_ALPHA: float = 0.0125

# 复用 multifactor 的 sign-flip 置换 p 值（per-fold delta 显著性）
try:
    from tools.multifactor_combo_validation import _permutation_pval as _perm_pval
except Exception:  # noqa: BLE001  # multifactor 不可用时退化（不阻塞 ablation 主逻辑）
    _perm_pval = None


def build_fusion_composite(
    cases_signal_values: list[dict],
    fs2_weights: dict[str, float],
) -> np.ndarray:
    """fusion_score = Σ_j(signal_value_j × weight_j) per case → 1D 分数数组。

    权重是输出里的直接乘数（非 ML 特征缩放），消融时设 weight_j=0 直接移除该信号贡献。
    缺信号值→0（信号未触发该 case）。
    """
    feature_names = list(fs2_weights.keys())
    if not cases_signal_values:
        return np.zeros(0)
    out = np.zeros(len(cases_signal_values))
    for i, case_vals in enumerate(cases_signal_values):
        out[i] = sum(float(case_vals.get(sig, 0.0)) * fs2_weights[sig] for sig in feature_names)
    return out


def ablate_fusion_composite(
    cases_signal_values: list[dict],
    fs2_weights: dict[str, float],
    target_signal: str,
) -> np.ndarray:
    """消融融合分：target_signal 权重设 0（移除该信号贡献），其余不变。"""
    ablated_weights = {k: (0.0 if k == target_signal else v) for k, v in fs2_weights.items()}
    return build_fusion_composite(cases_signal_values, ablated_weights)


def _spearman_ic(scores: np.ndarray, y: np.ndarray) -> float:
    """Spearman IC（融合分 vs y 的 rank 相关）。std=0/数据不足/无 scipy → 0.0。"""
    if len(scores) < 3 or len(scores) != len(y):
        return 0.0
    try:
        from scipy.stats import spearmanr  # noqa: PLC0415
        r, _ = spearmanr(scores, y)
        return 0.0 if np.isnan(r) else float(r)
    except Exception:  # noqa: BLE001
        return 0.0


def run_composite_ablation(
    cases_signal_values: list[dict],
    fs2_weights: dict[str, float],
    outcomes: list[float | None],
    dates: list[str],
    target_signal: str,
    ic_fn: Callable[[np.ndarray, np.ndarray], float] = _spearman_ic,
    reliability_fn: Callable[[list[dict]], dict[str, float]] | None = None,
) -> dict:
    """融合分消融：full vs ablated(weight_j=0) per-fold walk-forward → delta_ic + 置换 p 值。

    leave-one-day-out：每 fold test=一日，train=其余日。reliability_fn 注入则用 train-fold
    数据算权重（防 lookahead）；否则用传入的 fs2_weights（标 caveat：可能全量数据 lookahead）。
    1 信号消融：ablated 融合分全 0 → IC=0 → delta=full_ic（不崩，v1 会 0 列 imputer 崩）。
    """
    if target_signal not in fs2_weights:
        raise ValueError(f"target_signal {target_signal!r} 不在 fs2_weights {list(fs2_weights)}")

    # 过滤 None outcome（case + date 同步跳）
    kept_vals, kept_y, kept_dates = [], [], []
    for cv, y, d in zip(cases_signal_values, outcomes, dates):
        if y is None:
            continue
        kept_vals.append(cv)
        kept_y.append(float(y))
        kept_dates.append(d)
    if not kept_vals:
        return {"delta_ic": 0.0, "delta_pval": 1.0, "per_fold_deltas": [], "n_folds": 0,
                "full_ic_mean": 0.0, "ablated_ic_mean": 0.0}

    y_arr = np.array(kept_y)
    unique_dates = sorted(set(kept_dates))
    per_fold_full, per_fold_ablated, per_fold_delta = [], [], []

    for test_date in unique_dates:
        test_mask = np.array([d == test_date for d in kept_dates])
        train_mask = ~test_mask
        train_cases = [kept_vals[i] for i in range(len(kept_vals)) if train_mask[i]]
        # 每 fold 算权重（防 lookahead）；无 reliability_fn 用传入的 fs2_weights（caveat）
        weights = reliability_fn(train_cases) if reliability_fn else fs2_weights
        test_cases = [kept_vals[i] for i in range(len(kept_vals)) if test_mask[i]]
        y_test = y_arr[test_mask]
        full_scores = build_fusion_composite(test_cases, weights)
        ablated_scores = ablate_fusion_composite(test_cases, weights, target_signal)
        ic_full = ic_fn(full_scores, y_test)
        ic_abl = ic_fn(ablated_scores, y_test)
        per_fold_full.append(ic_full)
        per_fold_ablated.append(ic_abl)
        per_fold_delta.append(ic_full - ic_abl)

    deltas = np.array(per_fold_delta)
    delta_ic = float(np.mean(deltas))
    delta_pval = float(_perm_pval(deltas)) if _perm_pval is not None else 1.0
    return {
        "delta_ic": delta_ic,
        "delta_pval": delta_pval,
        "per_fold_deltas": per_fold_delta,
        "n_folds": len(per_fold_delta),
        "full_ic_mean": float(np.mean(per_fold_full)),
        "ablated_ic_mean": float(np.mean(per_fold_ablated)),
    }


def composite_ablation_verdict(
    delta_ic: float,
    delta_pval: float,
    n_total: int,
    n_days: int,
    K: int,
    bonf_alpha: float = BONF_ALPHA,
) -> dict:
    """融合分消融 verdict（v2）——delta_pval + 跨信号 Bonferroni + underpowered 分有害/模糊。

    - tier=reliability_tier(n_total, n_days)（n<30 insufficient / n_days<60 underpowered / ≥60 robust）；
    - adjusted_alpha = bonf_alpha / K（跨 K 信号消融多重比较校正）；
    - robust + delta_pval<adj_alpha + delta>0 → contributes；delta<0 → harmful；
    - underpowered/insufficient + delta>0 → exploratory（正但样本不够）；delta<0 → exploratory_harmful（区分）；
    - 其余 → no_contribution（非显著，不判冗余也不判贡献）。
    """
    tier = reliability_tier(n_total, n_days)
    adjusted_alpha = bonf_alpha / K
    significant = delta_pval < adjusted_alpha

    if tier in ("insufficient", "underpowered"):
        if delta_ic < 0:
            verdict = "exploratory_harmful"
            caveat = f"{tier}: delta 负（{delta_ic:+.4f}），可能有害但样本不够（n_days={n_days}）不判冗余"
        else:
            verdict = "exploratory"
            caveat = f"{tier}: delta 正（{delta_ic:+.4f}），可能贡献但样本不够（n_days={n_days}）不判冗余"
    elif significant and delta_ic > 0:
        verdict = "contributes"
        caveat = f"robust: delta 显著正（delta_ic={delta_ic:+.4f}, p={delta_pval:.4f} < {adjusted_alpha:.4f}）"
    elif significant and delta_ic < 0:
        verdict = "harmful"
        caveat = f"robust: delta 显著负（delta_ic={delta_ic:+.4f}），移除该信号预测力升，信号有害"
    else:
        verdict = "no_contribution"
        caveat = f"robust: delta 非显著（delta_ic={delta_ic:+.4f}, p={delta_pval:.4f} ≥ {adjusted_alpha:.4f}）"

    return {
        "verdict": verdict,
        "tier": tier,
        "delta_ic": delta_ic,
        "delta_pval": delta_pval,
        "adjusted_alpha": adjusted_alpha,
        "caveat": caveat,
    }
