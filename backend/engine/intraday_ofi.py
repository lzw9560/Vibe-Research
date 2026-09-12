# -*- coding: utf-8 -*-
"""S176 R2 — OFI + bid_ask_pressure 纯函数（无 IO，可单测）。

**OFI（Order Flow Imbalance）** = (Σbuy_vol - Σsell_vol) / (Σbuy_vol + Σsell_vol) ∈ [-1, 1]
（归一化，跨股可比）。涨停后 sell=0 → OFI=1.0（全买压）；后退化为 Δseal_amount
（封单净增=买压，KG 因子 3）——S176 涨停股用 seal_amount 替代 OFI。

**bid_ask_pressure** = Σbuy_vol / Σsell_vol（涨停 sell=0 → ∞，cap PRESSURE_CAP 999.0）。

纯函数：输入 buy/sell levels list[{level, price, vol}]（tencent _parse_gtimg levels() shape），
输出 float。vol 缺失/None/非数字当 0（数据质量门，防 tencent 偶发坏档）。
"""
from __future__ import annotations

#: 涨停 sell=0 时 pressure cap（避免 ∞，跨股可比）
PRESSURE_CAP: float = 999.0


def _sum_vol(levels: list[dict]) -> float:
    """Σ vol，vol 缺失/None/非数字当 0（数据质量门）。"""
    total = 0.0
    for lv in levels:
        if not isinstance(lv, dict):
            continue
        v = lv.get("vol")
        try:
            total += float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            continue
    return total


def compute_ofi(buy_levels: list[dict], sell_levels: list[dict]) -> float:
    """OFI 归一化 ∈ [-1, 1] = (Σbuy - Σsell) / (Σbuy + Σsell)。

    全买压（sell=0）→ 1.0；全卖压（buy=0）→ -1.0；平衡 → 0.0；空/total=0 → 0.0。
    """
    buy_sum = _sum_vol(buy_levels)
    sell_sum = _sum_vol(sell_levels)
    total = buy_sum + sell_sum
    if total <= 0:
        return 0.0
    return (buy_sum - sell_sum) / total


def compute_ofi_abs(buy_levels: list[dict], sell_levels: list[dict]) -> float:
    """OFI 绝对值 = Σbuy - Σsell（跨股不可比但保留量级）。"""
    return _sum_vol(buy_levels) - _sum_vol(sell_levels)


def compute_bid_ask_pressure(buy_levels: list[dict], sell_levels: list[dict]) -> float:
    """盘口买压比 = Σbuy / Σsell（涨停 sell=0 → cap 999.0；both 0 → 0.0；超 cap → cap）。

    涨停时 sell=0 ratio→∞，cap 999.0 避免跨股比较失真；涨停股用 seal_amount 替代（KG 因子 3）。
    """
    buy_sum = _sum_vol(buy_levels)
    sell_sum = _sum_vol(sell_levels)
    if sell_sum <= 0:
        return PRESSURE_CAP if buy_sum > 0 else 0.0
    return min(buy_sum / sell_sum, PRESSURE_CAP)


def compute_multi_level_ofi(
    prev_buy_prices: list[float],
    prev_buy_vols: list[float],
    prev_sell_prices: list[float],
    prev_sell_vols: list[float],
    curr_buy_prices: list[float],
    curr_buy_vols: list[float],
    curr_sell_prices: list[float],
    curr_sell_vols: list[float],
    levels: int = 5,
) -> tuple[list[float], float]:
    """S188 变动量 Multi-Level OFI（Cont, Kukanov, Stoikov 2014 学界标准）。

    与 compute_ofi（瞬时不平衡比）不同——本函数算订单流**变化量**（订单流冲击价格），
    更接近"价格驱动力"本质。五档分别算 delta_v_bid - delta_v_ask（含价格跳档判断），
    防主力的买一档虚假挂单 spoofing（看全五档加权）。

    跳档规则（Cont 原文）：
    - 买盘：curr_p > prev_p → delta_v = curr_v（价位上移，新增挂单）；== → curr_v - prev_v；< → 0
    - 卖盘：curr_p < prev_p → delta_v = curr_v（价位下移）；== → curr_v - prev_v；> → 0
    - OFI_Li = delta_v_bid - delta_v_ask

    返 (per_level_ofi_list, total_ofi)。total_ofi = Σ OFI_Li（等权；实战可按 1/d 距离加权）。
    入参长度不足 levels 的取 min(可用档数, levels)；空/对齐失败该档 0.0。
    """
    n = min(levels, len(prev_buy_prices) or 0, len(curr_buy_prices) or 0,
            len(prev_buy_vols) or 0, len(curr_buy_vols) or 0,
            len(prev_sell_prices) or 0, len(curr_sell_prices) or 0,
            len(prev_sell_vols) or 0, len(curr_sell_vols) or 0)
    per_level: list[float] = []
    for i in range(n):
        try:
            pbp, pbv = float(prev_buy_prices[i]), float(prev_buy_vols[i])
            cbp, cbv = float(curr_buy_prices[i]), float(curr_buy_vols[i])
            pap, pav = float(prev_sell_prices[i]), float(prev_sell_vols[i])
            cap_, cav = float(curr_sell_prices[i]), float(curr_sell_vols[i])
        except (TypeError, ValueError, IndexError):
            per_level.append(0.0)
            continue
        # 买盘变动量
        if cbp > pbp:
            delta_bid = cbv
        elif cbp == pbp:
            delta_bid = cbv - pbv
        else:
            delta_bid = 0.0
        # 卖盘变动量
        if cap_ < pap:
            delta_ask = cav
        elif cap_ == pap:
            delta_ask = cav - pav
        else:
            delta_ask = 0.0
        per_level.append(delta_bid - delta_ask)
    # 补齐到 levels 长度（不足档 0.0）
    while len(per_level) < levels:
        per_level.append(0.0)
    total = sum(per_level)
    return per_level, total


def ofi_turn_points(ofi_series: list[float]) -> dict[str, list[int]]:
    """S189 · OFI 序列拐点检测（T+0 触发用）。

    正转负 = 卖点 idx（买压消退），负转正 = 买点 idx（买压回升）。
    返 {"sell_points": [idx...], "buy_points": [idx...]}。
    零值视为正（≥0），避免噪声抖动。空/单元素返 {[], []}。
    """
    if len(ofi_series) < 2:
        return {"sell_points": [], "buy_points": []}
    sell_points: list[int] = []
    buy_points: list[int] = []
    for i in range(1, len(ofi_series)):
        prev, curr = ofi_series[i - 1], ofi_series[i]
        prev_pos = prev >= 0
        curr_pos = curr >= 0
        if prev_pos and not curr_pos:
            sell_points.append(i)  # 正转负
        elif not prev_pos and curr_pos:
            buy_points.append(i)  # 负转正
    return {"sell_points": sell_points, "buy_points": buy_points}


def is_auction_period(ts: str) -> bool:
    """集合竞价时段剔除（09:15-09:25 / 14:57-15:00）——撮合机制不同，OFI 公式不适用。

    ts 格式 'HH:MM' 或 'HH:MM:SS'。集合竞价 + 收盘集合竞价都剔。
    """
    try:
        hhmm = ts.replace(":", "")[:4]
        return ("0915" <= hhmm < "0925") or ("1457" <= hhmm <= "1500")
    except Exception:
        return False


__all__ = [
    "compute_ofi", "compute_ofi_abs", "compute_bid_ask_pressure", "PRESSURE_CAP",
    "compute_multi_level_ofi", "is_auction_period", "ofi_turn_points",
]
