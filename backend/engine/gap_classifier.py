# -*- coding: utf-8 -*-
"""S193 · 缺口理论集成——classify_gap 纯函数（grill Q1-Q17 定向后实现）。

缺口作 regime/变盘判断信号（不直接触发买卖，喂 AI 研判 + 融合消融验）。
四类缺口量化定义（spec §2，参数是 §44 sweep 空间非拍死）：
- 普通：缺口小 + 量比<2.0 + 3 日内回补
- 突破：量比≥2.0 + 3 日不回补 + 在 20 日前高/前低压力位
- 持续：突破缺口后 + 量比≥1.5 + 不回补
- 衰竭：第三个缺口 + 异常放量(量比≥3.0)或缩量(量比<1.0)

纯函数核心 `_classify_gap_from_bars(bars, target_idx)` 无 IO 可单测；
外壳 `classify_gap(code, date)` 拉 baostock 日 K 调核心。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 参数（§44 sweep 空间，spec §2 起点）
VOL_RATIO_BREAKOUT = 2.0      # 突破缺口量比阈值
VOL_RATIO_CONTINUATION = 1.5  # 持续缺口量比阈值
VOL_RATIO_EXHAUSTION_HIGH = 3.0  # 衰竭缺口异常放量阈值
VOL_RATIO_EXHAUSTION_LOW = 1.0   # 衰竭缺口缩量阈值（<此值）
FILL_WINDOW = 3                # 不回补窗口（A 股 T+1，3 日不回补=有效）
PRESSURE_LOOKBACK = 20         # 压力位回看天数（20 日前高/前低）
VOL_MA_WINDOW = 5             # 量比均线窗口（5 日均量）
GAP_HISTORY_WINDOW = 20       # 衰竭缺口判定：往前看多少日找历史缺口


def _bar_get(bar: dict, key: str, default: float = 0.0) -> float:
    """从 bar dict 取数值字段，容错（baostock key: date/open/high/low/close/volume）。"""
    v = bar.get(key, default)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _bar_date(bar: dict) -> str:
    """取 bar 日期（baostock 'date' 字段，YYYY-MM-DD）。"""
    return str(bar.get("date", ""))[:10]


def _vol_ratio(bars: list[dict], idx: int) -> float:
    """量比 = D 日 volume / 5 日均量（D-1..D-5）。"""
    if idx < 0 or idx >= len(bars):
        return 0.0
    vol_d = _bar_get(bars[idx], "volume")
    if vol_d <= 0:
        return 0.0
    prev_vols = [_bar_get(bars[i], "volume") for i in range(max(0, idx - VOL_MA_WINDOW), idx)]
    if not prev_vols or sum(prev_vols) <= 0:
        return 0.0
    ma = sum(prev_vols) / len(prev_vols)
    return vol_d / ma if ma > 0 else 0.0


def _detect_gap(bars: list[dict], idx: int) -> dict | None:
    """检测 D 日 vs D-1 日缺口。返 {direction: 向上/向下, gap_high, gap_low} 或 None。

    向上缺口：D.low > D-1.high（D 日最低 > 昨日最高，价格跳空向上）
    向下缺口：D.high < D-1.low（D 日最高 < 昨日最低，价格跳空向下）
    """
    if idx < 1 or idx >= len(bars):
        return None
    d_low = _bar_get(bars[idx], "low")
    d_high = _bar_get(bars[idx], "high")
    prev_high = _bar_get(bars[idx - 1], "high")
    prev_low = _bar_get(bars[idx - 1], "low")
    if d_low <= 0 or d_high <= 0 or prev_high <= 0 or prev_low <= 0:
        return None
    if d_low > prev_high:  # 向上缺口
        return {"direction": "向上", "gap_high": d_low, "gap_low": prev_high}
    if d_high < prev_low:  # 向下缺口
        return {"direction": "向下", "gap_high": prev_low, "gap_low": d_high}
    return None


def _is_filled(bars: list[dict], idx: int, gap: dict, window: int = FILL_WINDOW) -> bool:
    """判定缺口是否在 window 日内被回补。

    向上缺口回补：后续某日 low <= gap.gap_low（价格回到缺口下沿）
    向下缺口回补：后续某日 high >= gap.gap_high（价格回到缺口上沿）
    """
    direction = gap["direction"]
    for i in range(idx + 1, min(idx + 1 + window, len(bars))):
        if direction == "向上":
            if _bar_get(bars[i], "low") <= gap["gap_low"]:
                return True
        else:  # 向下
            if _bar_get(bars[i], "high") >= gap["gap_high"]:
                return True
    return False


def _at_pressure_level(bars: list[dict], idx: int, direction: str) -> bool:
    """判定 D 日缺口是否在 20 日前高/前低压力位附近（向上看前高，向下看前低）。

    向上缺口在压力位：D-1.high（缺口下沿=昨日最高）>= 20 日前高 → 昨日就在前高附近
    向下缺口在支撑位：D-1.low（缺口上沿=昨日最低）<= 20 日前低
    """
    if idx < 1 or idx >= len(bars):
        return False
    lookback = bars[max(0, idx - PRESSURE_LOOKBACK):idx]
    if len(lookback) < 5:  # 数据不足
        return False
    prev_highs = [_bar_get(b, "high") for b in lookback]
    prev_lows = [_bar_get(b, "low") for b in lookback]
    if direction == "向上":
        # D 日缺口下沿（=D-1.high）接近或突破 20 日前高
        pressure = max(prev_highs)
        d_prev_high = _bar_get(bars[idx - 1], "high")
        # 宽松：D-1.high >= 前高的 98%（接近压力位）或 D.low > 前高（突破压力位）
        return d_prev_high >= pressure * 0.98
    else:  # 向下
        pressure = min(prev_lows)
        d_prev_low = _bar_get(bars[idx - 1], "low")
        return d_prev_low <= pressure * 1.02  # 接近前低


def _count_recent_gaps(bars: list[dict], idx: int, window: int = GAP_HISTORY_WINDOW) -> list[dict]:
    """找 idx 前 window 日内的缺口序列（返 [{idx, gap}]）。供持续/衰竭缺口判定。"""
    gaps = []
    start = max(1, idx - window)
    for i in range(start, idx):
        g = _detect_gap(bars, i)
        if g is not None:
            gaps.append({"idx": i, "gap": g})
    return gaps


def _classify_gap_from_bars(bars: list[dict], target_idx: int, mode: str = "candidate") -> dict:
    """纯函数核心：从日 K 列表 + 目标日 idx 算缺口分类。无 IO，可单测。

    S201c candidate 语义（去前视）：
    - mode="candidate"（默认，实盘/检索用）：不查 _is_filled（未来 bar），突破/持续不 require not filled。
      只用 D 日 bar（量比+压力位+历史缺口），避免 _is_filled 扫 D+1..D+3 前视膨胀准确率。
    - mode="confirmed"（标签训练用）：查 _is_filled D+1..D+3 realized，突破/持续 require not filled。
      合法但 verify 有 label/metric 循环（D+1..D+3 fill ⊂ D+3 continuation metric）。

    返 {type: 普通/突破/持续/衰竭/无缺口, direction, regime, confidence, params, mode}。
    """
    result = {
        "type": "无缺口", "direction": "无", "regime": "无",
        "confidence": 0.0, "params": {}, "mode": mode,
    }
    if target_idx < 0 or target_idx >= len(bars):
        result["params"] = {"error": "target_idx 越界"}
        return result

    gap = _detect_gap(bars, target_idx)
    if gap is None:
        result["params"] = {"note": "D 日 vs D-1 无缺口"}
        return result

    direction = gap["direction"]
    vol_ratio = _vol_ratio(bars, target_idx)
    at_pressure = _at_pressure_level(bars, target_idx, direction)
    recent_gaps = _count_recent_gaps(bars, target_idx)
    n_recent = len(recent_gaps)

    # S201c: candidate 模式不查 _is_filled（去前视）；confirmed 模式用 D+1..D+3 realized
    if mode == "confirmed":
        filled = _is_filled(bars, target_idx, gap)
        fill_status = "3日内回补" if filled else "3日不回补"
    else:  # candidate（默认）
        filled = None  # 不查（未知，待 realized）
        fill_status = "candidate未知（待realized，去前视）"

    params = {
        "量比": round(vol_ratio, 3),
        "回补状态": fill_status,
        "压力位": "在前高/前低附近" if at_pressure else "不在压力位",
        "历史缺口数_20日": n_recent,
        "mode": mode,
    }

    # 分类逻辑（spec §2，顺序：突破 → 衰竭 → 持续 → 普通）：
    # S201c: 突破/持续 candidate 不 require not filled（去前视）；confirmed 才 require
    breakout_cond = (vol_ratio >= VOL_RATIO_BREAKOUT and at_pressure)
    continuation_cond = (vol_ratio >= VOL_RATIO_CONTINUATION and n_recent >= 1)
    if mode == "confirmed":
        breakout_cond = breakout_cond and not filled
        continuation_cond = continuation_cond and not filled

    gap_type = "普通"
    regime = "噪声"
    confidence = 0.3

    if breakout_cond:
        gap_type = "突破"
        regime = "趋势启动" if direction == "向上" else "反转"  # 向下突破=空头反转（A 股做空受限仅 regime）
        confidence = 0.7
    elif n_recent >= 2 and (vol_ratio >= VOL_RATIO_EXHAUSTION_HIGH or vol_ratio < VOL_RATIO_EXHAUSTION_LOW):
        # 衰竭缺口：第三个缺口 + 异常放量或缩量（不查 filled，:182 本就 clean）
        gap_type = "衰竭"
        # S198 gate 5/5 PASS 翻转（2026-09-13）：衰竭实测 5 日 continuation 55.2%
        # （regime-stratified bull 61.5% AND bear 56.6%，非牛月 artifact）→ 延续非反转。
        # 原 regime="反转" 被 day_paired(lift=1.33)+permutation(p=0.002)+regime+10日 全 PASS 证伪。
        # walk_forward oos_unstable（加分项非 gate）→ 标 provisional，待更长 OOS 数据复验。
        # 用"动能延续"非"趋势中继"避免与持续缺口(line 204) label 碰撞；direction 字段载向上/向下。
        regime = "动能延续"
        confidence = 0.65
    elif continuation_cond:
        # 持续缺口：之前有缺口（突破）+ 量比≥1.5
        gap_type = "持续"
        regime = "趋势中继"
        confidence = 0.6
    else:
        # 普通缺口：缺口小 + 量比<2.0 或 3 日内回补
        gap_type = "普通"
        regime = "噪声"
        confidence = 0.4 if (filled is True) else 0.35  # 回补快=更确定普通

    return {
        "type": gap_type,
        "direction": direction,
        "regime": regime,
        "confidence": confidence,
        "params": params,
        "mode": mode,
    }


def classify_gap(code: str, date: str) -> dict:
    """外壳：拉 baostock 日 K 调纯函数核心。返缺口分类。

    数据源：baostock query_history_k_data_plus（date/open/high/low/close/volume）。
    拉 60 日（覆盖 20 日压力位 + 3 日回补 + 20 日历史缺口窗口）。
    """
    try:
        from baostock.util import bs  # noqa: PLC0415
    except ImportError:
        return {"type": "无缺口", "direction": "无", "regime": "无",
                "confidence": 0.0, "params": {"error": "baostock 未装"}}

    # baostock 拉日 K（60 日，覆盖所有窗口）
    bars = _fetch_baostock_bars(code, date, count=60)
    if not bars:
        return {"type": "无缺口", "direction": "无", "regime": "无",
                "confidence": 0.0, "params": {"error": f"baostock 无数据 {code} {date}"}}

    # 找 target_date 的 idx
    target_idx = -1
    for i, b in enumerate(bars):
        if _bar_date(b) == date:
            target_idx = i
            break
    if target_idx < 0:
        return {"type": "无缺口", "direction": "无", "regime": "无",
                "confidence": 0.0, "params": {"error": f"target_date {date} 不在 bars"}}

    return _classify_gap_from_bars(bars, target_idx)


def _fetch_baostock_bars(code: str, end_date: str = "", count: int = 60) -> list[dict]:
    """baostock 拉日 K（复用 engine.bars_provider._baostock_a_share_hist）。

    S201c arity fix: 原 3 参调用 _baostock_a_share_hist(code, start, end_date) vs 签名 1 参 (code: str)
    → TypeError 被 except 吞返[] → classify_gap 恒"baostock 无数据"，query_gap_regime 死代码。
    修：只传 code（_baostock_a_share_hist 内部算最近 400 天，覆盖 60 日窗口 + 20 日压力位 + 3 日 + 20 日历史）。
    """
    try:
        from engine.bars_provider import _baostock_a_share_hist  # noqa: PLC0415
        # _baostock_a_share_hist(code) 1 参，返最近 400 天 bars（含 pctChg/isST）
        return _baostock_a_share_hist(code) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("classify_gap baostock 拉 %s 失败: %s", code, e)
        return []


__all__ = [
    "classify_gap", "_classify_gap_from_bars", "_detect_gap", "_vol_ratio",
    "_is_filled", "_at_pressure_level", "_count_recent_gaps",
    "VOL_RATIO_BREAKOUT", "VOL_RATIO_CONTINUATION", "VOL_RATIO_EXHAUSTION_HIGH",
    "VOL_RATIO_EXHAUSTION_LOW", "FILL_WINDOW", "PRESSURE_LOOKBACK",
]
