# -*- coding: utf-8 -*-
"""S162 R1/R3 Executor 层——可插拔 fill + A 股成交规则建模。

职责（学 zipline blotter 执行模拟与记账解耦）：
  1. 调 FillPolicy.fill → entry price + offset≥1 反前视。
  2. A 股成交规则 fillability check（T+1 结算 / 涨跌停闸门 / 停牌 / unbuyable）。
  3. 返回 filled Trades（entry_price + fill_status）；refused fills → untradeable 无 return。

R3 A 股规则（开源避免模式①——不裸调乐观撮合）：
  - T+1 结算：当日买入不可卖（FillPolicy offset≥1 内含，T+2 起检查 stop/take 在 Accounting）。
  - 涨跌停闸门：±10% 主板 / ±5% ST / ±20% 创业科创 / ±30% 北交——触板不成交。
    T+1OpenFill 买开盘：开盘=涨停价且四价相等（一字板）→ 不可买（is_unbuyable）。
  - 停牌：volume/amount==0 → 该日不可交易（is_halted）。

Accounting 只对 Executor ACCEPTED 的 fills 算 return；refused fills → status=untradeable
无 return（否则 simulate_holding 仍从 bars[idx+1].open 算 = 错窗口）。

R5 gap bypasses engine：gap Trades（fill_type=intraday_conditional）→ IntradayConditionalFill
返 untradeable → engine 拒绝。gap run 绕过 engine 直接算 D close→D+1 open。
"""
from __future__ import annotations

from engine.bar_utils import _bar_get, is_halted, is_unbuyable_next_bar
from engine.decision import FILL_ACCEPTED, FILL_UNTRADEABLE, Trades
from engine.fill_policies import FillPolicy, FillResult


class Executor:
    """执行引擎——FillPolicy 填价 + A 股规则 fillability check。

    不算 return（Accounting 的活）；不生成 Trades（Decision 的活）。
    只做：取 Trades → 调 FillPolicy → A 股规则 check → 返 filled Trades。
    """

    def execute(self, trades: Trades, bars: list, fill_policy: FillPolicy) -> Trades:
        """执行 fill：FillPolicy 算 entry → A 股规则 check → filled Trades。

        返回新 Trades（immutable，entry_price + fill_status 填好）。
        untradeable 时 entry_price=None, fill_status=UNTRADEABLE, fill_reason 标原因。
        """
        result: FillResult = fill_policy.fill(trades.signal_date, bars)
        if result.status != FILL_ACCEPTED or result.entry_price is None:
            return trades.with_fill(None, FILL_UNTRADEABLE, result.reason)

        # FillPolicy 接受了 → A 股成交规则 fillability check
        entry_idx = result.fill_bar_idx
        if entry_idx is None or entry_idx >= len(bars):
            return trades.with_fill(None, FILL_UNTRADEABLE, "no_entry_bar")

        entry_bar = bars[entry_idx]
        # 停牌检查（volume/amount==0 → 不可交易）
        if is_halted(entry_bar):
            return trades.with_fill(None, FILL_UNTRADEABLE, "halted")

        # 涨跌停闸门——一字板涨停封死（board-aware，用 trades.code 判板块）
        if is_unbuyable_next_bar(entry_bar, code=trades.code):
            return trades.with_fill(None, FILL_UNTRADEABLE, "limit_up_locked")

        # 所有 A 股规则通过 → 接受 fill
        return trades.with_fill(
            result.entry_price, FILL_ACCEPTED, result.reason or "accepted"
        )


def fillability_check(code: str, entry_bar: object) -> tuple[bool, str]:
    """独立 fillability 检查（供 Accounting survivorship 二次 guard 用）。

    返 (fillable, reason)。与 Executor 内部 check 同逻辑，defense-in-depth：
    Accounting 只对 ACCEPTED fills 算 return，但也二次 guard（防 bypass）。
    """
    if is_halted(entry_bar):
        return False, "halted"
    if is_unbuyable_next_bar(entry_bar, code=code):
        return False, "limit_up_locked"
    return True, "ok"
