# -*- coding: utf-8 -*-
"""limitup_sti 模型与辅助函数。"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional

from pydantic import BaseModel


DISCLAIMER = (
    "免责声明：情绪温度仅为历史统计维度之一，不构成任何操作建议。"
    "股市有风险，投资需谨慎。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。"
)

STI_WEIGHTS: dict[str, float] = {
    "limit_up_count": 0.15,
    "limit_down_count": 0.13,
    "seal_rate": 0.25,
    "advance_decline_ratio": 0.10,
    "promotion_rate": 0.22,
    "prev_zt_performance": 0.10,
    "max_boards": 0.05,
}
TOTAL_WEIGHT = sum(STI_WEIGHTS.values())

STI_DIRECTIONS: dict[str, int] = {
    "limit_up_count": 1,
    "limit_down_count": -1,
    "seal_rate": 1,
    "advance_decline_ratio": 1,
    "promotion_rate": 1,
    "prev_zt_performance": 1,
    "max_boards": 1,
}

_MARKET_ACTIVE_MAP = {
    "冰点": 0.7,
    "偏弱": 0.85,
    "中性": 1.0,
    "偏强": 1.15,
    "普涨": 1.3,
}

_FALLBACK_PHASE_THRESHOLDS = {
    "高潮": 80.0,
    "启动": 60.0,
    "分歧": 40.0,
    "冰点": 20.0,
}

PHASE_EXPLANATIONS = {
    "高潮": "市场过热（历史统计含义）",
    "启动": "情绪从低位回升（历史统计含义）",
    "分歧": "多空博弈激烈（历史统计含义）",
    "冰点": "市场冷清（历史统计含义）",
    "退潮": "情绪持续走弱（历史统计含义）",
}


class STIPhase(str, Enum):
    """五阶段枚举。"""
    HIGH潮 = "高潮"
    START = "启动"
    DIVERGENCE = "分歧"
    FREEZE = "冰点"
    DECLINE = "退潮"


class STIDimension(BaseModel):
    """8 维指标原始值（归一化前）。"""
    limit_up_count: float = 0.0
    limit_down_count: float = 0.0
    seal_rate: float = 0.0
    advance_decline_ratio: float = 0.0
    promotion_rate: float = 0.0
    prev_zt_performance: float = 0.0
    max_boards: float = 0.0
    market_factor: float = 1.0


class STIResult(BaseModel):
    """STI 情绪温度计算结果。"""
    date: str
    score: Optional[float]
    phase: Optional[STIPhase]
    dimensions: Optional[STIDimension]
    source_ok: bool = True
    confidence: str = "high"
    change_from_yesterday: Optional[float] = None
    data_updated: Optional[str] = None
    phase_explanation: Optional[str] = None
    disclaimer: str = DISCLAIMER
    data_freshness: str = "fresh"  # fresh | stale | expired
    data_age_seconds: float = 0.0  # 数据年龄（秒）
    raw_break_rate: Optional[float] = None  # S063 T4 补齐：原始炸板率（0-1），盘前简报 T-1 直读


def percentile_rank(value: float, lookback_series: list[float]) -> float:
    """将 value 映射到 lookback_series 的百分位排名（0-100）。

    warmup 期（<60 样本）不再硬返 50——否则 STI 在攒够 60 个交易日前恒为中
    性，毫无信号。改为只要 n>=1 就算真实百分位（粗但有用），低样本置信度由
    _compute_confidence 标注。n==0 才返 50 防除零。
    """
    n = len(lookback_series)
    if n == 0:
        return 50.0
    less = sum(1 for v in lookback_series if v < value)
    equal = sum(1 for v in lookback_series if v == value)
    return ((less + 0.5 * equal) / n) * 100.0


def _safe_float(v, default: float = 0.0) -> float:
    """安全转换为 float。"""
    try:
        if v is None:
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _ema_3day(current: float, history: list[float]) -> float:
    """计算 3 日移动平均（含历史数据）。"""
    if not history:
        return current
    if len(history) == 1:
        return (current + history[-1]) / 2.0
    return (current + history[-1] + history[-2]) / 3.0
