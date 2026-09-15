# -*- coding: utf-8 -*-
"""S203 T7: intraday_loss_breaker——吃大面 enforce（单笔>5%禁加仓/合计>8%禁开新仓+冷却）。

风控 gate，不依赖 baostock/S204（基于持仓浮亏）。从 risk_rules.py 诊断（report violations）
升级 enforce（block new positions + cooldown）。复用 DrawdownBreaker pattern
（engine/drawdown_breaker.py:77 status enforced/disabled）。

四层乘积 final_size = arm_size × portfolio_mult × lift_mult × intraday_mult（intraday_mult
由本模块算：单笔>5% → 该 code intraday_mult=0 禁加仓；合计>8% → 全账户 intraday_mult=0 禁新仓）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LossBreakerState:
    """单日吃大面熔断状态（不可变）。"""

    code: str
    date: str
    realized_loss_pct: float  # 单笔浮亏 %（负数）
    total_account_loss_pct: float  # 全账户合计浮亏 %（负数）
    is_blocked_add: bool  # 该 code 当日禁加仓（单笔>5%）
    is_blocked_new: bool  # 全账户禁开新仓+冷却（合计>8%）
    cooldown_until: Optional[str]  # 冷却到期日（None 无冷却）


#: 单笔浮亏阈值（>5% 禁该 code 加仓）
SINGLE_LOSS_BLOCK_PCT: float = 5.0
#: 全账户合计阈值（>8% 禁开新仓+冷却）
TOTAL_ACCOUNT_BLOCK_PCT: float = 8.0


def evaluate_loss_breaker(
    code: str,
    date: str,
    realized_loss_pct: float,
    total_account_loss_pct: float,
    cooldown_until: Optional[str] = None,
) -> LossBreakerState:
    """评估吃大面熔断（纯函数，不臆造）。

    Args:
        code: 股票代码。
        date: 交易日。
        realized_loss_pct: 该 code 单笔浮亏 %（负数，如 -6.0 表示亏 6%）。
        total_account_loss_pct: 全账户合计浮亏 %（负数，如 -9.0 表示亏 9%）。
        cooldown_until: 现有冷却到期日（None 无冷却）。

    Returns:
        LossBreakerState（is_blocked_add/is_blocked_new/cooldown）。

    单笔>5% → is_blocked_add=True（该 code 当日禁加仓）。
    合计>8% → is_blocked_new=True（全账户禁开新仓+冷却）。
    """
    is_blocked_add = abs(realized_loss_pct) > SINGLE_LOSS_BLOCK_PCT
    is_blocked_new = abs(total_account_loss_pct) > TOTAL_ACCOUNT_BLOCK_PCT
    return LossBreakerState(
        code=code,
        date=date,
        realized_loss_pct=realized_loss_pct,
        total_account_loss_pct=total_account_loss_pct,
        is_blocked_add=is_blocked_add,
        is_blocked_new=is_blocked_new,
        cooldown_until=cooldown_until,
    )


def intraday_multiplier(state: LossBreakerState) -> float:
    """四层乘积的 intraday_mult（0.0 禁该 code / 0.0 禁全账户 / 1.0 放行）。

    - is_blocked_new（合计>8%）→ 0.0（全账户禁开新仓，intraday_mult=0）
    - is_blocked_add（单笔>5%）→ 0.0（该 code 禁加仓）
    - 否则 → 1.0（放行）
    """
    if state.is_blocked_new:
        return 0.0  # 全账户熔断（优先级最高）
    if state.is_blocked_add:
        return 0.0  # 该 code 禁加仓
    return 1.0


def compute_final_size(
    arm_size: float,
    portfolio_mult: float,
    lift_mult: float,
    intraday_mult: float,
) -> float:
    """四层乘积 final_size = arm × portfolio × lift × intraday（任一 0 → 0 禁交易）。"""
    return arm_size * portfolio_mult * lift_mult * intraday_mult
