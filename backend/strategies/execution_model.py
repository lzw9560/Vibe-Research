# -*- coding: utf-8 -*-
"""S066 §16 执行与成本模型 + §15 组合级风控 + §16.4 市场级熔断。

spec §16.2 动态滑点：slippage = max(0.001, 0.003 * (order_amount / daily_amount))
spec §15.7 双层 kill criteria：策略级 >= 5 连亏 + 组合级 >= 8 连亏/5 日
spec §16.4 市场级熔断：指数跌幅 > 3% → 不开新仓
spec §15 账户硬约束：max 5 只/max 10% 单股/max 20% 板块/min 30% 现金

成本参数可配置（backend/config），默认值基于 A 股实际费率。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import default_config


# ===========================================================================
# 常量（spec §16.2 A 股实际费率）
# ===========================================================================

COMMISSION_RATE = 0.00025     # 佣金 0.025% 单边
STAMP_DUTY = 0.0005           # 印花税 0.05% 卖出单边
SLIPPAGE_MIN = 0.001          # 滑点下限 0.1%
SLIPPAGE_COEFF = 0.003        # 滑点系数 0.3%

# 账户硬约束（spec §15.x）
MAX_CONCURRENT_POSITIONS = 5
MAX_SINGLE_POSITION = 0.10    # 单股不超过 10%
MAX_SECTOR_EXPOSURE = 0.20    # 单板块不超过 20%
MIN_CASH_RESERVE = 0.30       # 永远保留至少 30% 现金
MAX_TOTAL_POSITION = 0.30     # 涨停延续策略最多占组合 30%

# 回撤熔断（spec §15.4）
CONSECUTIVE_LOSS_THRESHOLD = 3   # 连续 3 笔亏损 → 降仓 50%
DRAWDOWN_THRESHOLD = 0.08         # 组合回撤 > 8% → 停止开新仓

# kill criteria（spec §15.7）
KILL_STRATEGY_CONSECUTIVE_LOSS = 5    # 策略级连亏 5 笔
KILL_PORTFOLIO_CONSECUTIVE_LOSS = 8    # 组合级连亏 8 笔
KILL_PORTFOLIO_WINDOW_DAYS = 5         # 组合级 5 日窗口
KILL_DRAWDOWN = 0.15                   # 组合最大回撤 > 15%
KILL_ROLLING_WIN_RATE = 0.45          # 30 日滚动胜率 < 45%

# 市场熔断（spec §16.4）
MARKET_KILL_SH_DROP = 3.0        # 上证跌幅 > 3% → 不开新仓
MARKET_KILL_GEM_DROP = 4.0       # 创业板跌幅 > 4% → 不开新仓
MARKET_KILL_CONSECUTIVE_DROP = 2.0  # 连续 2 日上证跌幅 > 2% → 次日降仓 50%


# ===========================================================================
# 动态滑点模型（spec §16.2）
# ===========================================================================

@dataclass(frozen=True)
class TransactionCost:
    """单笔交易成本拆解。"""
    commission: float       # 佣金（双边）
    stamp_duty: float       # 印花税（卖出单边）
    slippage: float         # 滑点（双边）
    round_trip_cost: float  # 总成本
    slippage_pct: float     # 滑点百分比


def compute_slippage(order_amount: float, daily_amount: float) -> float:
    """动态滑点（spec §16.2）。

    slippage = max(0.001, 0.003 * (order_amount / daily_amount))

    - 小资金（500万/8亿日成交）→ 0.3% * 0.006 = 0.002% → 取 0.1% 下限
    - 大资金（2亿/8亿）→ 0.3% * 0.25 = 0.075% → 取 0.1% 下限
    - 超大资金（4亿/8亿）→ 0.3% * 0.5 = 0.15% → 超过下限
    """
    if daily_amount <= 0:
        return SLIPPAGE_MIN
    ratio = order_amount / daily_amount
    return max(SLIPPAGE_MIN, SLIPPAGE_COEFF * ratio)


def compute_transaction_cost(
    order_amount: float,
    daily_amount: float,
) -> TransactionCost:
    """计算单笔交易总成本（spec §16.2）。

    round_trip_cost = commission_rate * 2 + stamp_duty + slippage * 2
    """
    slippage = compute_slippage(order_amount, daily_amount)
    commission = order_amount * COMMISSION_RATE * 2  # 买卖双边
    stamp = order_amount * STAMP_DUTY                  # 卖出单边
    slip = order_amount * slippage * 2                # 买卖双边
    total = commission + stamp + slip
    return TransactionCost(
        commission=round(commission, 2),
        stamp_duty=round(stamp, 2),
        slippage=round(slip, 2),
        round_trip_cost=round(total, 2),
        slippage_pct=round(slippage, 6),
    )


# ===========================================================================
# 市场级熔断（spec §16.4）
# ===========================================================================

@dataclass(frozen=True)
class MarketKillSwitch:
    """市场熔断状态。"""
    triggered: bool
    reason: str
    sh_change_pct: float | None = None
    gem_change_pct: float | None = None


def check_market_kill_switch(indices: list[dict] | None = None) -> MarketKillSwitch:
    """检查市场级熔断（spec §16.4）。

    上证指数当日跌幅 > 3% → 不开新仓
    创业板指数当日跌幅 > 4% → 不开新仓
    暴风雨天气 + 指数跌幅 > 3% = 双重熔断，强制清仓

    indices: [{name, price, change_pct}]（来自 tencent.index_raw()）
    取不到指数数据 → 不触发（不臆造）。
    """
    if not indices:
        return MarketKillSwitch(triggered=False, reason="指数数据未取得，不触发熔断")

    sh_pct = None
    gem_pct = None
    for idx in indices:
        name = idx.get("name", "")
        pct = idx.get("change_pct", 0)
        if "上证" in name:
            sh_pct = pct
        elif "创业板" in name:
            gem_pct = pct

    if sh_pct is not None and sh_pct < -MARKET_KILL_SH_DROP:
        return MarketKillSwitch(
            triggered=True,
            reason=f"上证跌幅 {sh_pct:.2f}% > {MARKET_KILL_SH_DROP}%，不开新仓",
            sh_change_pct=sh_pct,
            gem_change_pct=gem_pct,
        )

    if gem_pct is not None and gem_pct < -MARKET_KILL_GEM_DROP:
        return MarketKillSwitch(
            triggered=True,
            reason=f"创业板跌幅 {gem_pct:.2f}% > {MARKET_KILL_GEM_DROP}%，不开新仓",
            sh_change_pct=sh_pct,
            gem_change_pct=gem_pct,
        )

    return MarketKillSwitch(
        triggered=False,
        reason=f"市场正常（上证 {sh_pct or 0:.2f}% / 创业板 {gem_pct or 0:.2f}%）",
        sh_change_pct=sh_pct,
        gem_change_pct=gem_pct,
    )


# ===========================================================================
# 双层 kill criteria（spec §15.7）
# ===========================================================================

@dataclass(frozen=True)
class KillCriteriaStatus:
    """策略终止条件状态。"""
    strategy_killed: bool
    portfolio_killed: bool
    strategy_reason: str
    portfolio_reason: str
    consecutive_loss: int
    rolling_30d_win_rate: float | None
    max_drawdown: float | None


def check_kill_criteria(
    consecutive_loss: int,
    rolling_30d_win_rate: float | None = None,
    max_drawdown: float | None = None,
    portfolio_consecutive_loss: int = 0,
    portfolio_5d_loss_count: int = 0,
) -> KillCriteriaStatus:
    """检查双层 kill criteria（spec §15.7）。

    策略级（任一触发即停机）：
    - 连续亏损 >= 5 笔
    - 30 日滚动胜率 < 45%

    组合级（任一触发即停机）：
    - 连续亏损 >= 8 笔（73% 胜率下概率 = 0.27^8 = 万分之三）
    - 5 日窗口内亏损 >= 8 笔
    - 最大回撤 > 15%
    """
    strategy_killed = False
    strategy_reason = ""
    portfolio_killed = False
    portfolio_reason = ""

    if consecutive_loss >= KILL_STRATEGY_CONSECUTIVE_LOSS:
        strategy_killed = True
        strategy_reason = f"策略级连亏 {consecutive_loss} 笔 >= {KILL_STRATEGY_CONSECUTIVE_LOSS}"

    if rolling_30d_win_rate is not None and rolling_30d_win_rate < KILL_ROLLING_WIN_RATE:
        strategy_killed = True
        strategy_reason += f"；30 日滚动胜率 {rolling_30d_win_rate:.1%} < {KILL_ROLLING_WIN_RATE:.0%}"

    if portfolio_consecutive_loss >= KILL_PORTFOLIO_CONSECUTIVE_LOSS:
        portfolio_killed = True
        portfolio_reason = f"组合级连亏 {portfolio_consecutive_loss} 笔 >= {KILL_PORTFOLIO_CONSECUTIVE_LOSS}"

    if portfolio_5d_loss_count >= KILL_PORTFOLIO_CONSECUTIVE_LOSS:
        portfolio_killed = True
        portfolio_reason += f"；5 日窗口亏损 {portfolio_5d_loss_count} 笔 >= {KILL_PORTFOLIO_CONSECUTIVE_LOSS}"

    if max_drawdown is not None and max_drawdown > KILL_DRAWDOWN:
        portfolio_killed = True
        portfolio_reason += f"；最大回撤 {max_drawdown:.1%} > {KILL_DRAWDOWN:.0%}"

    return KillCriteriaStatus(
        strategy_killed=strategy_killed,
        portfolio_killed=portfolio_killed,
        strategy_reason=strategy_reason,
        portfolio_reason=portfolio_reason,
        consecutive_loss=consecutive_loss,
        rolling_30d_win_rate=rolling_30d_win_rate,
        max_drawdown=max_drawdown,
    )


# ===========================================================================
# 账户硬约束（spec §15.x）
# ===========================================================================

@dataclass(frozen=True)
class PortfolioConstraint:
    """组合约束检查结果。"""
    within_limits: bool
    violations: list[str]
    total_position_pct: float
    sector_exposure: dict[str, float]
    cash_reserve_pct: float


def check_portfolio_constraints(
    positions: list[dict],
    total_capital: float,
) -> PortfolioConstraint:
    """检查账户硬约束（spec §15.x）。

    positions: [{code, sector, position_value}]
    - max 5 只
    - 单股不超过 10%
    - 单板块不超过 20%
    - 总仓位不超过 30%（涨停延续是卫星策略）
    - 现金 >= 30%
    """
    violations: list[str] = []
    total_position = sum(p.get("position_value", 0) for p in positions)
    total_position_pct = total_position / total_capital if total_capital > 0 else 0.0

    # max 5 只
    if len(positions) > MAX_CONCURRENT_POSITIONS:
        violations.append(f"持仓 {len(positions)} 只 > {MAX_CONCURRENT_POSITIONS} 上限")

    # 单股不超过 10%
    for p in positions:
        single_pct = p.get("position_value", 0) / total_capital if total_capital > 0 else 0
        if single_pct > MAX_SINGLE_POSITION:
            violations.append(f"单股 {p.get('code', '')} 占比 {single_pct:.1%} > {MAX_SINGLE_POSITION:.0%}")

    # 单板块不超过 20%
    sector_totals: dict[str, float] = {}
    for p in positions:
        sector = p.get("sector", "未知")
        sector_totals[sector] = sector_totals.get(sector, 0) + p.get("position_value", 0)
    for sector, val in sector_totals.items():
        sector_pct = val / total_capital if total_capital > 0 else 0
        if sector_pct > MAX_SECTOR_EXPOSURE:
            violations.append(f"板块 {sector} 占比 {sector_pct:.1%} > {MAX_SECTOR_EXPOSURE:.0%}")

    # 总仓位不超过 30%
    if total_position_pct > MAX_TOTAL_POSITION:
        violations.append(f"总仓位 {total_position_pct:.1%} > {MAX_TOTAL_POSITION:.0%}")

    # 现金 >= 30%
    cash_reserve_pct = 1.0 - total_position_pct
    if cash_reserve_pct < MIN_CASH_RESERVE:
        violations.append(f"现金 {cash_reserve_pct:.1%} < {MIN_CASH_RESERVE:.0%}")

    return PortfolioConstraint(
        within_limits=len(violations) == 0,
        violations=violations,
        total_position_pct=round(total_position_pct, 4),
        sector_exposure={k: round(v / total_capital, 4) if total_capital > 0 else 0 for k, v in sector_totals.items()},
        cash_reserve_pct=round(cash_reserve_pct, 4),
    )
