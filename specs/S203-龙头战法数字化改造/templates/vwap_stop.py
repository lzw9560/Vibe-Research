# -*- coding: utf-8 -*-
"""S203 T7 QMT 模板：实时 VWAP 跌破卖出。

[BLOCKER: 需 mootdx tick 实时分笔]
Vibe-Research 无 mootdx tick 实时分笔接入，本模板为参考骨架，不进生产。
QMT 实盘接入时按此骨架实现：实时算 VWAP + 价格跌破 VWAP → 卖出。

逻辑：
1. 实时累计 VWAP = Σ(price × volume) / Σ(volume)（日内逐笔）
2. 价格跌破 VWAP（如 < VWAP × 0.998）→ 触发卖出
3. 卖出下单（市价或限价 VWAP-0.1%）

依赖（BLOCKER）：
- mootdx tick 实时分笔：逐笔价格+量（日 K 线 OHLCV 算 VWAP 是 look-ahead，不可用）
- xtquant：下单接口

⚠️ 用日 K 线 OHLCV 算 VWAP 是 look-ahead（当日 close 已知才算）——必须 tick 实时。
"""
from __future__ import annotations

from dataclasses import dataclass


#: 跌破 VWAP 阈值（价格 < VWAP × 0.998 触发卖出）
BREAK_BELOW_PCT: float = 0.998


@dataclass(frozen=True)
class VwapBreakSignal:
    """VWAP 跌破信号（不可变）。"""

    code: str
    trade_date: str
    vwap: float
    last_price: float
    should_sell: bool  # 价格 < VWAP × BREAK_BELOW_PCT


def compute_vwap(price_volume_pairs: list[tuple[float, float]]) -> float:
    """实时 VWAP = Σ(price × volume) / Σ(volume)（纯函数）。

    Args:
        price_volume_pairs: 日内逐笔 (price, volume) 列表（tick 实时累计）。

    返回 0.0 若无成交（不报错）。

    ⚠️ 必须用 tick 实时分笔，日 K 线 OHLCV 算 VWAP 是 look-ahead。
    """
    total_value = sum(p * v for p, v in price_volume_pairs)
    total_volume = sum(v for _, v in price_volume_pairs)
    if total_volume <= 0:
        return 0.0
    return total_value / total_volume


def evaluate_vwap_break(
    code: str,
    trade_date: str,
    vwap: float,
    last_price: float,
) -> VwapBreakSignal:
    """评估 VWAP 跌破信号（纯函数，不臆造）。

    should_sell = last_price < vwap × BREAK_BELOW_PCT
    """
    should_sell = vwap > 0 and last_price < vwap * BREAK_BELOW_PCT
    return VwapBreakSignal(
        code=code,
        trade_date=trade_date,
        vwap=vwap,
        last_price=last_price,
        should_sell=should_sell,
    )


def trigger_sell_order(signal: VwapBreakSignal) -> str:
    """卖出下单（BLOCKER: 需 mootdx tick + xtquant 接入）。

    实盘接入时实现：
    - mootdx tick 实时取逐笔 (price, volume) 喂 compute_vwap
    - xtquant.order(code, side='sell', ...) 下单
    """
    raise NotImplementedError("BLOCKER: 需 mootdx tick 实时 + xtquant 接入（Vibe 侧不可实现）")
