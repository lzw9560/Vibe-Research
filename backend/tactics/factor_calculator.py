# -*- coding: utf-8 -*-
"""factor_calculator —— 反量化战法因子计算 + 归一化（S235 T02）。

纯函数模块，无外部依赖。所有 calc_* 接受 dict 快照返回数值；
normalize_factor 把异纲量原始值映射到 0-1，使加权评分数学有效。

⚠️ 字段名 provisional：竞价/快照字段口径待 Phase B T14 实测 CLI 确认。
   当前命名与 tests/fixtures/*.json 内部一致，Phase B 接 live 时若有偏差在此调整。
"""

from __future__ import annotations
from typing import Any

# ---------------------------------------------------------------------------
# 原始因子计算（calc_*）—— 输入 dict 快照，返回数值
# ---------------------------------------------------------------------------


def calc_vwap(snapshot: dict) -> float:
    """VWAP 近似 = (open + high + low + 2*close) / 5。

    真实 VWAP 需分笔成交，盘中不可得；用加权典型价格近似（收盘权重 2x）。
    全高价/全低价边界：所有 OHLC 相同时退化为该价（/5 权重和=5 一致）。

    注：plan.md 草案原写 /4（权重和 5 ÷ 除数 4 不一致，全相等时=1.25×price），
    2026-10-07 用户拍板改 /5（标准加权均价，全相等时=price 自身）。
    """
    o = float(snapshot.get("open_price", 0) or 0)
    h = float(snapshot.get("high_price", 0) or 0)
    lo = float(snapshot.get("low_price", 0) or 0)
    c = float(snapshot.get("close_price", 0) or 0)
    return (o + h + lo + 2 * c) / 5


def calc_turnover_rate(snapshot: dict, float_mv: float | None = None) -> float:
    """换手率 = 成交额 / 流通市值。

    流通市值优先用传入参数；否则从 snapshot.float_mv 取；都无返回 0.0。
    单位：成交额（元）/ 流通市值（元）→ 无量纲比率（0.12 表示 12%）。
    """
    amount = float(snapshot.get("amount", 0) or 0)
    mv = float_mv if float_mv is not None else float(snapshot.get("float_mv", 0) or 0)
    if mv <= 0:
        return 0.0
    return amount / mv


def calc_vol_ratio(auction_data: dict, prev_5d_open_volumes: list[float]) -> float:
    """竞价量比 = 竞价成交量 / 过去 5 日开盘均量。

    prev_5d_open_volumes 为空或均量=0 → 返回 0.0（不可计算，归一化后为 0）。
    """
    vol = float(auction_data.get("volume", 0) or 0)
    if not prev_5d_open_volumes:
        return 0.0
    mean_prev = sum(prev_5d_open_volumes) / len(prev_5d_open_volumes)
    if mean_prev <= 0:
        return 0.0
    return vol / mean_prev


def calc_amount_ratio(auction_data: dict, prev_day_turnover: float) -> float:
    """竞价额占比 = 竞价成交额 / 前日全天成交额。

    prev_day_turnover<=0 → 0.0。返回比率（0.10 表示占 10%）。
    """
    amt = float(auction_data.get("amount", 0) or 0)
    if prev_day_turnover <= 0:
        return 0.0
    return amt / prev_day_turnover


def calc_close_position(snapshot: dict) -> float:
    """收盘位置比 = (close - low) / (high - low)。

    high==low（一字板）→ 返回 1.0（封死在极值，按强势处理）。
    """
    c = float(snapshot.get("close_price", 0) or 0)
    lo = float(snapshot.get("low_price", 0) or 0)
    h = float(snapshot.get("high_price", 0) or 0)
    if h - lo == 0:
        return 1.0
    return (c - lo) / (h - lo)


def calc_prev_drop(prev_klines: list[dict]) -> float:
    """前日跌幅 = (前日 close - 前日 prev_close) / 前日 prev_close。

    prev_klines 至少 2 根：[-2]为前日 prev_close，[-1]为前日。
    返回百分比小数（-0.05 表示跌 5%）。不足 2 根 → 0.0。
    """
    if len(prev_klines) < 2:
        return 0.0
    prev_close = float(prev_klines[-2].get("close_price", 0) or 0)
    last_close = float(prev_klines[-1].get("close_price", 0) or 0)
    if prev_close <= 0:
        return 0.0
    return (last_close - prev_close) / prev_close


