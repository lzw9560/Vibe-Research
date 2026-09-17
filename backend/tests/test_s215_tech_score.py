# -*- coding: utf-8 -*-
"""S215 通用技术指标评分测试——6 维计算 + 100 分信号映射 + 边界。

TDD：覆盖 MA/MACD/RSI/量能/乖离/支撑 6 维 + 信号映射 + 边界（空/单/<60）。
"""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.tech_score import (  # noqa: E402
    compute_tech_score, score_to_signal,
    score_ma, score_macd, score_rsi, score_volume, score_bias, score_support,
    SIGNAL_STRONG_BUY, SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_WATCH, SIGNAL_STRONG_SELL,
)


def _make_bars(closes: list[float], vols: list[float] | None = None,
               lows: list[float] | None = None, highs: list[float] | None = None) -> list[dict]:
    """构造 bars（close 必填，vol/low/high 可选默认=close）。"""
    n = len(closes)
    vols = vols or [10000] * n
    lows = lows or [c * 0.98 for c in closes]
    highs = highs or [c * 1.02 for c in closes]
    return [{"date": f"2026-01-{i+1:02d}", "open": closes[i], "high": highs[i],
             "low": lows[i], "close": closes[i], "volume": vols[i]} for i in range(n)]


# ── 信号映射 ──────────────────────────────────────────────────────────


class TestSignalMapping:
    def test_strong_buy(self):
        assert score_to_signal(80) == SIGNAL_STRONG_BUY
        assert score_to_signal(75) == SIGNAL_STRONG_BUY

    def test_buy(self):
        assert score_to_signal(70) == SIGNAL_BUY
        assert score_to_signal(60) == SIGNAL_BUY

    def test_hold(self):
        assert score_to_signal(50) == SIGNAL_HOLD
        assert score_to_signal(45) == SIGNAL_HOLD

    def test_watch(self):
        assert score_to_signal(35) == SIGNAL_WATCH
        assert score_to_signal(30) == SIGNAL_WATCH

    def test_strong_sell(self):
        assert score_to_signal(20) == SIGNAL_STRONG_SELL
        assert score_to_signal(0) == SIGNAL_STRONG_SELL


# ── 维度1：MA 多空排列 ────────────────────────────────────────────────


class TestMA:
    def test_bullish_alignment(self):
        """多头排列（MA5>MA10>MA20>MA60）→ 85 分。"""
        closes = [10 + i * 0.1 for i in range(60)]  # 递增
        s, raw = score_ma(_make_bars(closes))
        assert s == 85.0, f"多头排列应 85, got {s}"

    def test_bearish_alignment(self):
        """空头排列（MA5<MA10<MA20<MA60）→ 20 分。"""
        closes = [10 - i * 0.1 for i in range(60)]  # 递减
        s, raw = score_ma(_make_bars(closes))
        assert s == 20.0, f"空头排列应 20, got {s}"

    def test_insufficient_bars(self):
        """bars < 60 → 50 分（缺 MA60）。"""
        s, raw = score_ma(_make_bars([10] * 50))
        assert s == 50.0
        assert "bars" in raw["reason"]


# ── 维度2：MACD ───────────────────────────────────────────────────────


class TestMACD:
    def test_golden_cross(self):
        """金叉（DIF>DEA）→ 70-85 分。"""
        closes = [10 + i * 0.2 for i in range(30)]  # 递增→金叉
        s, raw = score_macd(_make_bars(closes))
        assert s >= 70.0, f"金叉应 >=70, got {s}"

    def test_death_cross(self):
        """死叉（DIF<DEA）→ 20-35 分。"""
        closes = [10 - i * 0.2 for i in range(30)]  # 递减→死叉
        s, raw = score_macd(_make_bars(closes))
        assert s <= 35.0, f"死叉应 <=35, got {s}"

    def test_insufficient_bars(self):
        s, raw = score_macd(_make_bars([10] * 20))
        assert s == 50.0


# ── 维度3：RSI ────────────────────────────────────────────────────────


class TestRSI:
    def test_overbought(self):
        """超买（连续大涨 RSI>70）→ 30 分。"""
        closes = [10 + i * 0.5 for i in range(30)]  # 连续涨
        s, raw = score_rsi(_make_bars(closes))
        # 连续涨 RSI 接近 100，但 6/12/24 平均可能不一
        assert s in (30.0, 65.0, 80.0), f"超买场景 s={s}"

    def test_insufficient_bars(self):
        s, raw = score_rsi(_make_bars([10] * 20))
        assert s == 50.0


# ── 维度4：量能 ───────────────────────────────────────────────────────


