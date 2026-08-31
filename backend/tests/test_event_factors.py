# -*- coding: utf-8 -*-
"""S066 Phase 2 P2-4 产业资本 + 事件类因子测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.event_factors import (
    EventFactor,
    EventContext,
    fetch_earnings_forecast,
    fetch_shareholder_change,
    fetch_share_unlock,
    fetch_share_unlock_with_status,
    check_ex_dividend,
    build_event_context,
    classify_announcement_llm,
)


class TestCheckExDividend:
    """除权除息日历（spec §16.11）。"""

    def test_no_calendar(self, monkeypatch):
        """无日历 → (False, "未取得")。"""
        monkeypatch.setattr("strategies.event_factors._load_ex_dividend_calendar", lambda: {})
        result, note = check_ex_dividend("000001", "2026-08-14")
        assert result is False
        assert "未取得" in note

    def test_no_events(self, monkeypatch):
        monkeypatch.setattr("strategies.event_factors._load_ex_dividend_calendar", lambda: {"events": []})
        result, note = check_ex_dividend("000001", "2026-08-14")
        assert result is False

    def test_event_in_range(self, monkeypatch):
        """持仓期间有除权除息 → True。"""
        cal = {"events": [{"code": "000001", "date": "2026-08-20", "type": "10送5"}]}
        monkeypatch.setattr("strategies.event_factors._load_ex_dividend_calendar", lambda: cal)
        result, note = check_ex_dividend("000001", "2026-08-14", forward_days=30)
        assert result is True
        assert "2026-08-20" in note

    def test_event_outside_range(self, monkeypatch):
        """除权除息在持仓期外 → False。"""
        cal = {"events": [{"code": "000001", "date": "2026-12-31", "type": "10送5"}]}
        monkeypatch.setattr("strategies.event_factors._load_ex_dividend_calendar", lambda: cal)
        result, _ = check_ex_dividend("000001", "2026-08-14", forward_days=30)
        assert result is False

    def test_different_code(self, monkeypatch):
        """不同股票代码的事件不匹配。"""
        cal = {"events": [{"code": "000002", "date": "2026-08-20", "type": "10送5"}]}
        monkeypatch.setattr("strategies.event_factors._load_ex_dividend_calendar", lambda: cal)
        result, _ = check_ex_dividend("000001", "2026-08-14")
        assert result is False

    def test_invalid_date(self, monkeypatch):
        monkeypatch.setattr("strategies.event_factors._load_ex_dividend_calendar", lambda: {"events": [{"code": "000001", "date": "2026-08-20", "type": "10送5"}]})
        result, note = check_ex_dividend("000001", "invalid-date")
        assert result is False
        assert "格式错误" in note


class TestClassifyAnnouncementLLM:
    """公告分类（LLM 辅助）。"""

    def test_no_chat_fn_falls_back_to_keywords(self):
        """无 chat_fn → 关键词粗筛降级。"""
        result = classify_announcement_llm("2026年半年度业绩预增公告", chat_fn=None)
        assert result == "预增"

    def test_chat_fn_used(self):
        """有 chat_fn → 用 LLM。"""
        mock_chat = lambda prompt: "重组"
        result = classify_announcement_llm("重大资产重组", chat_fn=mock_chat)
        assert result == "重组"

    def test_chat_fn_failure_falls_back(self):
        """LLM 调用失败 → 关键词降级。"""
        def failing_chat(prompt):
            raise Exception("LLM unavailable")
        result = classify_announcement_llm("业绩预增公告", chat_fn=failing_chat)
        assert result == "预增"


class TestEventContext:
    """事件上下文聚合。"""

    def test_build_context_with_mocks(self, monkeypatch):
        """构建上下文（mock 各数据源）。"""
        mock_event = [EventFactor("业绩预告", "2026-08-01", "利好", "预增", 1.0)]
        monkeypatch.setattr("strategies.event_factors.fetch_earnings_forecast", lambda c: mock_event)
        monkeypatch.setattr("strategies.event_factors.fetch_shareholder_change", lambda c: [])
        monkeypatch.setattr("strategies.event_factors.fetch_share_unlock_with_status", lambda c: ([], "ok"))
        monkeypatch.setattr("strategies.event_factors.check_ex_dividend", lambda c, d, **kw: (False, "无"))

        ctx = build_event_context("000001", "2026-08-14")
        assert ctx.code == "000001"
        assert len(ctx.events) == 1
        assert ctx.events[0].event_type == "业绩预告"
        assert ctx.has_upcoming_ex_dividend is False
        assert ctx.lockup_data_status == "ok"

    def test_build_context_empty(self, monkeypatch):
        """所有数据源失败 → 空上下文（不崩）。"""
        monkeypatch.setattr("strategies.event_factors.fetch_earnings_forecast", lambda c: [])
        monkeypatch.setattr("strategies.event_factors.fetch_shareholder_change", lambda c: [])
        monkeypatch.setattr("strategies.event_factors.fetch_share_unlock_with_status", lambda c: ([], "ok"))
        monkeypatch.setattr("strategies.event_factors.check_ex_dividend", lambda c, d, **kw: (False, "无"))

        ctx = build_event_context("000001")
        assert ctx.code == "000001"
        assert ctx.events == []
        assert ctx.lockup_data_status == "ok"

    def test_events_aggregated(self, monkeypatch):
        """多数据源事件合并。"""
        e1 = [EventFactor("业绩预告", "2026-08-01", "利好", "预增", 1.0)]
        e2 = [EventFactor("增减持", "2026-08-02", "利空", "减持", -0.6)]
        e3 = [EventFactor("解禁", "2026-08-10", "风险提示", "解禁 5%", -0.7)]

        monkeypatch.setattr("strategies.event_factors.fetch_earnings_forecast", lambda c: e1)
        monkeypatch.setattr("strategies.event_factors.fetch_shareholder_change", lambda c: e2)
        monkeypatch.setattr("strategies.event_factors.fetch_share_unlock_with_status", lambda c: (e3, "ok"))
        monkeypatch.setattr("strategies.event_factors.check_ex_dividend", lambda c, d, **kw: (False, "无"))

        ctx = build_event_context("000001")
        assert len(ctx.events) == 3
        types = [e.event_type for e in ctx.events]
        assert "业绩预告" in types
        assert "增减持" in types
        assert "解禁" in types
        assert ctx.lockup_data_status == "ok"
