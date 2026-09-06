# -*- coding: utf-8 -*-
"""S162 R1 Executor 层——FillPolicy 接口 + T+1OpenFill + IntradayConditionalFill stub。

FillPolicy 只管 **何时/何价 fill**（entry price 计算，offset≥1 anti-lookahead）。
A 股成交规则（涨跌停闸门/停牌/unbuyable）在 Executor 层（非 FillPolicy）——FillPolicy
与记账解耦（学 zipline blotter）。

R2 反前视架构级（开源模式①）：backtrader 0/-1 索引（策略 next() 只看已收盘 bar）+
cheat_on_open 显式开关（默认关）。batch-mode enforcement = FillPolicy offset
（bars[signal_idx+1]，非 event-driven cursor）——治 §44v1 错窗口根因。

R5 gap bypasses engine：IntradayConditionalFill deferred stub 主动返 untradeable
（活哨兵非死代码，治 grill yagni refuted）。gap §44v2 run 绕过 engine 直接算
D close→D+1 open——engine 拒绝对未建模 fill 的隔夜捕获。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from engine.bar_utils import _bar_get
from engine.decision import FILL_ACCEPTED, FILL_UNTRADEABLE


@dataclass(frozen=True)
class FillResult:
    """FillPolicy.fill 的返回——entry price + 状态 + 原因 + 入场 bar idx。

    entry_price: None 表示未成交（untradeable）；非 None 表示成交价。
    fill_bar_idx: 入场 bar 在 bars 列表的 idx（Accounting 定位 stop/take 循环用）。
    """

    entry_price: float | None
    status: str  # FILL_ACCEPTED | FILL_UNTRADEABLE
    reason: str = ""
    fill_bar_idx: int | None = None


@runtime_checkable
class FillPolicy(Protocol):
    """可插拔 fill 策略接口（structural typing，T+1OpenFill / IntradayConditionalFill 实现）。"""

    def fill(self, signal_date: str, bars: list) -> FillResult:  # type: ignore[empty-body]
        """根据 signal_date + bars 算 entry price + 状态。

        offset≥1 强约束（反前视）：entry bar 必须在 signal bar 之后（T+1 或更晚），
        不允许用 signal bar 当日数据 fill（look-ahead）。
        """
        ...


class T1OpenFill:
    """T+1 开盘买入（默认 fill，offset≥1 anti-lookahead）。

    语义同 kline_returns.simulate_holding line 101：entry = bars[signal_idx+1].open。
    signal_date=T（盘后选股），买 T+1 开盘（次日开盘，当时可知）。offset=1（signal bar
    之后 1 bar），反前视强约束。

    cheat_on_open 概念（backtrader）：本 fill 默认"在 T+1 开盘前不知 T+1 数据"——
    entry 用 bars[idx+1].open 是 batch-mode 等价（开盘价是当日第一个成交价，
    选股在 T 盘后，T+1 开盘时可知）。非 event-driven cursor。
    """

    def fill(self, signal_date: str, bars: list) -> FillResult:
        if not bars:
            return FillResult(None, FILL_UNTRADEABLE, "empty_bars")
        idx = next(
            (i for i, b in enumerate(bars)
             if str(_bar_get(b, "date", ""))[:10] == signal_date),
            None,
        )
        if idx is None:
            return FillResult(None, FILL_UNTRADEABLE, "signal_date_not_in_bars")
        # offset≥1 反前视：入场 bar = signal bar 之后至少 1 bar（T+1）
        entry_idx = idx + 1
        if entry_idx >= len(bars):
            return FillResult(None, FILL_UNTRADEABLE, "no_t1_bar")
        entry = _bar_get(bars[entry_idx], "open", 0.0)
        try:
            entry_f = float(entry)
        except (TypeError, ValueError):
            entry_f = 0.0
        if not entry_f or entry_f <= 0:
            return FillResult(None, FILL_UNTRADEABLE, "invalid_entry_price")
        return FillResult(entry_f, FILL_ACCEPTED, "t1_open", entry_idx)


class IntradayConditionalFill:
    """盘中条件成交 fill stub（deferred——活哨兵，非死代码）。

    设计意图：封板事件条件成交（如竞价/秒板/封单条件成交 + 不封亏损，需 P(seal) 模型）。
    gap 方向（隔夜捕获 D 收→D+1 开）走此 fill——但 P(seal) 模型未建，**主动返 untradeable**。

    治 grill yagni refuted：不是"deferred=不写"，而是"写活哨兵返 untradeable"——
    engine 拒绝对未建模 fill 的隔夜捕获（诚实显示不可交易，治 s144 gap-blindness）。
    gap §44v2 run（S161 §3）绕过 engine 直接算 D close→D+1 open，不经此 fill。
    """

    def fill(self, signal_date: str, bars: list) -> FillResult:
        return FillResult(
            None,
            FILL_UNTRADEABLE,
            "intraday_conditional_not_implemented",
        )
