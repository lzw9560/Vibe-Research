# -*- coding: utf-8 -*-
"""S203 T7 模板：吃大面熔断 enforce（Vibe 侧可做，复用 T6 intraday_loss_breaker）。

单笔>5% 禁加仓 / 合计>8% 禁开新仓 + 冷却。复用 backend/risk/intraday_loss_breaker.py
（T6 已 built+green）的 evaluate_loss_breaker + intraday_multiplier + compute_final_size。

四层乘积 final_size = arm_size × portfolio_mult × lift_mult × intraday_mult：
- intraday_mult 由 T6 算（单笔>5% → 0.0 禁该 code 加仓；合计>8% → 0.0 禁全账户新仓）
- 本模板组装：读持仓浮亏 → 调 T6.evaluate_loss_breaker → 算 intraday_mult → compute_final_size

依赖（Vibe 侧可做）：
- backend/risk/intraday_loss_breaker（T6，已 built）
- 持仓浮亏数据（realized_loss_pct / total_account_loss_pct，从 trade_journal 或持仓表读）
"""
from __future__ import annotations

from typing import Optional

# 复用 T6 intraday_loss_breaker（已 built+green）
from risk.intraday_loss_breaker import (
    LossBreakerState,
    evaluate_loss_breaker,
    intraday_multiplier,
    compute_final_size,
)


def enforce_loss_breaker(
    code: str,
    date: str,
    realized_loss_pct: float,
    total_account_loss_pct: float,
    arm_size: float,
    portfolio_mult: float = 1.0,
    lift_mult: float = 1.0,
    cooldown_until: Optional[str] = None,
) -> tuple[LossBreakerState, float]:
    """吃大面熔断 enforce（Vibe 侧可做，复用 T6）。

    Args:
        code: 股票代码。
        date: 交易日。
        realized_loss_pct: 该 code 单笔浮亏 %（负数，如 -6.0 表示亏 6%）。
        total_account_loss_pct: 全账户合计浮亏 %（负数，如 -9.0 表示亏 9%）。
        arm_size: 该 arm 基础仓位（股数）。
        portfolio_mult: 组合乘数（默认 1.0）。
        lift_mult: §44 lift 乘数（默认 1.0）。
        cooldown_until: 现有冷却到期日（None 无冷却）。

    Returns:
        (LossBreakerState, final_size)：熔断状态 + 四层乘积最终仓位（0.0 禁交易）。

    单笔>5% → is_blocked_add=True → intraday_mult=0.0 → final_size=0（禁该 code 加仓）。
    合计>8% → is_blocked_new=True → intraday_mult=0.0 → final_size=0（禁全账户新仓）。
    """
    state = evaluate_loss_breaker(
        code=code,
        date=date,
        realized_loss_pct=realized_loss_pct,
        total_account_loss_pct=total_account_loss_pct,
        cooldown_until=cooldown_until,
    )
    intraday_mult = intraday_multiplier(state)
    final_size = compute_final_size(
        arm_size=arm_size,
        portfolio_mult=portfolio_mult,
        lift_mult=lift_mult,
        intraday_mult=intraday_mult,
    )
    return state, final_size
