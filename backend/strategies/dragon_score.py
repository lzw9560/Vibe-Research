# -*- coding: utf-8 -*-
"""S203 T2: Dragon Score composite 计算（非 ML，对齐 weight-as-ml-feature-is-inert）。

分数本身是选股排序依据，不是喂模型的特征（scale-invariant，喂 ML 会被归一化/
树阈值吃掉）。读 DIMENSION_REGISTRY Dimension.data_source 取原始值→归一化→加权求和。
纯函数无副作用（同输入→同输出）。
"""
from __future__ import annotations

from typing import Any

from .dimension_registry import DIMENSION_REGISTRY, 战法ScoreConfig


def _normalize(raw: float, normalization: str) -> float:
    """归一化到 [0,1]（按 normalization 方法）。缺失 raw → 0.0 不报错。

    简化实现：按 normalization 字符串识别方法，返 [0,1]。生产实现须读 Dimension.data_source
    取原始值 + 应用具体归一化公式（板块强度=zt_count_today/均值封顶、封单=ratio/0.005 等）。
    本函数是骨架，归一化逻辑在 harness 层按 Dimension.notes 实现。
    """
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN check (nan != nan) → 归一化 0 不污染 score
        return 0.0
    # 简化：raw 已是 [0,1] 归一化值（harness 层归一化后传入）。本函数只做 clip。
    return max(0.0, min(1.0, v))


def dragon_score(
    config: 战法ScoreConfig,
    code: str,
    trade_date: str,
    indicators: dict[str, float],
) -> float:
    """composite 0-100 分计算。

    Args:
        config: 战法配置（dimensions + weights）。
        code: 股票代码。
        trade_date: 交易日。
        indicators: ``{dimension_name: normalized_value_in_0_1}``（harness 层归一化后传入）。
            缺失维度 → 贡献 0（不报错）。

    Returns:
        0-100 分（``Σ(normalized × weight) × 100``）。非 ML 特征——分数是选股排序依据。

    纯函数：同输入→同输出，无副作用。guard：不喂回 gene_score/scoring.py（caller 须确保）。
    """
    score = 0.0
    for dim_name, weight in config.weights.items():
        if dim_name not in DIMENSION_REGISTRY:
            continue  # 未知维度（如"反包确认强度"待 S205 新增）→ 跳过贡献 0
        raw = indicators.get(dim_name)
        if raw is None:
            continue  # 缺失维度贡献 0
        dim = DIMENSION_REGISTRY[dim_name]
        normalized = _normalize(raw, dim.normalization)
        score += normalized * weight
    return score * 100.0  # → 0-100
