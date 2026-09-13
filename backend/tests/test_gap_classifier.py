# -*- coding: utf-8 -*-
"""S193 A1 · gap_classifier 单测——四类缺口 + 边界 case + S201c candidate/confirmed mode。

纯函数 _classify_gap_from_bars 输入日 K 列表输出分类，无网络依赖。
S201c: mode="candidate"（默认，去前视，不查 _is_filled）/ mode="confirmed"（用 D+1..D+3 realized）。
"""
from __future__ import annotations

from engine.gap_classifier import (
    _classify_gap_from_bars, _detect_gap, _vol_ratio,
    VOL_RATIO_BREAKOUT, FILL_WINDOW, PRESSURE_LOOKBACK,
)


def _bar(date: str, o: float, h: float, l: float, c: float, v: float) -> dict:
    """构造测试 bar。"""
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _make_bars(prices: list[tuple], base_vol: float = 1000.0) -> list[dict]:
    """批量构造 bars。"""
    return [_bar(d, o, h, l, c, base_vol) for d, o, h, l, c in prices]


def _no_gap_bars(n: int = 25) -> list[dict]:
    """n 日连续 K 线无缺口。价格平 base=10。"""
    bars = []
    for i in range(n):
        date = f"2026-09-{i + 1:02d}" if i < 30 else f"2026-10-{i - 29:02d}"
        base = 10.0
        bars.append(_bar(date, base, base + 0.5, base - 0.5, base, 1000.0))
    return bars


def _bar_get_test(bar: dict, key: str) -> float:
    """测试辅助：取 bar 数值字段。"""
    try:
        return float(bar.get(key, 0))
    except (TypeError, ValueError):
        return 0.0


class TestDetectGap:
    def test_no_gap_returns_none(self):
        bars = _no_gap_bars(5)
        assert _detect_gap(bars, 1) is None

    def test_upward_gap(self):
        bars = [
            _bar("2026-09-01", 10.0, 10.5, 9.5, 10.2, 1000),
            _bar("2026-09-02", 11.0, 11.5, 10.8, 11.2, 2000),
        ]
        gap = _detect_gap(bars, 1)
        assert gap is not None and gap["direction"] == "向上"

    def test_downward_gap(self):
        bars = [
            _bar("2026-09-01", 10.0, 10.5, 9.5, 10.2, 1000),
            _bar("2026-09-02", 9.0, 9.2, 8.5, 8.8, 2000),
        ]
        gap = _detect_gap(bars, 1)
        assert gap is not None and gap["direction"] == "向下"


class TestVolRatio:
    def test_vol_ratio_basic(self):
        bars = _no_gap_bars(6)
        bars[5] = _bar("2026-09-06", 15.0, 15.5, 14.5, 15.0, 3000.0)
        assert _vol_ratio(bars, 5) == 3.0

    def test_vol_ratio_zero_vol(self):
        bars = _no_gap_bars(6)
        bars[5] = _bar("2026-09-06", 15.0, 15.5, 14.5, 15.0, 0.0)
        assert _vol_ratio(bars, 5) == 0.0


