# -*- coding: utf-8 -*-
"""S203 T2: dragon_score composite test（TDD）。

验证 composite 0-100 / 缺失维度贡献 0 / 非 ML guard / 纯函数。
"""
from __future__ import annotations

from strategies.dimension_registry import STRATEGY_CONFIGS
from strategies.dragon_score import dragon_score


def test_composite_range_0_100():
    """dragon_score 返回 [0, 100]。"""
    config = STRATEGY_CONFIGS["龙头首板"]
    # 全维度归一化值 1.0 → score=100
    indicators = {dim: 1.0 for dim in config.weights}
    assert dragon_score(config, "600000", "2026-01-01", indicators) == 100.0
    # 全 0 → 0
    indicators0 = {dim: 0.0 for dim in config.weights}
    assert dragon_score(config, "600000", "2026-01-01", indicators0) == 0.0


def test_missing_dim_contribution_zero():
    """缺失维度贡献=0（不报错）。"""
    config = STRATEGY_CONFIGS["龙头首板"]
    # 只给板块强度 1.0，其他缺失 → score = 1.0*0.25*100 = 25
    indicators = {"板块强度": 1.0}
    assert dragon_score(config, "600000", "2026-01-01", indicators) == 25.0


def test_weighted_sum():
    """加权求和正确（各维度不同归一化值）。"""
    config = STRATEGY_CONFIGS["龙头首板"]
    indicators = {
        "板块强度": 1.0,    # 0.25
        "封单强度": 0.5,    # 0.25*0.5=0.125
        "量能确认": 0.0,    # 0
        "情绪周期": 1.0,    # 0.15
        "技术形态": 0.5,    # 0.15*0.5=0.075
    }
    expected = (0.25 + 0.125 + 0.0 + 0.15 + 0.075) * 100  # 60.0
    assert abs(dragon_score(config, "600000", "2026-01-01", indicators) - expected) < 1e-6


def test_pure_function():
    """同输入→同输出（无副作用）。"""
    config = STRATEGY_CONFIGS["龙头首板"]
    indicators = {"板块强度": 0.8, "封单强度": 0.6}
    s1 = dragon_score(config, "600000", "2026-01-01", indicators)
    s2 = dragon_score(config, "600000", "2026-01-01", indicators)
    assert s1 == s2


def test_unknown_dim_in_weights_skipped():
    """weights 含未知维度（如反包的"反包确认强度"待 S205）→ 跳过贡献 0。"""
    config = STRATEGY_CONFIGS["反包"]  # weights 有"反包确认强度"（不在 dimensions，待 S205）
    indicators = {dim: 1.0 for dim in config.dimensions}  # 不含"反包确认强度"
    # score = sum of dimensions weights (板块0.15+量能0.20+情绪0.15+技术0.25=0.75，反包确认 0.25 缺失贡献 0)
    assert abs(dragon_score(config, "600000", "2026-01-01", indicators) - 75.0) < 1e-6


def test_nan_raw_handled():
    """raw 非数值（NaN/str）→ 归一化 0 不 crash。"""
    config = STRATEGY_CONFIGS["龙头首板"]
    indicators = {"板块强度": float("nan"), "封单强度": "invalid"}
    # nan + invalid → 0 each → score 0
    assert dragon_score(config, "600000", "2026-01-01", indicators) == 0.0
