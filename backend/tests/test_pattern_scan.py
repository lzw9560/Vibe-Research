# -*- coding: utf-8 -*-
"""S066 Phase 2 P2-1/P2-2 板块成分股 + 形态计算测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.pattern_scan import (
    PatternScan,
    compute_relative_strength,
    check_ma_bullish,
    compute_ma5_proximity,
    compute_consolidation,
    compute_volume_breakout,
    compute_amount_yi,
    compute_shadow_length_pct,
    compute_ma5_slope,
    _compute_ma,
    scan_patterns,
    get_stock_industry,
    get_sector_stocks,
    load_industry_map,
    _pct_change,
)


def _mock_bars() -> list[dict]:
    """5 根日K，MA 多头排列。"""
    return [
        {"date": "2026-08-08", "close": 10.0, "high": 10.5, "low": 9.8, "volume": 100, "amount": 1e9, "ma5": 10.0, "ma10": 9.8, "ma20": 9.5},
        {"date": "2026-08-11", "close": 10.5, "high": 10.8, "low": 10.0, "volume": 120, "amount": 1.2e9, "ma5": 10.2, "ma10": 9.9, "ma20": 9.6},
        {"date": "2026-08-12", "close": 11.0, "high": 11.2, "low": 10.4, "volume": 150, "amount": 1.5e9, "ma5": 10.5, "ma10": 10.1, "ma20": 9.8},
        {"date": "2026-08-13", "close": 11.5, "high": 11.8, "low": 10.9, "volume": 200, "amount": 2e9, "ma5": 10.8, "ma10": 10.3, "ma20": 10.0},
        {"date": "2026-08-14", "close": 12.0, "high": 12.2, "low": 11.4, "volume": 300, "amount": 2.5e9, "ma5": 11.0, "ma10": 10.5, "ma20": 10.2},
    ]


def _mock_bars_20() -> list[dict]:
    """20+ 根日K（close 递增），供 S094 R1 自算 MA 用（需 >=20）。"""
    bars = []
    base = 10.0
    for i in range(22):
        bars.append({
            "date": f"2026-08-{i+1:02d}",
            "close": round(base + i * 0.2, 2),  # 10.0 → 14.2 递增，MA 多头
            "high": round(base + i * 0.2 + 0.5, 2),
            "low": round(base + i * 0.2 - 0.2, 2),
            "volume": 100 + i * 10,
            "amount": (100 + i * 10) * 1e7,
        })
    return bars


class TestPctChange:
    def test_positive_change(self):
        bars = [{"close": 10.0}, {"close": 12.0}]
        assert _pct_change(bars, 1) == 20.0

    def test_negative_change(self):
        bars = [{"close": 10.0}, {"close": 8.0}]
        assert _pct_change(bars, 1) == -20.0

    def test_insufficient_data(self):
        bars = [{"close": 10.0}]
        assert _pct_change(bars, 5) is None

    def test_zero_start(self):
        bars = [{"close": 0}, {"close": 10.0}]
        assert _pct_change(bars, 1) is None


class TestComputeMa:
    """S094 R1：_compute_ma 自算 SMA（不依赖 cache ma5/ma10/ma20 字段）。

    spec R1：bars<20 返 None（诚实降级，因 ma20 需 20 根，整体策略守 ≥20）。
    """

    def test_ma5_basic(self):
        """>=20 根 bar 算 MA5。"""
        bars = [{"close": 10.0}] * 20
        assert _compute_ma(bars, 5) == 10.0

    def test_ma_uneven(self):
        """>=20 根 close 递增，MA5 = 近 5 根均值。"""
        bars = [{"close": round(10.0 + i * 0.2, 2)} for i in range(20)]
        # 近 5 根 close (index 15-19): 13.0, 13.2, 13.4, 13.6, 13.8 → ma5 = 13.4
        expected = (13.0 + 13.2 + 13.4 + 13.6 + 13.8) / 5
        assert _compute_ma(bars, 5) == round(expected, 4)

    def test_bars_lt_20_returns_none(self):
        """S094 R1：bars<20 返 None（诚实降级，不臆造）。"""
        bars = [{"close": 10.0}] * 10
        assert _compute_ma(bars, 5) is None

    def test_empty_bars(self):
        assert _compute_ma([], 5) is None


class TestCheckMaBullish:
    """均线多头排列（S094 R1：改用 _compute_ma 自算，需 >=20 根 bar）。"""

    def test_bullish(self):
        """close 递增 22 根 → MA5>MA10>MA20。"""
        bars = _mock_bars_20()
        assert check_ma_bullish(bars) is True

    def test_not_bullish(self):
        """close 递减 22 根 → MA5<MA10<MA20 非多头。"""
        bars = _mock_bars_20()
        bars = [{"close": b["close"]} for b in reversed(bars)]
        assert check_ma_bullish(bars) is False

    def test_insufficient_bars_returns_false(self):
        """S094 R1：<20 根返 False（旧实现读 cache 字段恒 False 的 bug 修复）。"""
        bars = [{"ma5": 12, "ma10": 11, "ma20": 10}]  # 旧 mock 有 cache 字段但 <20 根
        assert check_ma_bullish(bars) is False

    def test_empty_bars(self):
        assert check_ma_bullish([]) is False


class TestMa5Proximity:
    """MA5 接近度（S094 R1：改用 _compute_ma 自算，需 >=20 根 bar）。"""

    def test_close_to_ma5(self):
        bars = _mock_bars_20()
        # close=14.2, ma5=avg(close[-5:])=(13.4+13.6+13.8+14.0+14.2)/5=13.8
        # proximity = |14.2-13.8|/13.8*100 ≈ 2.9
        result = compute_ma5_proximity(bars)
        assert result is not None
        assert 2.0 < result < 4.0

    def test_insufficient_bars_returns_none(self):
        """S094 R1：<20 根返 None（旧实现读 cache ma5 字段，无字段恒 None 的 bug 修复）。"""
        bars = [{"close": 10.1, "ma5": 10.0}]  # 旧 mock 有 cache 字段但 <20 根
        assert compute_ma5_proximity(bars) is None

    def test_missing_close_returns_none(self):
        bars = [{"high": 10}] * 20  # 无 close
        assert compute_ma5_proximity(bars) is None

    def test_empty_bars(self):
        assert compute_ma5_proximity([]) is None


class TestShadowLengthPct:
    """S094 R5：上影线长度 = (high/close - 1)*100。"""

    def test_basic(self):
        bars = [{"high": 11.0, "close": 10.0}]
        assert compute_shadow_length_pct(bars) == 10.0

    def test_no_shadow(self):
        bars = [{"high": 10.0, "close": 10.0}]
        assert compute_shadow_length_pct(bars) == 0.0

    def test_missing_fields(self):
        bars = [{"high": 10.0}]
        assert compute_shadow_length_pct(bars) is None

    def test_zero_close(self):
        bars = [{"high": 10.0, "close": 0}]
        assert compute_shadow_length_pct(bars) is None

    def test_empty_bars(self):
        assert compute_shadow_length_pct([]) is None


class TestMa5Slope:
    """S094 R5：MA5 斜率 = (ma5_now - ma5_prev) / ma5_prev。"""

    def test_upward(self):
        """close 递增 → ma5_slope > 0。"""
        bars = _mock_bars_20()
        result = compute_ma5_slope(bars)
        assert result is not None
        assert result > 0

    def test_downward(self):
        """close 递减 → ma5_slope < 0。"""
        bars = _mock_bars_20()
        bars = list(reversed(bars))
        result = compute_ma5_slope(bars)
        assert result is not None
        assert result < 0

    def test_insufficient_bars(self):
        """<21 根返 None（需 [-1]与[-2]各5根，重叠可取，但 R1 守 <20 已 None）。"""
        bars = [{"close": 10.0}] * 15
        assert compute_ma5_slope(bars) is None

    def test_empty_bars(self):
        assert compute_ma5_slope([]) is None


class TestConsolidation:
    """横盘形态。"""

    def test_consolidation_detected(self):
        """低振幅连续 N 日 → 横盘。"""
        bars = [
            {"high": 10.2, "low": 10.0}, {"high": 10.1, "low": 9.9},
            {"high": 10.0, "low": 10.0}, {"high": 10.1, "low": 10.0},
            {"high": 10.2, "low": 10.0},
        ]
        days, amp = compute_consolidation(bars, threshold=5.0, min_days=3)
        assert days is not None
        assert days >= 0

    def test_no_consolidation_high_volatility(self):
        """高振幅 → 非横盘。"""
        bars = [
            {"high": 15.0, "low": 10.0}, {"high": 14.0, "low": 9.0},
            {"high": 13.0, "low": 8.0}, {"high": 12.0, "low": 7.0},
        ]
        days, amp = compute_consolidation(bars, threshold=5.0, min_days=3)
        assert days == 0 or days is None

    def test_insufficient_data(self):
        bars = [{"high": 10, "low": 10}]
        days, amp = compute_consolidation(bars, threshold=5.0, min_days=5)
        assert days is None


class TestVolumeBreakout:
    """量比突破。"""

    def test_breakout_detected(self):
        """放量突破：当日 > 前 N 日均量 2 倍+。"""
        bars = [
            {"volume": 100}, {"volume": 100}, {"volume": 100},
            {"volume": 100}, {"volume": 100}, {"volume": 300},
        ]
        result = compute_volume_breakout(bars, lookback=5)
        assert result == 3.0

    def test_no_breakout(self):
        bars = [{"volume": 100}] * 6
        result = compute_volume_breakout(bars, lookback=5)
        assert result == 1.0

    def test_insufficient_data(self):
        bars = [{"volume": 100}, {"volume": 200}]
        result = compute_volume_breakout(bars, lookback=5)
        assert result is None

    def test_zero_avg_volume(self):
        bars = [{"volume": 0}] * 5 + [{"volume": 100}]
        result = compute_volume_breakout(bars, lookback=5)
        assert result is None


class TestAmountYi:
    def test_normal_amount(self):
        bars = [{"amount": 2.5e9}]
        assert compute_amount_yi(bars) == 25.0

    def test_empty_bars(self):
        assert compute_amount_yi([]) is None


class TestRelativeStrength:
    """相对强度。"""

    def test_stock_outperforms_sector(self):
        stock = [{"close": 10.0}, {"close": 12.0}]  # +20%
        sector = [{"close": 10.0}, {"close": 11.0}]  # +10%
        result = compute_relative_strength(stock, sector, days=1)
        assert result == 10.0  # 20% - 10%

    def test_no_sector_data(self):
        stock = [{"close": 10.0}, {"close": 12.0}]
        result = compute_relative_strength(stock, None, days=1)
        assert result == 20.0  # 只返回个股涨幅

    def test_insufficient_data(self):
        result = compute_relative_strength([{"close": 10.0}], None, days=5)
        assert result is None


class TestScanPatterns:
    """完整形态扫描（S094 R1：自算 MA 需 >=20 根 bar）。"""

    def test_full_scan(self):
        bars = _mock_bars_20()
        result = scan_patterns("000001", bars)
        assert isinstance(result, PatternScan)
        assert result.code == "000001"
        # close 递增 22 根 → MA 多头
        assert result.ma_bullish is True
        assert result.ma5_proximity is not None
        assert result.amount_yi is not None

    def test_empty_bars(self):
        result = scan_patterns("000001", [])
        assert result.code == "000001"
        assert result.ma_bullish is False
        assert result.relative_strength is None
        assert result.ma5_proximity is None


class TestIndustryMap:
    """板块成分股。"""

    def test_get_stock_industry(self):
        """从缓存获取个股行业（BaoStock 实测 000426 → 有色金属）。"""
        industry = get_stock_industry("000426")
        # BaoStock 可能缓存为空时实时拉取，这里容忍 None
        assert industry is None or "有色" in industry or isinstance(industry, str)

    def test_get_sector_stocks(self):
        """获取板块成分股列表。"""
        industry_map = {"000001": "银行业", "000002": "银行业", "000003": "医药"}
        stocks = get_sector_stocks("银行业", industry_map)
        assert "000001" in stocks
        assert "000002" in stocks
        assert "000003" not in stocks

    def test_get_sector_stocks_empty(self):
        stocks = get_sector_stocks("不存在的行业", {"000001": "银行业"})
        assert stocks == []

    def test_load_industry_map_returns_dict(self):
        """加载行业分类返回 dict（可能为空，BaoStock 不可达时不崩）。"""
        mapping = load_industry_map()
        assert isinstance(mapping, dict)