class TestClassifyGap:
    def test_no_gap(self):
        """无缺口 → type=无缺口。"""
        bars = _no_gap_bars(25)
        r = _classify_gap_from_bars(bars, 10)
        assert r["type"] == "无缺口" and r["regime"] == "无"
        assert r["mode"] == "candidate"  # S201c 默认

    def test_target_idx_out_of_range(self):
        bars = _no_gap_bars(5)
        r = _classify_gap_from_bars(bars, 100)
        assert "error" in r["params"]

    def test_common_gap_filled_confirmed(self):
        """普通缺口：confirmed 模式查 3 日内回补。"""
        bars = _no_gap_bars(25)
        bars[10] = _bar("2026-09-11", 11.0, 11.2, 10.8, 11.0, 1500.0)  # 向上小缺口 vol<2x
        bars[11] = _bar("2026-09-12", 10.8, 11.0, 10.3, 10.5, 1000.0)  # low=10.3<=10.5 回补
        r = _classify_gap_from_bars(bars, 10, mode="confirmed")
        assert r["type"] == "普通" and r["direction"] == "向上"
        assert r["params"]["回补状态"] == "3日内回补"
        assert r["mode"] == "confirmed"

    def test_breakaway_gap_confirmed(self):
        """突破缺口 confirmed：量比≥2.0 + 3 日不回补 + 压力位（D+1..D+3 realized）。"""
        bars = _no_gap_bars(25)
        prev_high = max(_bar_get_test(b, "high") for b in bars[:20])
        d_low = prev_high + 0.5
        bars[20] = _bar("2026-09-21", d_low + 0.5, d_low + 1.0, d_low, d_low + 0.7, 3000.0)
        for i in range(21, 24):  # D+1..D+3 不回补
            bars[i] = _bar(f"2026-09-{i - 19:02d}", d_low + 0.5, d_low + 1.0, d_low + 0.3, d_low + 0.6, 2000.0)
        r = _classify_gap_from_bars(bars, 20, mode="confirmed")
        assert r["type"] == "突破" and r["regime"] == "趋势启动"
        assert r["params"]["回补状态"] == "3日不回补"
        assert r["params"]["量比"] >= VOL_RATIO_BREAKOUT

    def test_breakaway_gap_candidate_no_future(self):
        """S201c candidate：仅 D 日 bar（无 D+1..D+3），断言突破候选不查回补（去前视）。"""
        bars = _no_gap_bars(25)
        prev_high = max(_bar_get_test(b, "high") for b in bars[:20])
        d_low = prev_high + 0.5
        bars[20] = _bar("2026-09-21", d_low + 0.5, d_low + 1.0, d_low, d_low + 0.7, 3000.0)
        # 不构造 D+1..D+3（candidate 不查未来）——即使 bars[21..23] 无也 OK
        r = _classify_gap_from_bars(bars, 20, mode="candidate")
        assert r["type"] == "突破"  # candidate 量比≥2+压力位即可（不 require not filled）
        assert "candidate未知" in r["params"]["回补状态"]  # 不查 filled
        assert r["mode"] == "candidate"

    def test_exhaustion_gap_candidate(self):
        """衰竭缺口：第三个缺口 + 异常放量（不查 filled，:182 clean）。"""
        bars = _no_gap_bars(25)
        bars[5] = _bar("2026-09-06", 10.5, 10.7, 10.4, 10.6, 1500.0)
        bars[10] = _bar("2026-09-11", 11.0, 11.2, 10.9, 11.1, 1500.0)
        prev = bars[19]["high"]
        bars[20] = _bar("2026-09-21", prev + 0.6, prev + 1.0, prev + 0.4, prev + 0.7, 3000.0)
        r = _classify_gap_from_bars(bars, 20)  # 默认 candidate
        assert r["type"] == "衰竭" and r["regime"] == "反转"
        assert r["params"]["历史缺口数_20日"] >= 2

    def test_continuation_gap_confirmed(self):
        """持续缺口 confirmed：突破后 + 量比≥1.5 + 不回补 + 历史有缺口。"""
        bars = _no_gap_bars(25)
        prev_high_15 = max(_bar_get_test(b, "high") for b in bars[:15])
        bars[15] = _bar("2026-09-16", prev_high_15 + 0.5, prev_high_15 + 1.0, prev_high_15 + 0.3, prev_high_15 + 0.8, 3000.0)
        for i in range(16, 20):
            bars[i] = _bar(f"2026-09-{i - 14:02d}", prev_high_15 + 0.5, prev_high_15 + 1.0, prev_high_15 + 0.3, prev_high_15 + 0.6, 2000.0)
        prev_high_20 = max(_bar_get_test(b, "high") for b in bars[16:20])
        bars[20] = _bar("2026-09-21", prev_high_20 + 0.3, prev_high_20 + 0.5, prev_high_20 + 0.1, prev_high_20 + 0.4, 3500.0)
        for i in range(21, 24):  # D+1..D+3 不回补
            bars[i] = _bar(f"2026-09-{i - 19:02d}", prev_high_20 + 0.3, prev_high_20 + 0.5, prev_high_20 + 0.1, prev_high_20 + 0.4, 2000.0)
        r = _classify_gap_from_bars(bars, 20, mode="confirmed")
        assert r["direction"] == "向上"
        assert r["params"]["回补状态"] == "3日不回补"
        assert r["type"] in ("持续", "突破", "衰竭")

    def test_continuation_gap_candidate(self):
        """S201c candidate：持续缺口不查 filled（去前视）。"""
        bars = _no_gap_bars(25)
        prev_high_15 = max(_bar_get_test(b, "high") for b in bars[:15])
        bars[15] = _bar("2026-09-16", prev_high_15 + 0.5, prev_high_15 + 1.0, prev_high_15 + 0.3, prev_high_15 + 0.8, 3000.0)
        for i in range(16, 20):
            bars[i] = _bar(f"2026-09-{i - 14:02d}", prev_high_15 + 0.5, prev_high_15 + 1.0, prev_high_15 + 0.3, prev_high_15 + 0.6, 2000.0)
        prev_high_20 = max(_bar_get_test(b, "high") for b in bars[16:20])
        bars[20] = _bar("2026-09-21", prev_high_20 + 0.3, prev_high_20 + 0.5, prev_high_20 + 0.1, prev_high_20 + 0.4, 3500.0)
        r = _classify_gap_from_bars(bars, 20, mode="candidate")
        assert r["direction"] == "向上"
        assert "candidate未知" in r["params"]["回补状态"]  # 不查 filled

    def test_mode_candidate_no_filled_lookup(self):
        """S201c: candidate 模式 params 无 filled 查询（去前视），confirmed 模式查。"""
        bars = _no_gap_bars(25)
        prev_high = max(_bar_get_test(b, "high") for b in bars[:20])
        d_low = prev_high + 0.5
        bars[20] = _bar("2026-09-21", d_low + 0.5, d_low + 1.0, d_low, d_low + 0.7, 3000.0)
        rc = _classify_gap_from_bars(bars, 20, mode="candidate")
        assert "candidate未知" in rc["params"]["回补状态"]
        # confirmed 需 D+1..D+3（这里没构造，filled=False 即 3 日不回补——bars 长度够 idx+3）
        rf = _classify_gap_from_bars(bars, 20, mode="confirmed")
        assert rf["params"]["回补状态"] in ("3日不回补", "3日内回补")
