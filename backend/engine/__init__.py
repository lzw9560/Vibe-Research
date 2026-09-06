# -*- coding: utf-8 -*-
"""S162 反前视回测引擎三层——Decision + Accounting design-agnostic + Executor pluggable fill.

架构（世纪大辩论 verdict + grill-foundation-holes）：
  Decision(Trades 生成) → Executor(可插拔 fill + A 股规则) → Accounting(path return + cost + survivorship)

三层解耦治 §44v1 错窗口根因——entry 时点可捕获性作**架构级强约束**
（FillPolicy offset≥1，非策略层自律）。借鉴 backtrader 0/-1 索引 + cheat_on_open
显式开关（开源调研模式①）+ qlib Nested Decision Point（决策时只用当时可得信息）。

R5 gap §44v2 run bypasses engine：gap run（S161 §3）绕过 engine，直接从 daily bars
算（D close→D+1 open）——IntradayConditionalFill deferred，gap Trades 会被 engine
拒绝（untradeable）；engine 拒绝对未建模 fill 的隔夜捕获（诚实显示不可交易）。

PIT store（R4）已在 backend/pit_store/ 建重桩（commit 01a5807/bcd29ca）。engine 读
pre-loaded bars（如 simulate_holding 的 bars arg from kline_cache），非 PIT query。
"""
from __future__ import annotations

from engine.decision import Trades, FILL_T_PLUS_1_OPEN, FILL_INTRADAY_CONDITIONAL
from engine.fill_policies import (
    FillPolicy,
    FillResult,
    FILL_ACCEPTED,
    FILL_UNTRADEABLE,
    T1OpenFill,
    IntradayConditionalFill,
)
from engine.executor import Executor
from engine.accounting import path_return, PathReturn

__all__ = [
    "Trades",
    "FILL_T_PLUS_1_OPEN",
    "FILL_INTRADAY_CONDITIONAL",
    "FillPolicy",
    "FillResult",
    "FILL_ACCEPTED",
    "FILL_UNTRADEABLE",
    "T1OpenFill",
    "IntradayConditionalFill",
    "Executor",
    "path_return",
    "PathReturn",
]
