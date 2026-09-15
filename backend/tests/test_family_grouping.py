# -*- coding: utf-8 -*-
"""S204 R10 T6: family_grouping test（TDD）。

验证 Bonferroni family grouping 去重等价 + K 拆≤8 子 phase + K 冻结。
"""
from __future__ import annotations

import pytest

from s44_verifier.family_grouping import (
    EQUIVALENCE_FAMILIES,
    FrozenK,
    effective_family_count,
    split_into_subphases,
)


def test_family_grouping_dedup_bollinger_zscore():
    """bollinger==zscore 数学等价 → 1 family（非 2）。"""
    assert effective_family_count(["bollinger", "zscore"]) == 1
    assert effective_family_count(["zscore", "bollinger"]) == 1  # 顺序无关


def test_family_grouping_macd_rsi_momentum():
    """macd==rsi_momentum 等价 → 1 family。"""
    assert effective_family_count(["macd", "rsi_momentum"]) == 1


def test_family_grouping_no_dedup_different_families():
    """不同族策略不去重：bollinger + (macd+rsi_momentum=1) = 2。"""
    assert effective_family_count(["bollinger", "macd", "rsi_momentum"]) == 2


def test_family_grouping_all_distinct():
    """全不同族策略不去重。"""
    assert effective_family_count(["bollinger", "supertrend", "donchian"]) == 3


def test_family_grouping_effective_less_than_raw():
    """effective families < raw count（去重后）。"""
    raw = ["bollinger", "zscore", "triple_ma", "ema_ribbon", "macd", "rsi_momentum", "supertrend"]
    eff = effective_family_count(raw)
    assert eff < len(raw)  # 去重后 < 7
    assert eff == 4  # bollinger+zscore=1, triple_ma+ema_ribbon=1, macd+rsi_momentum=1, supertrend=1


def test_split_into_subphases_k12():
    """K=12 拆成 [8,4]（每子≤8，alpha_adj=0.05/8 或 0.05/4 非 0.05/12 cap）。"""
    sub = split_into_subphases(12)
    assert sum(sub) == 12
    assert all(s <= 8 for s in sub)
    assert 12 not in sub  # 不整体 12（会 cap 到 8）


def test_split_into_subphases_k8_no_split():
    """K=8 不拆（≤8）。"""
    assert split_into_subphases(8) == [8]


def test_split_into_subphases_k4():
    """K=4 不拆。"""
    assert split_into_subphases(4) == [4]


def test_split_into_subphases_k20():
    """K=20 拆成 [8,8,4]（每子≤8）。"""
    sub = split_into_subphases(20)
    assert sum(sub) == 20
    assert all(s <= 8 for s in sub)
    assert 20 not in sub


def test_frozen_k_immutable():
    """FrozenK frozen dataclass。"""
    fk = FrozenK(k=12, frozen_at="2026-09-14", strategy_count=12, family_count=4)
    assert fk.k == 12
    assert fk.family_count == 4
    with pytest.raises(Exception):
        fk.k = 15  # frozen, should raise


def test_equivalence_families_nonempty():
    """EQUIVALENCE_FAMILIES 至少含 3 族（bollinger/zscore, triple_ma/ema_ribbon, macd/rsi_momentum）。"""
    assert len(EQUIVALENCE_FAMILIES) >= 3
