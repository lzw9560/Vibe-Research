# -*- coding: utf-8 -*-
"""S204 T4: underpowered 诚实标注 + R17 数据源诚实标注（§44v2 rule②）。

数据不够（<60 天 / <10 事件）标 underpowered 不外推结论——守不臆造底线。
数据源限制（撤单率不可得 / mootdx tick 缺）标诚实标签非硬编码 0.0。
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from s44_verifier.underpowered_label import (
    UnderpoweredLabel,
    label_underpowered,
    label_data_source_limitation,
)


class TestUnderpoweredLabel:
    """§44v2 rule②：数据不够不外推 robust/falsified verdict。"""

    def test_gene_scores_underpowered_label(self):
        # gene_scores ~60 天（实测 7466 行，spec §1.2 核 <60 R6 gate）
        # Arrange: days=59 < 60 → underpowered
        result = label_underpowered(source="gene_scores", days=59)
        # Assert: 标 underpowered，不输出 robust/falsified（harness 不外推）
        assert result.label == "underpowered"
        assert "60" in result.reason
        assert result.source == "gene_scores"
        assert result.days == 59

    def test_seal_intraday_underpowered(self):
        # seal_intraday 10 天 → underpowered
        result = label_underpowered(source="seal_intraday", days=10)
        assert result.label == "underpowered"
        assert result.days == 10

    def test_sti_zero_days(self):
        # STI 退潮/高潮 0 天 → underpowered（regime_adaptation 无数据不验）
        result = label_underpowered(source="sti_regime", days=0)
        assert result.label == "underpowered"
        assert result.days == 0

    def test_institutional_quarterly_override(self):
        # institutional 季度披露 ~4 事件/年 → structural_underpowered
        # n_events=4 < 10 → structural override（verifier 无此机制，harness post-process）
        result = label_underpowered(
            source="institutional", days=365, n_events=4
        )
        assert result.label == "structural_underpowered"
        assert "quarterly" in result.reason or "cadence" in result.reason

    def test_adequate_when_days_and_events_sufficient(self):
        # days>=60 + 非 institutional（或 institutional n_events>=10）→ adequate
        result = label_underpowered(source="gene_scores", days=100)
        assert result.label == "adequate"
        assert result.reason == ""

    def test_institutional_adequate_when_events_sufficient(self):
        # institutional n_events>=10 → adequate（非 structural_underpowered）
        result = label_underpowered(
            source="institutional", days=365, n_events=15
        )
        assert result.label == "adequate"

    def test_boundary_days_exactly_60_is_adequate(self):
        # 边界：days=60（>=60）→ adequate（rule② 是 days<60 not <=60）
        result = label_underpowered(source="seal_intraday", days=60)
        assert result.label == "adequate"

    def test_underpowered_label_frozen(self):
        # UnderpoweredLabel immutable——setattr 报 FrozenInstanceError
        label = UnderpoweredLabel(
            source="gene_scores", days=59, label="underpowered", reason="days<60"
        )
        with pytest.raises(FrozenInstanceError):
            label.days = 100  # type: ignore[misc]

    def test_label_underpowered_pure_function(self):
        # 同输入 → 同输出（无副作用）
        a = label_underpowered(source="seal_intraday", days=10)
        b = label_underpowered(source="seal_intraday", days=10)
        assert a == b


class TestDataSourceLimitation:
    """R17 数据源诚实标注：不可得/BLOCKER 标签非硬编码 0.0。"""

    def test_cancel_rate_honest(self):
        # cancel_rate 字段标 "不可得（仅 seal_amount 阈值）" 非硬编码 0.0
        # bidding_monitor.py:103/133 当前 cancel_rate=0.0（腾讯行情不含撤单率）
        label = label_data_source_limitation("cancel_rate")
        # Assert: 标签含"不可得"，不返回数字 0.0 当真值
        assert "不可得" in label
        assert "0.0" not in label  # 不把 0.0 当诚实值
        assert "seal_amount" in label or "阈值" in label

    def test_mootdx_tick_blocker_label(self):
        # mootdx 实时分笔标 BLOCKER，回测用 5min kline 近似（非 daily OHLCV 做 VWAP 代理=look-ahead）
        label = label_data_source_limitation("mootdx_tick")
        assert "BLOCKER" in label
        assert "5min" in label or "近似" in label

    def test_no_limitation_for_clean_source(self):
        # 无已知限制的数据源 → 空标签（不臆造限制）
        label = label_data_source_limitation("close_price")
        assert label == ""

    def test_label_data_source_limitation_returns_str(self):
        # 返回 str（纯函数，immutable）
        label = label_data_source_limitation("cancel_rate")
        assert isinstance(label, str)
