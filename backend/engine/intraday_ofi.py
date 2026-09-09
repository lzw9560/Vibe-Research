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


__all__ = ["compute_ofi", "compute_ofi_abs", "compute_bid_ask_pressure", "PRESSURE_CAP"]
