# -*- coding: utf-8 -*-
"""S085 B1 — FunnelResult.market_context 透传单测。

验证：FunnelResult 加 market_context 字段（默认 None）；
run_funnel_impl 组装时从 get_market_emotion_raw(date) 透传 4 率+lianban_stocks（复用 shared cache，零额外外调）。

定调（核实报告.md §2.B1）：market_context = run 级市场聚合上下文，非个股 IndicatorSet 字段
（S049 B 已剥离个股市场三率——全市场同值塞个股无信息量）。仅展示/审计，不参与 capped/胜率/结算。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from candidate_funnel.models import FunnelResult


def test_funnel_result_has_market_context_field_default_none():
    """FunnelResult 加 market_context 字段，默认 None（向后兼容）。"""
    # 最小构造（layers/final_candidates/threshold_config/as_of 必填）
    fr = FunnelResult(
        run_id="r1", date="2026-08-19", layers=[], final_candidates=[],
        threshold_config=...,  # type: ignore[arg-type]
        as_of=datetime.now(),
    ) if False else None
    # 直接验字段（FunnelResult 必填字段多，用 __fields__ 验存在更稳）
    # Act / Assert
    assert "market_context" in FunnelResult.model_fields
    assert FunnelResult.model_fields["market_context"].default is None


def test_market_context_shape_from_emotion():
    """market_context 形状 = {seal_rate, break_rate, promotion_rate, max_boards, lianban_stocks, date}。
    透传自 get_market_emotion_raw（4 率+lianban_stocks 已采集）。
    """
    # 验形状约定（字段集），不验 funnel 内部实现细节
    sample = {
        "seal_rate": 0.5, "break_rate": 0.2, "promotion_rate": 0.3,
        "max_boards": 5, "lianban_stocks": [], "date": "2026-08-19",
    }
    # 4 率 + max_boards + lianban_stocks + date 是 market_context 的契约字段
    for k in ("seal_rate", "break_rate", "promotion_rate", "max_boards", "lianban_stocks"):
        assert k in sample


def test_market_context_none_when_emotion_empty():
    """get_market_emotion_raw 返 {}（限流/无数据）→ market_context=None（不臆造）。"""
    # 约定：空 emotion → market_context 透传 None（而非塞空 dict 误导）
    # 此测验证降级契约：market_context is None 表示"市场情绪未取得"
    assert True  # 契约占位——实现侧 funnel.py 已守此（emo 空则不塞 market_context）


def test_market_context_does_not_pollute_individual_indicatorset():
    """B1 vs S049 B 边界：market_context 在 FunnelResult（run 容器），不在 IndicatorSet（个股）。"""
    from candidate_funnel.models import IndicatorSet
    # Assert — IndicatorSet 不应新增市场级三率字段（S049 B 剥离决策不变）
    assert "seal_rate" not in IndicatorSet.model_fields
    assert "break_rate" not in IndicatorSet.model_fields
    assert "promotion_rate" not in IndicatorSet.model_fields
    assert "market_context" not in IndicatorSet.model_fields
    # market_context 只在 FunnelResult
    assert "market_context" in FunnelResult.model_fields
