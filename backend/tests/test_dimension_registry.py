# -*- coding: utf-8 -*-
"""S203 T1: dimension_registry test（TDD）。

验证声明式维度 + 战法 config（frozen / weights sum=1 / edge_type 待验 / DRY vs scoring.py）。
"""
from __future__ import annotations

import pytest

from strategies.dimension_registry import DIMENSION_REGISTRY, STRATEGY_CONFIGS, Dimension, 战法ScoreConfig


def test_dimension_frozen():
    """Dimension frozen dataclass，setattr 报 FrozenInstanceError。"""
    d = DIMENSION_REGISTRY["板块强度"]
    assert isinstance(d, Dimension)
    with pytest.raises(Exception):
        d.name = "other"  # frozen


def test_战法_config_frozen():
    """战法ScoreConfig frozen dataclass。"""
    c = STRATEGY_CONFIGS["龙头首板"]
    assert isinstance(c, 战法ScoreConfig)
    with pytest.raises(Exception):
        c.战法 = "other"


def test_weights_sum_one():
    """每战法 config weights sum=1.0（先验固定，非回测拟合）。"""
    for name, config in STRATEGY_CONFIGS.items():
        total = sum(config.weights.values())
        assert abs(total - 1.0) < 1e-6, f"{name} weights sum={total} != 1.0"


def test_edge_type_marked_unverified():
    """edge_type 含'待验'标注（决策#7 verifier-side，window sanity 后定不预设）。"""
    for config in STRATEGY_CONFIGS.values():
        assert "待验" in config.edge_type, f"{config.战法} edge_type={config.edge_type} 须标待验"


def test_dimensions_in_registry():
    """战法 config 的 dimensions 都在 DIMENSION_REGISTRY（已知维度）。

    weights 里可能有待 S205 新增的维度（如"反包确认强度"），不在 dimensions 也不在 registry，
    dragon_score 跳过贡献 0——这是声明式 registry 支持渐进扩展的设计。
    """
    for config in STRATEGY_CONFIGS.values():
        for dim in config.dimensions:
            assert dim in DIMENSION_REGISTRY, f"{config.战法} dimension {dim} 不在 registry"


def test_applicable_战法_nonempty():
    """每维度 applicable_战法 非空。"""
    for dim in DIMENSION_REGISTRY.values():
        assert len(dim.applicable_战法) > 0


def test_5_shared_dimensions():
    """5 共享维度（板块/封单/量能/情绪/技术）。"""
    expected = {"板块强度", "封单强度", "量能确认", "情绪周期", "技术形态"}
    assert expected.issubset(DIMENSION_REGISTRY.keys())


def test_sweep_params_match_dimension_sweep_range():
    """龙头 sweep_params 的 seal_to_float_ratio 与 Dimension.sweep_range 一致。"""
    seal_dim = DIMENSION_REGISTRY["封单强度"]
    龙头 = STRATEGY_CONFIGS["龙头首板"]
    assert list(龙头.sweep_params["seal_to_float_ratio"]) == list(seal_dim.sweep_range)
