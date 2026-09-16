# -*- coding: utf-8 -*-
"""S205 T2: 7 新维度 compute（纯函数，返 [0,1]，缺数据=0，immutable）。

7 compute：
- auction_signal（BLOCKER：A 股竞价历史无免费源→skipif 返 0.0）
- expectation_gap_reversal（T-1 close + T open 差代理）
- volume_rhythm（首板倍量→缩量→再放量三段）
- pullback_structure（回调深度/天数/不破起涨点）
- leader_identity（sector_rank≤3/lbc≥2/high_gene 综合）
- pullback_rhythm（距上次涨停 3-5 日 + 第一次回调）
- reversal_confirm（close 突上影中点 + 吞没 + 放量）

data_source 声明在 s205_registry.py DIMENSION_REGISTRY（不臆造）。
纯函数：同输入→同输出，无副作用，不写 DB/不调网络。
"""
from __future__ import annotations

from typing import Any


def _clip01(v: float) -> float:
    """clip 到 [0,1]，NaN/None→0.0。"""
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return max(0.0, min(1.0, f))


# ── T2g: auction_signal（BLOCKER）──────────────────────────────────
AUCTION_SIGNAL_BLOCKER: bool = True
AUCTION_SIGNAL_BLOCKER_REASON: str = (
    "A 股竞价历史数据无免费源：Tushare stk_auction / hithink 付费；"
    "akshare/腾讯/新浪 实时竞价无历史。compute_auction_signal 返 0.0（一字竞价 T4a 标 BLOCKER 不实现）"
)


def compute_auction_signal(code: str, date: str, **kwargs: Any) -> float:
    """BLOCKER：A 股竞价历史无免费源→返 0.0。

    一字竞价战法的 auction_signal 维度无数据源（Tushare/hithink 付费，
    akshare/腾讯/新浪 无历史竞价）。标 BLOCKER skipif，返 0.0（不臆造）。
    """
    return 0.0


# ── T2f: expectation_gap_reversal（预期差反包）─────────────────────
def compute_expectation_gap_reversal(
    code: str, date: str, bars: list[dict] | None = None, **kwargs: Any
) -> float:
    """预期差反包：T-1 close + T open 差（高开%）+ 开盘量比代理。

    无竞价量免费源→用 T 日 open vs T-1 close 差（高开%）+ T 日 volume vs T-1 volume 比。
    高开 2-7% + 量比≥1.0 → 高分；过高（>7% gap trap）/过低（<2%）→ 扣分。
    缺 bars / 数据不足 → 0.0。
    """
    if not bars or len(bars) < 2:
        return 0.0
    d_idx = next((i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == date), None)
    if d_idx is None or d_idx < 1:
        return 0.0
    prev_close = bars[d_idx - 1].get("close")
    open_price = bars[d_idx].get("open")
    prev_vol = bars[d_idx - 1].get("volume")
    cur_vol = bars[d_idx].get("volume")
    if not (prev_close and open_price and prev_vol and cur_vol):
        return 0.0
    try:
        gap_pct = (float(open_price) - float(prev_close)) / float(prev_close) * 100
        vol_ratio = float(cur_vol) / float(prev_vol) if float(prev_vol) > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    # 高开 2-7% 最佳，>7% gap trap 扣分，<2% 弱
    if 2.0 <= gap_pct <= 7.0:
        gap_score = 1.0 - abs(gap_pct - 4.5) / 4.5  # 4.5% 最佳
    elif gap_pct > 7.0:
        gap_score = max(0.0, 0.3 - (gap_pct - 7.0) * 0.05)  # gap trap
    else:
        gap_score = max(0.0, gap_pct / 2.0)  # <2% 弱
    vol_score = _clip01(vol_ratio / 3.0)  # 量比 3x 封顶
    return _clip01(gap_score * 0.6 + vol_score * 0.4)


# ── T2b: volume_rhythm（量能节奏）──────────────────────────────────
def compute_volume_rhythm(bars: list[dict] | None = None, **kwargs: Any) -> float:
    """量能节奏：首板倍量→缩量→再放量三段连续性评分。

    三段：首板日 volume / 前日 volume ≥1.5（倍量）→ 次日 volume / 首板 volume ≤0.7（缩量）
    → 第三日 volume / 次日 volume ≥1.2（再放量）。三段命中 → 高分。
    缺 bars / <3 段 → 0.0。
    """
    if not bars or len(bars) < 3:
        return 0.0
    try:
        v = [float(b.get("volume", 0) or 0) for b in bars[-3:]]
    except (TypeError, ValueError):
        return 0.0
    if v[0] <= 0 or v[1] <= 0 or v[2] <= 0:
        return 0.0
    surge_ratio = v[0] / v[1] if v[1] > 0 else 0  # 首板 vs 次日（注：bars[-3] 是最早）
    # 重新对齐：bars[-3]=首板, bars[-2]=缩量日, bars[-1]=再放量日
    first_vol = v[0]  # 首板
    shrink_vol = v[1]  # 次日缩量
    retry_vol = v[2]  # 第三日再放量
    surge = first_vol / shrink_vol if shrink_vol > 0 else 0  # 首板倍量 vs 前日（需 4 段，简化用 3 段代理）
    # 简化 3 段：首板高 → 缩量 → 再放量
    shrink_ok = shrink_vol < first_vol * 0.7  # 缩量
    retry_ok = retry_vol > shrink_vol * 1.2  # 再放量
    score = 0.0
    if shrink_ok:
        score += 0.4
    if retry_ok:
        score += 0.4
    # 首板倍量（vs 缩量日）≥1.5
    if first_vol / shrink_vol >= 1.5 if shrink_vol > 0 else False:
        score += 0.2
    return _clip01(score)


