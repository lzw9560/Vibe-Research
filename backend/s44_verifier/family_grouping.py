# -*- coding: utf-8 -*-
"""S204 R10 T6: Bonferroni family grouping + K 冻结 pre-registration。

决策#9: K>8 拆≤8 子 phase（不用 BH，保 Bonferroni 严格，alpha_adj 正确）。
决策#10: family grouping 去重等价（bollinger==zscore 数学等价等）。
§44v2 rule③: K 冻结 pre-registration（防后调 cherry-pick K）。

本模块（verifier/stats 不改，harness G5 用本模块算 n_comparisons）：
- ``EQUIVALENCE_FAMILIES``: 数学等价策略族（去重，effective families ~9-15 非 raw 30）。
- ``effective_family_count``: 给策略列表返 effective family 数（Bonferroni n_comparisons 用）。
- ``split_into_subphases``: K>8 拆成≤8 子 phase（每子 alpha_adj=0.05/K_sub）。
- ``FrozenK``: K 冻结 dataclass（首次入库冻结，后续 K 变→rejected 防后调）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# 数学等价策略族（去重）：同族内策略数学等价，Bonferroni 只算 1 个 family。
# bollinger: z<=-2 == close<=lower band (std_mult=2)；triple_ma/ema_ribbon: 持续 MA 多头排列；
# macd/rsi_momentum: 动量交叉。
EQUIVALENCE_FAMILIES: dict[frozenset[str], str] = {
    frozenset({"bollinger", "zscore"}): "mean_reversion",
    frozenset({"triple_ma", "ema_ribbon"}): "ma_stack",
    frozenset({"macd", "rsi_momentum"}): "momentum_crossover",
}

# K 冻结上限（与 stats.py:33 _MAX_BONFERRONI_K=8 一致——拆子 phase 保严格，非 cap overcorrect）
_MAX_SUBPHASE_K: int = 8


@dataclass(frozen=True)
class FrozenK:
    """K 冻结 pre-registration（§44v2 rule③，防后调）。

    首次入库冻结 K（n_comparisons），后续跑若 K 变 → rejected（防 cherry-pick K
    让结果好看）。``family_count`` 是去重后 effective families。
    """

    k: int
    frozen_at: str  # ISO timestamp
    strategy_count: int
    family_count: int  # effective families（去重后）


def effective_family_count(strategy_names: Iterable[str]) -> int:
    """给策略列表返 effective family 数（去重数学等价族）。

    Args:
        strategy_names: 策略名列表（如 ``["bollinger", "zscore", "macd"]``）。

    Returns:
        effective family 数（去重后，~9-15 非 raw 30）。用于 Bonferroni ``n_comparisons``
        （决策#10：bollinger==zscore 等价只算 1 family）。
    """
    names = set(strategy_names)
    effective = set(names)  # 先全算
    # 去重等价族：族内 ≥2 策略 → 合并成 1 family（去掉多余的，留 1 个代表）
    for family_set in EQUIVALENCE_FAMILIES:
        in_family = names & family_set
        if len(in_family) >= 2:
            kept = next(iter(in_family))  # 保留一个代表（count 不依赖具体哪个）
            for name in in_family:
                if name != kept:
                    effective.discard(name)
    return len(effective)


def split_into_subphases(k: int, max_k: int = _MAX_SUBPHASE_K) -> list[int]:
    """K>8 拆成≤8 子 phase（决策#9，保 Bonferroni 严格 + alpha_adj 正确）。

    Args:
        k: 原始 K（如 12 = 3 regime×4 战法）。
        max_k: 子 phase 上限（默认 8，stats.py:33 ``_MAX_BONFERRONI_K``）。

    Returns:
        子 phase K 列表（每子≤max_k，和=k）。如 K=12 → [8,4]。
        每子 phase ``alpha_adj = 0.05 / K_sub``（非 0.05/k 整体，也非 0.05/max_k cap）。
        harness 也可预拆（如按 regime 拆 3 family 各 K=4），本函数是 fallback。
    """
    if k <= max_k:
        return [k]
    subphases: list[int] = []
    remaining = k
    while remaining > max_k:
        subphases.append(max_k)
        remaining -= max_k
    if remaining > 0:
        subphases.append(remaining)
    return subphases
