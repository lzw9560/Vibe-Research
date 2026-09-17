# -*- coding: utf-8 -*-
"""S204 T4: underpowered 诚实标注 + R17 数据源诚实标注（§44v2 rule②）。

数据不够（<60 天 / institutional 季度 cadence <10 事件）标 underpowered
不外推 robust/falsified verdict——守不臆造底线（§44v2 rule②）。
数据源限制（撤单率不可得 / mootdx tick 缺）标诚实标签非硬编码 0.0（R17）。

本模块是 harness post-process 纯函数，不改 verifier/stats——harness 在
调 wire_verdict 前先查本模块，underpowered 则跳过 verdict 不外推。

spec: specs/S204-多日跟踪架构与§44v2修正/tasks.md T4
"""
from __future__ import annotations

from dataclasses import dataclass

# §44v2 rule②：days<60 → underpowered（不外推 robust/falsified）
_MIN_DAYS_ROBUST = 60

# institutional 季度披露 cadence——n_events<10 独立事件 → structural underpowered
#（verifier 无此机制，harness post-process override）
_INSTITUTIONAL_MIN_EVENTS = 10
_STRUCTURAL_UNDERPOWERED_SOURCES = frozenset({"institutional"})

# R17 数据源诚实标注：不可得/BLOCKER 标签（非硬编码 0.0）
# key = 数据源字段名，value = 诚实标签（harness 展示用，不参与计算）
_DATA_SOURCE_LIMITATIONS: dict[str, str] = {
    # 撤单率：腾讯行情不含撤单率（bidding_monitor.py:103/133 当前 0.0）
    # 标"不可得"非硬编码 0.0——守不臆造底线
    "cancel_rate": "不可得（仅 seal_amount 阈值，腾讯行情不含撤单率）",
    # mootdx 实时分笔：回测无 tick 数据，用 5min kline 近似
    # daily OHLCV 做 VWAP 代理 = look-ahead，标 BLOCKER
    "mootdx_tick": "BLOCKER（回测用 5min kline 近似，非 daily OHLCV 做 VWAP 代理=look-ahead）",
}


@dataclass(frozen=True)
class UnderpoweredLabel:
    """数据源样本量诚实标注（immutable）。

    label 三态：
    - ``underpowered``: days<60，不外推 verdict（§44v2 rule②）
    - ``structural_underpowered``: institutional 季度 cadence n_events<10
      （verifier 无此机制，harness override）
    - ``adequate``: 样本够，可外推
    """

    source: str
    days: int
    label: str  # "underpowered" / "structural_underpowered" / "adequate"
    reason: str


def label_underpowered(
    source: str, days: int, n_events: int | None = None
) -> UnderpoweredLabel:
    """标数据源是否 underpowered（纯函数，immutable 返新对象）。

    Args:
        source: 数据源名（如 ``"gene_scores"`` / ``"seal_intraday"``
            / ``"sti_regime"`` / ``"institutional"``）。
        days: 样本天数（交易日）。
        n_events: 独立事件数（institutional 季度 cadence 用，可选）。

    Returns:
        ``UnderpoweredLabel``：underpowered / structural_underpowered / adequate。
        - institutional + n_events<10 → structural_underpowered（季度 cadence）
        - days<60 → underpowered（§44v2 rule② 不外推）
        - 否则 adequate

    WHY institutional override：institutional 季度披露 ~4 事件/年，即使 days=365
    独立事件也 <10 → structural underpowered（verifier R6 只查 days<60 不查
    事件 cadence，harness post-process 须 override 防假 robust）。
    """
    # structural_underpowered 优先（institutional 季度 cadence，n_events<10）
    if (
        source in _STRUCTURAL_UNDERPOWERED_SOURCES
        and n_events is not None
        and n_events < _INSTITUTIONAL_MIN_EVENTS
    ):
        return UnderpoweredLabel(
            source=source,
            days=days,
            label="structural_underpowered",
            reason=f"institutional quarterly cadence, n_events={n_events}<{_INSTITUTIONAL_MIN_EVENTS}",
        )
    # days<60 → underpowered（§44v2 rule② 不外推 robust/falsified）
    if days < _MIN_DAYS_ROBUST:
        return UnderpoweredLabel(
            source=source,
            days=days,
            label="underpowered",
            reason=f"days<{_MIN_DAYS_ROBUST} §44v2 rule②",
        )
    # 样本够 → adequate
    return UnderpoweredLabel(source=source, days=days, label="adequate", reason="")


def label_data_source_limitation(source: str) -> str:
    """R17 数据源诚实标注：返限制标签（纯函数，返 str）。

    不可得/BLOCKER 的数据源返诚实标签，harness 展示用（不硬编码 0.0 当真值）。
    无已知限制的源返空串（不臆造限制）。

    Args:
        source: 数据源字段名（如 ``"cancel_rate"`` / ``"mootdx_tick"``）。

    Returns:
        诚实标签 str（无限制返 ``""``）。
    """
    return _DATA_SOURCE_LIMITATIONS.get(source, "")


__all__ = [
    "UnderpoweredLabel",
    "label_underpowered",
    "label_data_source_limitation",
]