# ── T2a: pullback_structure（回调结构）────────────────────────────
def compute_pullback(bars: list[dict] | None = None, **kwargs: Any) -> float:
    """回调结构：回调深度 20-30% 最佳 + 不破首板起涨点。

    回调深度 = (peak - trough) / peak。20-30% → 高分；过深（>40%）/过浅（<10%）→ 扣分。
    不破起涨点（trough ≥ 首板前 close）→ 加分。
    缺 bars → 0.0。
    """
    if not bars or len(bars) < 2:
        return 0.0
    try:
        closes = [float(b.get("close", 0) or 0) for b in bars]
    except (TypeError, ValueError):
        return 0.0
    closes = [c for c in closes if c > 0]
    if len(closes) < 2:
        return 0.0
    peak = max(closes)
    trough = min(closes)
    if peak <= 0:
        return 0.0
    depth_pct = (peak - trough) / peak * 100
    # 20-30% 最佳
    if 20.0 <= depth_pct <= 30.0:
        depth_score = 1.0 - abs(depth_pct - 25.0) / 25.0
    elif 10.0 <= depth_pct < 20.0:
        depth_score = (depth_pct - 10.0) / 10.0 * 0.6  # 过浅
    elif 30.0 < depth_pct <= 40.0:
        depth_score = max(0.0, 0.6 - (depth_pct - 30.0) * 0.03)  # 过深
    else:
        depth_score = 0.0  # <10% 或 >40%
    # 不破起涨点（trough >= 首个 close）
    breakout_ok = trough >= closes[0] * 0.95  # 5% 容差
    score = depth_score * 0.7 + (0.3 if breakout_ok else 0.0)
    return _clip01(score)


# ── T2d: leader_identity（龙头确认）───────────────────────────────
def compute_leader_identity(
    sector_rank: int | None = None,
    lbc: int | None = None,
    high_gene: int | None = None,
    **kwargs: Any,
) -> float:
    """龙头确认综合：sector_rank≤3 + lbc≥2 + high_gene=1。

    三条件命中数 / 3 → [0,1]。缺数据→该条件 0。
    """
    score = 0.0
    if sector_rank is not None and sector_rank <= 3:
        score += 1.0
    if lbc is not None and lbc >= 2:
        score += 1.0
    if high_gene is not None and high_gene == 1:
        score += 1.0
    return _clip01(score / 3.0)


# ── T2e: pullback_rhythm（回调节奏）───────────────────────────────
def compute_pullback_rhythm(
    days_since_last_zt: int | None = None,
    pullback_pct: float | None = None,
    is_first_pullback: bool | None = None,
    **kwargs: Any,
) -> float:
    """回调节奏：距上次涨停 3-5 日 + 回调 20-30% + 第一次回调。

    三条件加权（0.4+0.4+0.2）。缺数据→该条件 0。
    """
    score = 0.0
    if days_since_last_zt is not None and 3 <= days_since_last_zt <= 5:
        score += 0.4
    elif days_since_last_zt is not None and 2 <= days_since_last_zt <= 7:
        score += 0.2  # 容差
    if pullback_pct is not None and 20.0 <= pullback_pct <= 30.0:
        score += 0.4
    if is_first_pullback is True:
        score += 0.2
    return _clip01(score)


# ── T2c: reversal_confirm（反包确认）──────────────────────────────
def compute_reversal_confirm(bars: list[dict] | None = None, **kwargs: Any) -> float:
    """反包确认：close 突破上影中点 + 吞没 + 放量。

    三条件：
    - close ≥ 前日上影中点 (upper_shadow_mid = (high+close)/2 前日) → 突破
    - close ≥ 前日 open 且 open ≤ 前日 close → 吞没
    - volume / 前日 volume ≥ 1.2 → 放量
    缺 bars → 0.0。
    """
    if not bars or len(bars) < 2:
        return 0.0
    try:
        prev = bars[-2]
        cur = bars[-1]
        prev_high = float(prev.get("high", 0) or 0)
        prev_close = float(prev.get("close", 0) or 0)
        prev_open = float(prev.get("open", 0) or 0)
        cur_close = float(cur.get("close", 0) or 0)
        cur_open = float(cur.get("open", 0) or 0)
        prev_vol = float(prev.get("volume", 0) or 0)
        cur_vol = float(cur.get("volume", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    if not (prev_high and prev_close and cur_close):
        return 0.0
    # 前日上影中点（前日 high + close）/2
    shadow_mid = (prev_high + prev_close) / 2
    breakout = cur_close >= shadow_mid
    # 吞没：cur close ≥ prev open 且 cur open ≤ prev close
    engulf = cur_close >= prev_open and cur_open <= prev_close
    # 放量
    vol_surge = (cur_vol / prev_vol >= 1.2) if prev_vol > 0 else False
    score = 0.0
    if breakout:
        score += 0.4
    if engulf:
        score += 0.3
    if vol_surge:
        score += 0.3
    return _clip01(score)


__all__ = [
    "AUCTION_SIGNAL_BLOCKER",
    "AUCTION_SIGNAL_BLOCKER_REASON",
    "compute_auction_signal",
    "compute_expectation_gap_reversal",
    "compute_volume_rhythm",
    "compute_pullback",
    "compute_leader_identity",
    "compute_pullback_rhythm",
    "compute_reversal_confirm",
]
