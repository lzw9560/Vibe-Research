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
)


def _make_pattern(
    relative_strength: float | None = 5.0,
    ma_bullish: bool = True,
    ma5_proximity: float | None = 2.0,
    consolidation_days: int | None = 0,
    consolidation_amplitude: float | None = None,
    volume_breakout_ratio: float | None = 2.5,
    amount_yi: float | None = 20.0,
    shadow_length_pct: float | None = 5.0,
    ma5_slope: float | None = 0.01,
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
        shadow_length_pct=shadow_length_pct,
        ma5_slope=ma5_slope,
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
        """S094 R3/R4：compute_non_limitup_score 委托 compute_strategy_score 后，
        breakdown 键随权重源——strategy_weights.json 存在用英文权重键，不存在
        （测试环境 VR_DATA_DIR 临时目录）走等权兜底用 factors 中文键
        （相对强度/均线多头/量能信号/板块强度，对齐 S094 R4 单一 PatternScan factors dict）。

        两种情况都验证 4 因子键存在（中英文任一）。
        """
        p = _make_pattern()
        result = compute_non_limitup_score("000001", p, "low_absorption", sector_rank=1)
        keys = set(result.score_breakdown.keys())
        # 英文键（json 存在）或中文键（等权兜底）任一
        rs_ok = "relative_strength" in keys or "相对强度" in keys
        ma_ok = "ma_bullish" in keys or "均线多头" in keys
        vol_ok = "volume_signal" in keys or "量能信号" in keys
        sec_ok = "sector_strength" in keys or "板块强度" in keys
        assert rs_ok and ma_ok and vol_ok and sec_ok, f"breakdown keys: {keys}"

    def test_invalid_strategy_returns_zero(self):
        """非涨停类策略不存在的 code → 返 0。"""
        p = _make_pattern()
        result = compute_non_limitup_score("000001", p, "first_plate")  # 涨停类
        assert result.strategy_score == 0.0

    def test_weights_from_strategy_weights_json(self):
        """S094 R3：删硬编码 NON_LIMITUP_WEIGHTS，权重改从 strategy_weights.json
        non_limitup 权重集读（等权 0.25×4，与旧硬编码值一致）。

        验证 compute_non_limitup_score 委托 compute_strategy_score 后，
        4 因子满分（100×0.25×4=100）仍得 100 分（权重等权兜底）。
        """
        p = _make_pattern(relative_strength=10.0, ma_bullish=True, volume_breakout_ratio=2.5, amount_yi=20.0)
        result = compute_non_limitup_score("000001", p, "platform_breakout", sector_rank=3)
        # 委托 compute_strategy_score：4 因子都满分 100 × 0.25 = 25 × 4 = 100
        assert result.strategy_score == 100.0


class TestRunNonLimitupFunnel:
    """非涨停类漏斗编排。"""

    def test_produces_candidates_with_pattern(self):
        """S094 T9-full：run_non_limitup_funnel 只产候选（挂 pattern + 透传 name/sector_rank/close）。

        旧自打分（strategy_score/排序）已删，归 score_candidates(market_scan)（2b-i-c）。
        """
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [
            {"code": "000001", "bars": bars, "sector": "电子", "name": "甲", "sector_rank": 1, "close": 14.0},
            {"code": "000002", "bars": bars, "sector": "电子"},
        ]
        result = run_non_limitup_funnel(candidates, "晴天", {"电子": 1})
        assert len(result) == 2
        by_code = {r["code"]: r for r in result}
        assert "pattern" in by_code["000001"]  # PatternScan 挂上
        assert "strategy_score" not in by_code["000001"]  # 不再自打分
        assert "passes_hard_standards" not in by_code["000001"]  # 不再过滤
        # 透传候选字段
        assert by_code["000001"]["name"] == "甲"
        assert by_code["000001"]["sector_rank"] == 1
        assert by_code["000001"]["close"] == 14.0
        # 无 name/close 的候选兜底
        assert by_code["000002"]["name"] == ""
        assert by_code["000002"]["close"] == 14  # bars[-1].close 兜底
        assert by_code["000002"]["sector_rank"] is None

    def test_produces_candidates_regardless_of_weather(self):
        """S094 T9-full：只产候选不做策略选择，weather 不影响产出（storm/sunny 同）。

        旧"storm 允许非涨停战法"语义移至 score_candidates(market_scan)（2b-i-c）。
        """
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [{"code": "000001", "bars": bars, "sector": "电子"}]
        assert len(run_non_limitup_funnel(candidates, "暴风雨", {"电子": 1})) == 1
        assert len(run_non_limitup_funnel(candidates, "晴天", {"电子": 1})) == 1

    def test_empty_candidates_returns_empty(self):
        result = run_non_limitup_funnel([], "晴天")
        assert result == []

    def test_no_quality_filter_in_produce_only(self):
        """S094 T9-full：只产候选不做硬剔除过滤（check_quality 闸前移 score_candidates market_scan，2b-i-c）。

        所有候选透传，无 passes_hard_standards 字段。
        """
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [{"code": "000001", "bars": bars, "sector": "电子"}]
        result = run_non_limitup_funnel(candidates, "晴天", {"电子": 1})
        assert len(result) == 1
        assert "passes_hard_standards" not in result[0]  # 不再过滤


class TestCandidateShapePassthrough:
    """S094 T9-transitional：run_non_limitup_funnel 透传统一候选 shape（R14 {name,sector_rank,close}）。

    sector_rank 字段=板块内个股排名（T7，调用方算，供 S3 market_scan_ctx/dragon_head R9）；
    与 sector_strength_rank（板块间，喂 compute_sector_strength_score 因子）同名不同语境。
    过渡态保留 compute_non_limitup_score 自打分（端点不破）；"删自打分"耦合 S3 T11+T16 时切。
    """

    def test_name_sector_rank_close_passed_through(self):
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [{"code": "000001", "name": "测试股", "bars": bars, "sector": "电子",
                       "sector_rank": 2, "close": 14.0}]
        result = run_non_limitup_funnel(candidates, "晴天", {"电子": 1})
        assert len(result) > 0
        for r in result:
            assert r["name"] == "测试股"
            assert r["sector_rank"] == 2  # 板块内（透传），非板块间 sector_strength_rank
            assert r["close"] == 14.0

    def test_close_falls_back_to_last_bar_when_missing(self):
        # 候选无 close/name/sector_rank 字段 → close 从 bars[-1] 兜底，name 默认空串，sector_rank None
        bars = [
            {"close": 10, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10, "ma10": 9.8, "ma20": 9.5},
            {"close": 11, "high": 11.5, "low": 10.4, "volume": 120, "amount": 1.2e9, "ma5": 10.5, "ma10": 10, "ma20": 9.6},
            {"close": 12, "high": 12.5, "low": 11.4, "volume": 150, "amount": 1.5e9, "ma5": 11, "ma10": 10.2, "ma20": 9.8},
            {"close": 13, "high": 13.5, "low": 12.4, "volume": 200, "amount": 2e9, "ma5": 11.5, "ma10": 10.5, "ma20": 10},
            {"close": 14, "high": 14.5, "low": 13.4, "volume": 300, "amount": 2.5e9, "ma5": 12, "ma10": 11, "ma20": 10.2},
        ]
        candidates = [{"code": "000001", "bars": bars, "sector": "电子"}]
        result = run_non_limitup_funnel(candidates, "晴天", {"电子": 1})
        assert len(result) > 0
        for r in result:
            assert r["close"] == 14  # bars[-1]["close"] 兜底
            assert r["name"] == ""
            assert r["sector_rank"] is None