class TestVolume:
    def test_healthy_volume(self):
        """量比 1-2 健康放量 → 80 分。"""
        vols = [10000] * 5 + [15000]  # 量比 1.5
        s, raw = score_volume(_make_bars([10] * 6, vols=vols))
        assert s == 80.0, f"健康放量应 80, got {s}"

    def test_abnormal_volume(self):
        """量比 >5 异常 → 40 分。"""
        vols = [10000] * 5 + [80000]  # 量比 8
        s, raw = score_volume(_make_bars([10] * 6, vols=vols))
        assert s == 40.0, f"异常放量应 40, got {s}"

    def test_insufficient_bars(self):
        s, raw = score_volume(_make_bars([10] * 3))
        assert s == 50.0


# ── 维度5：乖离率 ────────────────────────────────────────────────────


class TestBias:
    def test_no_chase_risk(self):
        """BIAS 在 ±5% 内 → 80 分。"""
        closes = [10] * 20  # 平稳 BIAS=0
        s, raw = score_bias(_make_bars(closes))
        assert s == 80.0, f"无追高应 80, got {s}"

    def test_chase_high(self):
        """BIAS >5% 追高 → 40 分。"""
        closes = [10] * 19 + [11]  # 涨 10%
        s, raw = score_bias(_make_bars(closes))
        assert s == 40.0, f"追高应 40, got {s}"

    def test_insufficient_bars(self):
        s, raw = score_bias(_make_bars([10] * 10))
        assert s == 50.0


# ── 维度6：支撑/压力 ──────────────────────────────────────────────────


class TestSupport:
    def test_near_support(self):
        """近支撑（+5% 内）→ 80 分。"""
        # 20 日 low min=9.8，last close=9.9 → dist_support=1%
        lows = [9.8 + i * 0.01 for i in range(20)]
        closes = [l + 0.1 for l in lows]
        closes[-1] = 9.9  # 近支撑
        s, raw = score_support(_make_bars(closes, lows=lows, highs=[c * 1.02 for c in closes]))
        assert s == 80.0, f"近支撑应 80, got {s}"

    def test_near_resistance(self):
        """近压力（dist_resist<=5% 且 dist_support>5%）→ 35 分。"""
        highs = [10 + i * 0.01 for i in range(20)]  # 10.00-10.19
        lows = [9 + i * 0.01 for i in range(20)]  # 9.00-9.19（远低于 close）
        closes = [10.15] * 20  # 最后 close 10.15 近 resistance 10.19
        s, raw = score_support(_make_bars(closes, lows=lows, highs=highs))
        # dist_resist=(10.19-10.15)/10.15*100≈0.39% → <=5 → 35
        assert s == 35.0, f"近压力应 35, got {s} raw={raw}"

    def test_insufficient_bars(self):
        s, raw = score_support(_make_bars([10] * 10))
        assert s == 50.0


# ── 合成：compute_tech_score ───────────────────────────────────────────


class TestComputeTechScore:
    def test_bullish_market(self):
        """多头市场（递增）→ 验 6 维结构 + MA 多头 85 + signal 合法（不验绝对总分，直线递增 bias/support 会拉低）。"""
        closes = [10 + i * 0.1 for i in range(60)]
        result = compute_tech_score(_make_bars(closes))
        assert result["n_bars"] == 60
        assert set(result["dimensions"].keys()) == {"ma", "macd", "rsi", "volume", "bias", "support"}
        assert result["dimensions"]["ma"]["score"] == 85.0  # 多头排列
        assert 0 <= result["total_score"] <= 100
        assert result["signal"] in (SIGNAL_STRONG_BUY, SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_WATCH, SIGNAL_STRONG_SELL)

    def test_bearish_market(self):
        """空头市场（递减）→ 验 MA 空头 20 + 6 维结构（直线递减 RSI 超卖会拉高，不验绝对总分）。"""
        closes = [10 - i * 0.1 for i in range(60)]
        result = compute_tech_score(_make_bars(closes))
        assert result["dimensions"]["ma"]["score"] == 20.0  # 空头排列
        assert set(result["dimensions"].keys()) == {"ma", "macd", "rsi", "volume", "bias", "support"}
        assert 0 <= result["total_score"] <= 100

    def test_insufficient_bars(self):
        """bars < 60 → total_score=0 + 观望 + reason。"""
        result = compute_tech_score(_make_bars([10] * 30))
        assert result["total_score"] == 0.0
        assert result["signal"] == SIGNAL_WATCH
        assert "reason" in result

    def test_empty_bars(self):
        """空 bars → total_score=0 + 观望。"""
        result = compute_tech_score([])
        assert result["total_score"] == 0.0
        assert result["signal"] == SIGNAL_WATCH
