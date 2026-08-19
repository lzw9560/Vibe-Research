# -*- coding: utf-8 -*-
"""S066 Phase 2 P2-3 非涨停类策略分 + 漏斗测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.pattern_scan import PatternScan
from strategies.non_limitup_funnel import (
    NonLimitupScore,
    compute_relative_strength_score,
    compute_ma_bullish_score,
    compute_volume_signal_score,
    compute_sector_strength_score,
    compute_non_limitup_score,
    run_non_limitup_funnel,
    NON_LIMITUP_WEIGHTS,
)


def _make_pattern(
    relative_strength: float | None = 5.0,
    ma_bullish: bool = True,
    ma5_proximity: float | None = 2.0,
    consolidation_days: int | None = 0,
    consolidation_amplitude: float | None = None,
    volume_breakout_ratio: float | None = 2.5,
    amount_yi: float | None = 20.0,
) -> PatternScan:
    return PatternScan(
        code="000001",
        relative_strength=relative_strength,
        ma_bullish=ma_bullish,
        ma5_proximity=ma5_proximity,
        consolidation_days=consolidation_days,
        consolidation_amplitude=consolidation_amplitude,
        volume_breakout_ratio=volume_breakout_ratio,
        amount_yi=amount_yi,
    )


class TestRelativeStrengthScore:
    """相对强度因子。"""

    def test_positive_outperformance(self):
        p = _make_pattern(relative_strength=10.0)
        assert compute_relative_strength_score(p) == 100.0

    def test_neutral(self):
        p = _make_pattern(relative_strength=0.0)
        assert compute_relative_strength_score(p) == 50.0

    def test_negative(self):
        p = _make_pattern(relative_strength=-10.0)
        assert compute_relative_strength_score(p) == 0.0

    def test_none_returns_neutral(self):
        p = _make_pattern(relative_strength=None)
        assert compute_relative_strength_score(p) == 50.0

    def test_clamped_to_0_100(self):
        p = _make_pattern(relative_strength=50.0)  # 50*5+50=300 → clamp 100
        assert compute_relative_strength_score(p) == 100.0
        p2 = _make_pattern(relative_strength=-50.0)
        assert compute_relative_strength_score(p2) == 0.0


class TestMaBullishScore:
    """均线多头因子。"""

    def test_bullish_full_score(self):
        p = _make_pattern(ma_bullish=True)
        assert compute_ma_bullish_score(p) == 100.0

    def test_not_bullish_half_score(self):
        p = _make_pattern(ma_bullish=False)
        assert compute_ma_bullish_score(p) == 50.0


class TestVolumeSignalScore:
    """量能信号因子（按战法上下文选）。"""

    def test_platform_breakout_vol_ratio_above_2(self):
        """平台突破：量比 > 2 → 满分。"""
        p = _make_pattern(volume_breakout_ratio=2.5)
        assert compute_volume_signal_score(p, "platform_breakout") == 100.0

    def test_platform_breakout_low_vol(self):
        p = _make_pattern(volume_breakout_ratio=1.0)
        assert compute_volume_signal_score(p, "platform_breakout") == 40.0

    def test_reverse_package_high_amount(self):
        """反包：成交额 > 15亿 → 满分。"""
        p = _make_pattern(amount_yi=20.0)
        assert compute_volume_signal_score(p, "reverse_package") == 100.0

    def test_reverse_package_low_amount(self):
        p = _make_pattern(amount_yi=7.5)
        assert compute_volume_signal_score(p, "reverse_package") == 50.0

    def test_dragon_head_high_amount(self):
        """龙头：成交额 > 10亿 → 满分。"""
        p = _make_pattern(amount_yi=15.0)
        assert compute_volume_signal_score(p, "dragon_head") == 100.0

    def test_low_absorption(self):
        """低吸：成交额 > 5亿 → 80 分。"""
        p = _make_pattern(amount_yi=8.0)
        assert compute_volume_signal_score(p, "low_absorption") == 80.0

    def test_none_volume_data(self):
        p = _make_pattern(volume_breakout_ratio=None, amount_yi=None)
        assert compute_volume_signal_score(p, "platform_breakout") == 50.0


class TestSectorStrengthScore:
    """板块强度因子。"""

    def test_top5_full_score(self):
        assert compute_sector_strength_score(3) == 100.0

    def test_top20_half_score(self):
        assert compute_sector_strength_score(15) == 50.0

    def test_below_20_low_score(self):
        assert compute_sector_strength_score(30) == 20.0

    def test_none_neutral(self):
        assert compute_sector_strength_score(None) == 50.0


class TestComputeNonLimitupScore:
    """非涨停类策略分计算。"""

    def test_full_score_calculation(self):
        """完整策略分 = 4 因子等权加总。"""
        p = _make_pattern(relative_strength=10.0, ma_bullish=True, volume_breakout_ratio=2.5, amount_yi=20.0)
        result = compute_non_limitup_score("000001", p, "platform_breakout", sector_rank=3)
        assert result.code == "000001"
        assert result.strategy_code == "platform_breakout"
        assert result.strategy_score > 0
        # 4 因子都满分 100 × 0.25 = 25 × 4 = 100
        assert result.strategy_score == 100.0

    def test_all_factors_in_breakdown(self):
        p = _make_pattern()
        result = compute_non_limitup_score("000001", p, "low_absorption", sector_rank=1)
        assert "relative_strength" in result.score_breakdown
        assert "ma_bullish" in result.score_breakdown
        assert "volume_signal" in result.score_breakdown
        assert "sector_strength" in result.score_breakdown

    def test_invalid_strategy_returns_zero(self):
        """非涨停类策略不存在的 code → 返 0。"""
        p = _make_pattern()
        result = compute_non_limitup_score("000001", p, "first_plate")  # 涨停类
        assert result.strategy_score == 0.0

    def test_weights_sum_to_one(self):
        """4 因子权重等权 = 0.25 × 4 = 1.0。"""
        assert sum(NON_LIMITUP_WEIGHTS.values()) == 1.0
        assert all(w == 0.25 for w in NON_LIMITUP_WEIGHTS.values())


class TestRunNonLimitupFunnel:
    """非涨停类漏斗编排。"""

    def test_sunny_day_filters_and_sorts(self):
        """晴天候选：龙头/平台突破是主跑策略。"""
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [
            {"code": "000001", "bars": bars, "sector": "电子"},
            {"code": "000002", "bars": bars, "sector": "电子"},
        ]
        result = run_non_limitup_funnel(candidates, "晴天", {"电子": 1})
        # 应有结果（晴天主跑 dragon_head + platform_breakout）
        assert len(result) > 0
        # 结果按策略分降序
        scores = [r["strategy_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_storm_allows_non_limitup_strategies(self):
        """S086 R3：暴风雨不再硬约束——非涨停类策略亦 allowed（返非空，与晴天同）。

        旧：暴风雨 → get_strategies_for_weather 返 ["storm_reversal"]（涨停类），非涨停类返空；
        新：暴风雨 → 全 allowed，非涨停类策略（龙头/平台突破/低吸/反包）亦跑。
        """
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [{"code": "000001", "bars": bars, "sector": "电子"}]
        result = run_non_limitup_funnel(candidates, "暴风雨", {"电子": 1})
        assert len(result) > 0  # S086 R3：暴风雨允许非涨停类策略（不再只跑 storm_reversal）

    def test_empty_candidates_returns_empty(self):
        result = run_non_limitup_funnel([], "晴天")
        assert result == []

    def test_passed_hard_standards_filtering(self):
        """未通过硬标准的候选被过滤。"""
        bars = [{"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5}] * 5
        candidates = [{"code": "000001", "bars": bars, "sector": "电子"}]
        result = run_non_limitup_funnel(candidates, "晴天", {"电子": 1})
        # 所有结果应标 passes_hard_standards=True（missing 数据不阻断）
        for r in result:
            assert r["passes_hard_standards"] is True
