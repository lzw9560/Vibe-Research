# -*- coding: utf-8 -*-
"""engine 共享 bar 工具——_bar_get + board-aware is_unbuyable_next_bar。

自包含（engine 不 import strategies.kline_returns，避免循环依赖）。
kline_returns._is_unbuyable_next_bar / _bar_get 薄委托至此（backward compat）。
"""
from __future__ import annotations

from typing import Any

#: 一字板四价相等容差（float 噪声；覆盖 ¥5-50 涨停股，高价股更宽松不误判）。
UNBUYABLE_PRICE_TOL: float = 0.01

#: 主板涨停判定阈值（10% - 0.2% 容差 = 9.8%，匹配 kline_returns 原口径）。
MAIN_BOARD_LIMIT_PCT: float = 10.0
LIMIT_TOLERANCE: float = 0.2  # 涨停幅度容差（百分点，覆盖 float 噪声 + 盘口微动）


def _bar_get(bar: object, key: str, default: Any = 0.0) -> Any:
    """统一取 bar 字段（dict 或 SimpleNamespace——strategy_backtest 用 NS，kline_returns 用 dict）。

    与 kline_returns._bar_get 同签名同行为，engine 自有副本避免循环依赖。
    """
    if isinstance(bar, dict):
        v = bar.get(key, default)
        return v if v is not None else default
    return getattr(bar, key, default)


def _limit_pct_for_code(code: str) -> float:
    """A 股涨跌停幅度（基于代码判断板块）。

    主板 ±10% / ST ±5% / 创业板(300/301) ±20% / 科创板(688/689) ±20% / 北交所(8/43/87) ±30%。
    未知代码 → 主板 10%（保守）。
    """
    if not code or len(code) != 6:
        return MAIN_BOARD_LIMIT_PCT
    if code.startswith("300") or code.startswith("301"):
        return 20.0  # 创业板
    if code.startswith("688") or code.startswith("689"):
        return 20.0  # 科创板
    if code.startswith("8") or code.startswith("43") or code.startswith("87"):
        return 30.0  # 北交所
    return MAIN_BOARD_LIMIT_PCT


def is_unbuyable_next_bar(nb: object, code: str = "") -> bool:
    """检测 next_bar（T+1）是否一字板涨停封死（不可买）——board-aware 版。

    四价相等（high≈low≈open≈close）+ pctChg≥涨停阈值 → 一字板涨停 → 不可买。
    正常上涨/有区间/跌停均返 False（可买）。跌停一字板对做多可买（有人抛、买家成交）。

    code="" → 主板 10% → 阈值 9.8%（匹配 kline_returns 原口径，backward compat）。
    code="300xxx" → 创业板 20% → 阈值 19.8%。ST 股（bar.isST）→ 5% → 阈值 4.8%。

    用 _bar_get 统一 dict/SimpleNamespace（原 kline_returns 版只支持 dict .get，此处超集）。
    """
    nb_open = _bar_get(nb, "open", 0.0)
    nb_high = _bar_get(nb, "high", 0.0)
    nb_low = _bar_get(nb, "low", 0.0)
    nb_close = _bar_get(nb, "close", 0.0)
    nb_pct = _bar_get(nb, "pctChg", 0.0)
    # board-specific limit（ST 检测：baostock isST 字段，1=ST）
    is_st = _bar_get(nb, "isST", 0)
    limit_pct = 5.0 if is_st else _limit_pct_for_code(code)
    threshold = limit_pct - LIMIT_TOLERANCE
    try:
        pct_f = float(nb_pct)
    except (TypeError, ValueError):
        pct_f = 0.0
    return (
        abs(float(nb_high) - float(nb_low)) <= UNBUYABLE_PRICE_TOL
        and abs(float(nb_open) - float(nb_close)) <= UNBUYABLE_PRICE_TOL
        and pct_f >= threshold  # 涨停方向（非 abs：跌停一字板对做多可买）
    )


def is_halted(bar: object) -> bool:
    """检测 bar 是否停牌（volume/amount 字段存在且 ==0）。

    仅当 bar 显式带 volume 或 amount 字段且值为 0 时判定停牌——
    test bar（SimpleNamespace 无 volume）不会误判（_bar_get 返 None → 跳过）。
    """
    vol = _bar_get(bar, "volume", None)
    if vol is not None:
        try:
            return float(vol) == 0
        except (TypeError, ValueError):
            return False
    amt = _bar_get(bar, "amount", None)
    if amt is not None:
        try:
            return float(amt) == 0
        except (TypeError, ValueError):
            return False
    return False
