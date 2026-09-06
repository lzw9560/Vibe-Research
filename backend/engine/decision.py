# -*- coding: utf-8 -*-
"""S162 R1a Decision 层——Trades dataclass + generate_trade_decision stub。

Trades 是**本项目自设计**（非 qlib BaseTradeDecision 借）——spec v2 修：
qlib 实际 API 非 generate_trade_decision（v1 误引已纠），real API =
BaseExecutor.execute(trade_decision) → execute_result + NestedExecutor 线程嵌套。
R1a Trades 可 NOW 实现；R1b（qlib 嵌套决策 inspiration）deferred 待源码核实。

v2 关键修（治 grill #6 两分支都破）：entry_price 是 Executor FillPolicy **唯一源**
（Decision INPUT 不带 entry_price/exit_price，Executor 填）；signal_date + fill_type
在 INPUT batch。Trades 自带 signal_date → PIT store 无消费者（deferred，engine 读
pre-loaded bars 非 PIT query）。
"""
from __future__ import annotations

from dataclasses import dataclass

#: T+1 开盘买入 fill（默认，offset≥1 anti-lookahead）。
FILL_T_PLUS_1_OPEN: str = "t1_open"
#: 盘中条件成交 fill（封板事件条件，deferred stub 返 untradeable）。
FILL_INTRADAY_CONDITIONAL: str = "intraday_conditional"

#: fill 状态——Executor 填后设。
FILL_PENDING: str = "pending"
FILL_ACCEPTED: str = "accepted"
FILL_UNTRADEABLE: str = "untradeable"

#: A 股 1 手 = 100 股（佣金 5 元最低门槛换算用）。
DEFAULT_LOT_SIZE: float = 100.0


@dataclass(frozen=True)
class Trades:
    """单笔交易决策（immutable，三层流转的载体）。

    INPUT（Decision 生成，Executor 前）：code + signal_date + fill_type + direction + size。
    entry_price=None / exit_date=None / exit_price=None / fill_status=FILL_PENDING。

    Executor 填：entry_price（FillPolicy 唯一源）+ fill_status（ACCEPTED/UNTRADEABLE）。
    Accounting 读：entry_price + fill_status（只对 ACCEPTED 算 return）；exit_* 由
    Accounting 结果携带（PathReturn），Trades 本体 exit_* 留 future trade-journal 用。

    direction: "long"（A 股做多，无做空）/ "short"（预留，A 股不可做空但留接口）。
    size: 股数（默认 100 = 1 手，佣金换算用）。
    """

    code: str
    signal_date: str
    fill_type: str
    direction: str
    size: float
    entry_price: float | None = None
    exit_date: str | None = None
    exit_price: float | None = None
    fill_status: str = FILL_PENDING
    fill_reason: str = ""

    def is_accepted(self) -> bool:
        """Executor 是否接受此 fill（Accounting 只对 accepted 算 return）。"""
        return self.fill_status == FILL_ACCEPTED

    def with_fill(self, entry_price: float | None, status: str, reason: str = "") -> "Trades":
        """返回填好 entry_price + status 的新 Trades（immutable，不 mutate）。"""
        return Trades(
            code=self.code,
            signal_date=self.signal_date,
            fill_type=self.fill_type,
            direction=self.direction,
            size=self.size,
            entry_price=entry_price,
            exit_date=self.exit_date,
            exit_price=self.exit_price,
            fill_status=status,
            fill_reason=reason,
        )


def generate_trade_decision(*args, **kwargs):  # type: ignore[no-untyped-def]
    """R1b stub——TODO 待 qlib gh-proxy 源码核实。

    spec v2 §0：qlib real API = BaseExecutor.execute(trade_decision, level=0) → List[object]
    + NestedExecutor 经 execute_result 线程嵌套 + _update_trade_decision（:396）；
    决策对象 BaseTradeDecision(Generic[DecisionType]) / TradeDecisionWO(BaseTradeDecision[Order])
    （decision.py:302/547）。**generate_trade_decision 不存在于 qlib**（v1 误引已纠，
    grill ant_lookahead #8 标 unverified 正确）。R1a Trades 是本项目自设计非 qlib 借。
    此 stub 不臆造签名——等 qlib 源码核实后再实现嵌套决策 inspiration。
    """
    raise NotImplementedError(
        "generate_trade_decision 待 qlib gh-proxy 源码核实（R1b deferred）。"
        " qlib real API = execute(trade_decision)->execute_result，非本签名。"
        " NOW 用 Trades dataclass 手动构造（如 gap run 直接构造）。"
    )
