# -*- coding: utf-8 -*-
"""S203 T7 QMT 模板：触涨停排队买入触发器。

[BLOCKER: 需 xtquant + L2 实时盘口]
Vibe-Research 无 xtquant 接入 + 无 L2 实时盘口数据，本模板为参考骨架，不进生产。
QMT 实盘接入时按此骨架实现：监控价格触涨停 + 封成比>阈值 → 排队买入。

逻辑：
1. 监控目标股价格是否触涨停（接近涨停价 -0.5% 内）
2. 触涨停后取封单量+成交额算封成比 = seal_amount / amount
3. 封成比>阈值（如 5%）→ 排队挂单买入（涨停价排队）
4. 封单撤/炸板 → 撤单

依赖（BLOCKER）：
- xtquant：QMT 交易接口（下单/撤单/查持仓）
- L2 实时盘口：封单量实时变化（L1 慢 + 不全）
- 涨停价计算：前一交易日 close × (1 + limit_pct)
"""
from __future__ import annotations

from dataclasses import dataclass


#: 触涨停阈值（接近涨停价 -0.5% 内判定"触涨停"）
NEAR_LIMIT_PCT: float = 0.5
#: 封成比阈值（>5% 排队买入，封单足够厚）
SEAL_RATIO_THRESHOLD: float = 0.05


@dataclass(frozen=True)
class BoardHitSignal:
    """触涨停信号（不可变）。"""

    code: str
    trade_date: str
    last_price: float
    limit_price: float
    seal_amount: float  # 封单量（元）
    amount: float  # 成交额（元）
    seal_ratio: float  # 封成比 = seal_amount / amount
    should_buy: bool  # 触涨停 + 封成比>阈值


def compute_limit_price(prev_close: float, limit_pct: float) -> float:
    """涨停价 = 前收 × (1 + limit_pct)（纯函数）。"""
    return round(prev_close * (1 + limit_pct), 2)


def compute_seal_ratio(seal_amount: float, amount: float) -> float:
    """封成比 = seal_amount / amount（纯函数，amount=0 返 0.0 不报错）。"""
    if amount <= 0:
        return 0.0
    return seal_amount / amount


def evaluate_board_hit(
    code: str,
    trade_date: str,
    last_price: float,
    limit_price: float,
    seal_amount: float,
    amount: float,
) -> BoardHitSignal:
    """评估触涨停信号（纯函数，不臆造）。

    触涨停 = last_price >= limit_price × (1 - NEAR_LIMIT_PCT/100)
    should_buy = 触涨停 AND 封成比 > SEAL_RATIO_THRESHOLD
    """
    near_limit = last_price >= limit_price * (1 - NEAR_LIMIT_PCT / 100)
    ratio = compute_seal_ratio(seal_amount, amount)
    should_buy = near_limit and ratio > SEAL_RATIO_THRESHOLD
    return BoardHitSignal(
        code=code,
        trade_date=trade_date,
        last_price=last_price,
        limit_price=limit_price,
        seal_amount=seal_amount,
        amount=amount,
        seal_ratio=ratio,
        should_buy=should_buy,
    )


def trigger_buy_order(signal: BoardHitSignal) -> str:
    """排队挂单买入（BLOCKER: 需 xtquant + L2 实时盘口接入）。

    实盘接入时实现：
    - xtquant.connect() 登录 QMT
    - xtquant.order(code, price=limit_price, volume=...) 排队涨停价
    - 返 order_id
    """
    raise NotImplementedError("BLOCKER: 需 xtquant + L2 实时盘口接入（Vibe 侧不可实现）")
