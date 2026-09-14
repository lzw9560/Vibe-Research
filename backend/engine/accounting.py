# -*- coding: utf-8 -*-
"""S162 R1 Accounting 层——design-agnostic path return + cost + survivorship。

**只算**（spec v2 删边界）：path return + cost + survivorship（unbuyable 过滤）。
**不含** day_paired_lift / walk-forward / Bonferroni / IC（归 S161 verifier；
IC 是 cross-sectional scalar ≠ return series，喂 verify() 是 category error）。

接 **filled Trades + bars**（bars needed for intrabar stop/take triggers at
simulate_holding lines 104-106/114；非"给定 Trades → path return"）。
喂 S161 verifier（raw per-trade return series → verdict 闭环）。

拆分重构自 kline_returns.simulate_holding（非复用）：
  - FillPolicy.fill → Executor（line 101 entry=bars[idx+1].open）
  - path_return → Accounting（lines 104-119 stop/take/max_hold + return）
T+1 guard（idx+2>=len → None）保留——Accounting 需 T+2（首可卖日）才能算 path。

cost 模型（spec §2）：0.15% round-trip（0.10% slippage + 0.05% residual half-spread）
+ 印花 0.1%（sell-side）
+ 佣金 5 元（per side，A 股最低佣金）。apply_cost=False 时 simulate_holding
legacy 无 cost（backward compat 精确匹配）。
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.bar_utils import _bar_get
from engine.decision import Trades
from engine.executor import fillability_check

#: round-trip spread+slippage 成本（百分点，不含佣金/印花）。
#: S201b：0.70→0.15（0.10% slippage S189 T0_SLIPPAGE_PCT + 0.05% residual half-spread；
#: 0.60% spread 是美股假设，A股 tick-based 0.02-0.20%，5元门佣金抵消低价 under-charge）。
ROUND_TRIP_COST_PCT: float = 0.15
#: A 股印花税（sell-side，百分点）。2023-08-28 起减半至 0.05%（原 0.10%）。
STAMP_DUTY_PCT: float = 0.05
STAMP_DUTY_PCT_PRE_2023_08_28: float = 0.10
#: 印花税减半生效日（A 股 2023-08-28 印花税减半）。
STAMP_DUTY_HALVING_DATE: str = "2023-08-28"
#: 最低佣金（per side，元——A 股散户最低 5 元/笔）。
COMMISSION_MIN_YUAN: float = 5.0
#: 散户佣金费率（百分点 of notional/side，万 2.5=0.025）。notional×rate 超 5 元最低后按费率（修原只 5 元最低低估中大单）。
COMMISSION_RATE_PCT: float = 0.025
#: T+0 VWAP→execution 往返 shortfall（百分点，市场冲击 + 半价差×2）。
#: T+0 成交价已是分钟 VWAP（市场均价），不需 breakout 的 0.70% 理论价桥接——真实 shortfall
#: 对流动 A 股约 0.05-0.20%，取 0.10% 保守。S189 grill 修订（原 t0_cost 直接 return _cost_pct 0.70% 高估 T+0 成本 ~5x）。
T0_SLIPPAGE_PCT: float = 0.10
#: S201b stage 2: 止损正常触发的微小滑点（fill 略低于止损价，市场冲击）。
#: gap-through 是主修正项（48% stop exits gap-through at open），eps 是正常触止损的次要修正。
STOP_SLIPPAGE_EPS: float = 0.001


@dataclass(frozen=True)
class PathReturn:
    """单笔交易 path 模拟结果（喂 S161 verifier 的 raw per-trade return）。

    won: 止盈/max_hold 盈 / 止损亏（exit_reason 决定，非 return_pct 符号）。
    return_pct: apply_cost=True 为 net（扣 cost）；False 为 gross（backward compat）。
    cost_pct: 本次交易成本（百分点，0 当 apply_cost=False）。
    """

    won: bool
    return_pct: float
    exit_reason: str  # "stop" | "take" | "max_hold"
    exit_date: str
    cost_pct: float = 0.0
    gross_return_pct: float = 0.0
    # S175 T2（spec grill SH7）：三分支均设。S201b stage 2 修复 stop gap-through-aware
    # fill（open<=stop→fill=open, low<=stop→fill=stop*(1-eps), 一字跌停→carry）；
    # take=limit sell 触及即成交（不 gap-through，防高估盈利）；max_hold=bars[exit_idx].close。
    exit_price: float = 0.0


def _stamp_duty_for_date(entry_date: str) -> float:
    """A 股印花税随成交日：2023-08-28 前 0.10%，起 0.05%（sell-side）。

    entry_date YYYY-MM-DD；空/无法解析 → 当前 0.05%（保守低估，多数近期 backtest 适用）。
    """
    if entry_date and entry_date[:10] < STAMP_DUTY_HALVING_DATE:
        return STAMP_DUTY_PCT_PRE_2023_08_28
    return STAMP_DUTY_PCT


def _cost_pct(entry_price: float, size: float, entry_date: str = "") -> float:
    """A 股 round-trip 成本（百分点 of notional）。

    = ROUND_TRIP_COST_PCT + 印花税（随成交日 0.10%/0.05%）+ 佣金（5 元×2 side / notional × 100）。
    notional=entry_price×size（size 默认 100 = 1 手）。
    佣金按最低 5 元/side 算（散户小单普遍触发最低，保守）。
    """
    notional = entry_price * size
    stamp = _stamp_duty_for_date(entry_date)
    if notional <= 0:
        return ROUND_TRIP_COST_PCT + stamp
    commission_pct = (COMMISSION_MIN_YUAN * 2 / notional) * 100
    return ROUND_TRIP_COST_PCT + stamp + commission_pct


def t0_cost(entry_price: float, size: float, date: str = "") -> float:
    """S189 · T+0 当日往返成本（百分点 of notional）。

    S189 grill 修订：T+0 成交价是分钟 VWAP（市场均价），不需 breakout 的 0.70% 理论价桥接。
    = T0_SLIPPAGE_PCT(0.10% VWAP→execution shortfall) + 印花(0.05%) + 佣金(max(notional×0.025%, 5元)×2)。
    佣金用 max(费率, 最低)——中大单按费率（修原只有 5 元最低低估大单 bug）。
    """
    notional = entry_price * size
    stamp = _stamp_duty_for_date(date)
    if notional <= 0:
        return T0_SLIPPAGE_PCT + stamp + COMMISSION_RATE_PCT
    commission_yuan = max(notional * COMMISSION_RATE_PCT / 100, COMMISSION_MIN_YUAN) * 2
    commission_pct = commission_yuan / notional * 100
    return T0_SLIPPAGE_PCT + stamp + commission_pct


def _find_signal_idx(bars: list, signal_date: str) -> int | None:
    """在 bars 中找 signal_date 的 idx（date 字段前 10 字符匹配）。"""
    return next(
        (i for i, b in enumerate(bars)
         if str(_bar_get(b, "date", ""))[:10] == signal_date),
        None,
    )


def _is_sellable_bar(high_f: float, low_f: float, stop_level: float) -> bool:
    """检查止损卖单能否在此 bar 成交（非一字跌停 locked）。

    一字跌停：high==low（无日内振幅）且价格在止损位或以下 → 无法卖，须 carry。
    一字涨停：high==low 但价格在止损位以上 → 不影响（不会触止损）。
    """
    if high_f == low_f and high_f <= stop_level:
        return False
    return True


def path_return(
    trades: Trades,
    bars: list,
    stop_pct: float,
    take_profit_pct: float,
    max_hold_days: int,
    apply_cost: bool = True,
) -> PathReturn | None:
    """design-agnostic path return + cost + survivorship。

    输入：filled Trades（Executor 填好 entry_price + fill_status）+ bars + params。
    输出：PathReturn（won/return_pct/exit_reason/exit_date/cost_pct/gross_return_pct）或 None。

    只对 ACCEPTED fills 算（trades.is_accepted()）。refused → None（无 return）。
    survivorship 二次 guard：即使 Trades 标 accepted，entry_bar 仍 fillability_check（防 bypass）。

    T+1 guard（idx+2>=len → None）：A 股 T+1 买 T+1 open，T+2 起才能卖——缺 T+2 无法算 path。
    stop/take/max_hold 逻辑抽自 simulate_holding lines 104-119（拆分重构非复用）。
    """
    if not trades.is_accepted() or trades.entry_price is None:
        return None  # refused fills 无 return

    if not bars:
        return None
    # max_hold_days 须 ≥1：A 股 T+1（买 T+1 open，最早 T+2 卖），max_hold=0 会让 exit 落在
    # entry bar（T+1）违 T+1 结算。非法值→None（不臆算）。
    if not isinstance(max_hold_days, int) or max_hold_days < 1:
        return None
    idx = _find_signal_idx(bars, trades.signal_date)
    if idx is None or idx + 2 >= len(bars):
        return None  # T+1 guard：需 T+2（首可卖日）

    entry = float(trades.entry_price)  # Executor 填的 entry（非 bars[idx+1].open 重读）
    if not entry or entry <= 0:
        return None

    # survivorship 二次 guard：entry_bar fillability check（defense-in-depth）
    entry_idx = idx + 1
    if entry_idx < len(bars):
        fillable, _ = fillability_check(trades.code, bars[entry_idx])
        if not fillable:
            return None  # unbuyable/halted 即使标 accepted 也跳过

    cost = _cost_pct(entry, trades.size, entry_date=str(_bar_get(bars[entry_idx], "date", ""))) if apply_cost else 0.0

    # S201b stage 2: stop_level/take_level 提前算（gap-through-aware fill 需要）
    stop_level = entry * (1 + stop_pct / 100)
    take_level = entry * (1 + take_profit_pct / 100)

    # stop/take 循环（simulate_holding lines 104-112）——T+2 起检查
    for j in range(idx + 2, min(idx + 2 + max_hold_days, len(bars))):
        low = _bar_get(bars[j], "low", 0.0)
        high = _bar_get(bars[j], "high", 0.0)
        open_val = _bar_get(bars[j], "open", 0.0)
        try:
            low_f = float(low)
            high_f = float(high)
            open_f = float(open_val)
        except (TypeError, ValueError):
            continue
        # S201b stage 2: stop gap-through-aware fill（修硬编码 gross=float(stop_pct)）
        # 一字跌停 locked → 无法卖，carry 到下一 bar
        stop_fill_price: float | None = None
        if _is_sellable_bar(high_f, low_f, stop_level):
            if open_f and open_f <= stop_level:
                # gap-through：开盘已在止损位或以下 → fill=open（更差）
                stop_fill_price = open_f
            elif low_f and low_f <= stop_level:
                # 正常触止损：fill=止损位*(1-eps)（微小滑点）
                stop_fill_price = stop_level * (1 - STOP_SLIPPAGE_EPS)
        if stop_fill_price is not None:
            gross = (stop_fill_price - entry) / entry * 100
            net = gross - cost
            return PathReturn(
                won=False, return_pct=round(net, 2) if apply_cost else round(gross, 2),
                exit_reason="stop", exit_date=str(_bar_get(bars[j], "date", "")),
                cost_pct=cost, gross_return_pct=round(gross, 2),
                exit_price=stop_fill_price,
            )
        # S201b stage 2: take-side 不碰（limit sell 触及即成交，fill 在限价水平已 realistic）
        if high_f and high_f >= take_level:
            gross = float(take_profit_pct)
            net = gross - cost
            return PathReturn(
                won=(net if apply_cost else gross) > 0,
                return_pct=round(net, 2) if apply_cost else gross,
                exit_reason="take", exit_date=str(_bar_get(bars[j], "date", "")),
                cost_pct=cost, gross_return_pct=gross,
                exit_price=take_level,  # S175 T2：take level（limit sell，不 gap-through）
            )

    # max_hold exit（simulate_holding lines 113-119）
    exit_idx = min(idx + 1 + max_hold_days, len(bars) - 1)
    exit_price = _bar_get(bars[exit_idx], "close", 0.0)
    try:
        exit_f = float(exit_price)
    except (TypeError, ValueError):
        return None
    if not exit_f:
        return None
    gross = (exit_f - entry) / entry * 100
    net = gross - cost
    return PathReturn(
        won=(net if apply_cost else gross) > 0,
        return_pct=round(net, 2) if apply_cost else round(gross, 2),
        exit_reason="max_hold",
        exit_date=str(_bar_get(bars[exit_idx], "date", "")),
        cost_pct=cost,
        gross_return_pct=round(gross, 2),
        exit_price=exit_f,  # S175 T2：bars[exit_idx].close（:171 已算，现暴露）
    )


def gap_net_return(
    entry_price: float,
    exit_price: float,
    entry_date: str = "",
    size: float = 100,
) -> tuple[float, float, float]:
    """Overnight gap net return (buy T close, sell T+1 open, no stop/take).

    Unlike ``path_return`` (which needs bars + stop/take/max_hold), this is a
    pure 2-price event capture. Cost from ``_cost_pct`` (5 元 min commission +
    stamp duty + slippage), scaled to the trade's notional.

    Returns ``(net_return_ratio, cost_pct, gross_return_ratio)``.
    Ratios are decimal (0.013 = 1.3%); cost_pct is in percentage points
    (0.75 = 0.75%) — same unit as ``_cost_pct`` and ``PathReturn.cost_pct``.
    """
    if entry_price <= 0:
        return 0.0, 0.0, 0.0
    gross = exit_price / entry_price - 1.0
    cost = _cost_pct(entry_price, size, entry_date)
    net = gross - cost / 100.0
    return net, cost, gross


def path_return_as_dict(
    trades: Trades,
    bars: list,
    stop_pct: float,
    take_profit_pct: float,
    max_hold_days: int,
    apply_cost: bool = True,
) -> dict | None:
    """path_return 的 dict 包装——匹配 simulate_holding 原返回 shape（backward compat）。

    {won, return_pct, exit_reason, exit_date, cost_pct, gross_return_pct} 或 None。
    """
    pr = path_return(trades, bars, stop_pct, take_profit_pct, max_hold_days, apply_cost)
    if pr is None:
        return None
    return {
        "won": pr.won,
        "return_pct": pr.return_pct,
        "exit_reason": pr.exit_reason,
        "exit_date": pr.exit_date,
        "cost_pct": pr.cost_pct,
        "gross_return_pct": pr.gross_return_pct,
    }