# ---------------------------------------------------------------------------
# 归一化（normalize_factor）—— 每因子独立逻辑，输出 0-1
# 硬条件类（prev_drop/above_vwap/ice_point）作 gate：满足 1.0 不满足 0.0
# ---------------------------------------------------------------------------

# 换手率归一化区间边界（spec §2.2：12-22% 为尾盘突破甜区）
_TURNOVER_LO, _TURNOVER_HI = 0.12, 0.22
_TURNOVER_FLOOR, _TURNOVER_CEIL = 0.06, 0.30  # 区间外线性衰减到 0 的边界

# close_position 归一化锚点（0.7 → 1.0，T10 验收）
_CLOSE_POS_FULL = 0.7

# gap_pct 甜区与衰减边界（T10：2→1.0, 5→1.0, 1→0, 6→0）
_GAP_LO, _GAP_HI = 2.0, 5.0
_GAP_FLOOR, _GAP_CEIL = 1.0, 6.0

# 量比/额占比 满分锚点（spec §2.2：4.5 / 10%）
_VOL_RATIO_FULL = 4.5
_AMOUNT_RATIO_FULL = 0.10


def _norm_plateau(v: float, lo: float, hi: float, floor: float, ceil: float) -> float:
    """区间 [lo,hi] 内 1.0，向 floor/ceil 线性衰减到 0，超出截断 0。"""
    if lo <= v <= hi:
        return 1.0
    if v < lo:
        if lo == floor:
            return 0.0
        return max(0.0, (v - floor) / (lo - floor))
    # v > hi
    if hi == ceil:
        return 0.0
    return max(0.0, (ceil - v) / (ceil - hi))


def _norm_linear_to_anchor(v: float, anchor: float) -> float:
    """min(1.0, v/anchor)：到 anchor 满分，超过截断 1.0，负值 0。"""
    if anchor <= 0:
        return 0.0
    if v <= 0:
        return 0.0
    return min(1.0, v / anchor)


def normalize_factor(name: str, value: Any) -> float:
    """因子归一化分发表 —— 每因子独立逻辑，输出 0.0-1.0。

    未知因子名 → 0.0（保守，避免评分膨胀）。
    None/NaN → 0.0。
    """
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if name == "prev_drop":
        # 硬条件 gate：跌>5% 才 1.0（注意 v 是负数，<=-0.05）
        return 1.0 if v <= -0.05 else 0.0
    if name == "above_vwap":
        return 1.0 if bool(v) else 0.0
    if name == "ice_point":
        return 1.0 if bool(v) else 0.0
    if name == "bid_increasing":
        return 1.0 if bool(v) else 0.0
    if name == "break_vwap":
        return 1.0 if bool(v) else 0.0
    if name == "gap_pct":
        # v 是百分点数（2 表示 2%），用 _GAP 边界
        return _norm_plateau(v, _GAP_LO, _GAP_HI, _GAP_FLOOR, _GAP_CEIL)
    if name == "vol_ratio":
        return _norm_linear_to_anchor(v, _VOL_RATIO_FULL)
    if name == "amount_ratio":
        return _norm_linear_to_anchor(v, _AMOUNT_RATIO_FULL)
    if name == "turnover_rate":
        return _norm_plateau(v, _TURNOVER_LO, _TURNOVER_HI, _TURNOVER_FLOOR, _TURNOVER_CEIL)
    if name == "close_position":
        return _norm_linear_to_anchor(v, _CLOSE_POS_FULL)
    if name == "breakout_high":
        # 突破日内高点：>=99.5% 满分，否则用比值
        return 1.0 if v >= 0.995 else max(0.0, v)
    if name == "sector_resonance":
        # 板块涨停数：>=2 满分
        return _norm_linear_to_anchor(v, 2.0)
    if name == "anti_drop":
        # 抗跌：相对市场的正超额，>=阈值满分；负值（比市场跌更多）0
        return _norm_linear_to_anchor(v, 1.0)
    if name == "big_order_proxy":
        # 降级因子：proxy 本身在 0-1，直接截断
        return max(0.0, min(1.0, v))
    if name == "bottom_divergence":
        # 降级因子：proxy 0-1
        return max(0.0, min(1.0, v))
    # 未知因子：保守 0.0
    return 0.0
