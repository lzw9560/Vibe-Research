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

cost 模型（spec §2）：0.70% round-trip（spread+slippage）+ 印花 0.1%（sell-side）
+ 佣金 5 元（per side，A 股最低佣金）。apply_cost=False 时 simulate_holding
legacy 无 cost（backward compat 精确匹配）。
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.bar_utils import _bar_get
from engine.decision import Trades
from engine.executor import fillability_check

#: round-trip spread+slippage 成本（百分点，不含佣金/印花）。
ROUND_TRIP_COST_PCT: float = 0.70
#: 印花税（sell-side，百分点）。
STAMP_DUTY_PCT: float = 0.10
#: 最低佣金（per side，元——A 股散户最低 5 元/笔）。
COMMISSION_MIN_YUAN: float = 5.0


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


def _cost_pct(entry_price: float, size: float) -> float:
    """A 股 round-trip 成本（百分点 of notional）。

    = ROUND_TRIP_COST_PCT + STAMP_DUTY_PCT + 佣金（5 元×2 side / notional × 100）。
    notional=entry_price×size（size 默认 100 = 1 手）。
    佣金按最低 5 元/side 算（散户小单普遍触发最低，保守）。
    """
    notional = entry_price * size
    if notional <= 0:
        return ROUND_TRIP_COST_PCT + STAMP_DUTY_PCT
    commission_pct = (COMMISSION_MIN_YUAN * 2 / notional) * 100
    return ROUND_TRIP_COST_PCT + STAMP_DUTY_PCT + commission_pct


def _find_signal_idx(bars: list, signal_date: str) -> int | None:
    """在 bars 中找 signal_date 的 idx（date 字段前 10 字符匹配）。"""
    return next(
        (i for i, b in enumerate(bars)
         if str(_bar_get(b, "date", ""))[:10] == signal_date),
        None,
    )


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

    cost = _cost_pct(entry, trades.size) if apply_cost else 0.0

    # stop/take 循环（simulate_holding lines 104-112）——T+2 起检查
    for j in range(idx + 2, min(idx + 2 + max_hold_days, len(bars))):
        low = _bar_get(bars[j], "low", 0.0)
        high = _bar_get(bars[j], "high", 0.0)
        try:
            low_f = float(low)
            high_f = float(high)
        except (TypeError, ValueError):
            continue
        if low_f and low_f <= entry * (1 + stop_pct / 100):
            gross = float(stop_pct)
            net = gross - cost
            return PathReturn(
                won=False, return_pct=round(net, 2) if apply_cost else gross,
                exit_reason="stop", exit_date=str(_bar_get(bars[j], "date", "")),
                cost_pct=cost, gross_return_pct=gross,
            )
        if high_f and high_f >= entry * (1 + take_profit_pct / 100):
            gross = float(take_profit_pct)
            net = gross - cost
            return PathReturn(
                won=True, return_pct=round(net, 2) if apply_cost else gross,
                exit_reason="take", exit_date=str(_bar_get(bars[j], "date", "")),
                cost_pct=cost, gross_return_pct=gross,
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
    )


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
