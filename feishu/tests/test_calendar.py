# -*- coding: utf-8 -*-
"""test_calendar.py — is_trading_day 边界测试。

测试覆盖：
- 周日（非交易日）
- 周一（交易日，假设非节假日）
- 节假日（国庆 2026-10-01）
- 正常交易日（2026-11-09 周一，非节假日）
- 日历覆盖 vs 日历不覆盖降级路径
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from feishu import calendar


@pytest.fixture(autouse=True)
def _reset_calendar_cache(monkeypatch):
    """每个测试前重置 calendar 模块的内存缓存，避免测试间污染。"""
    monkeypatch.setattr(calendar, "CALENDAR_DATES", None)
    yield
    monkeypatch.setattr(calendar, "CALENDAR_DATES", None)


def _mock_calendar(monkeypatch, dates: set[str]):
    """注入一个内存中的 load_trade_calendar，避免触碰文件系统/CLI。"""
    monkeypatch.setattr(calendar, "load_trade_calendar", lambda: dates)


# ─── 日历覆盖路径（日期在日历范围内） ───

def test_trading_day_calendar_covered(monkeypatch):
    """日历覆盖且命中 → True。"""
    _mock_calendar(monkeypatch, {"20261109", "20261110"})
    dt = datetime(2026, 11, 9)  # 周一
    assert calendar.is_trading_day(dt) is True


def test_non_trading_day_calendar_covered(monkeypatch):
    """日历覆盖但未命中（周末，日历不含周末）→ False。"""
    _mock_calendar(monkeypatch, {"20261109", "20261110"})
    dt = datetime(2026, 11, 8)  # 周日
    assert calendar.is_trading_day(dt) is False


# ─── 日历不覆盖降级路径（日期超出日历范围） ───

def test_non_trading_day_sunday_fallback(monkeypatch):
    """日历不覆盖 + 周日 → 降级返回 False。"""
    _mock_calendar(monkeypatch, set())  # 空日历 → 触发降级
    dt = datetime(2026, 11, 8)  # 周日
    assert calendar.is_trading_day(dt) is False


def test_trading_day_monday_fallback(monkeypatch):
    """日历不覆盖 + 周一（非节假日）→ 降级返回 True。"""
    _mock_calendar(monkeypatch, set())
    dt = datetime(2026, 11, 9)  # 周一，不在 _KNOWN_HOLIDAYS
    assert calendar.is_trading_day(dt) is True


def test_non_trading_day_holiday_fallback(monkeypatch):
    """日历不覆盖 + 已知节假日（国庆）→ 降级返回 False。"""
    _mock_calendar(monkeypatch, set())
    dt = datetime(2026, 10, 1)  # 国庆，在 _KNOWN_HOLIDAYS
    assert calendar.is_trading_day(dt) is False


def test_non_trading_day_saturday_fallback(monkeypatch):
    """日历不覆盖 + 周六 → 降级返回 False。"""
    _mock_calendar(monkeypatch, set())
    dt = datetime(2026, 11, 7)  # 周六
    assert calendar.is_trading_day(dt) is False


# ─── 边界值 ───

def test_all_weekdays_non_holiday_fallback(monkeypatch):
    """日历不覆盖时，周一到周五（非节假日）都应是交易日。"""
    _mock_calendar(monkeypatch, set())
    # 2026-11-09 周一 ~ 2026-11-13 周五，均非 _KNOWN_HOLIDAYS
    for day in range(9, 14):
        dt = datetime(2026, 11, day)
        assert calendar.is_trading_day(dt) is True, f"2026-11-{day} 应为交易日"


def test_known_holiday_spring_festival(monkeypatch):
    """春节假期（2026-02-15，日历不覆盖）→ False。"""
    _mock_calendar(monkeypatch, set())
    dt = datetime(2026, 2, 15)  # 春节，在 _KNOWN_HOLIDAYS
    assert calendar.is_trading_day(dt) is False


def test_holiday_in_calendar_overrides_weekday(monkeypatch):
    """日历覆盖路径：节假日落在日历中（日历不含该日）→ False，即使周一。"""
    # 日历有更晚的日期，2026-10-01 不在日历中 → 走降级 → 国庆 → False
    _mock_calendar(monkeypatch, {"20261109"})
    dt = datetime(2026, 10, 1)  # 国庆
    assert calendar.is_trading_day(dt) is False


def test_load_trade_calendar_caches(monkeypatch):
    """load_trade_calendar 第二次调用返回缓存的同一对象。"""
    monkeypatch.setattr(calendar, "CALENDAR_DATES", None)
    # 让缓存文件不存在 + 刷新返回空 → 返回空 set
    monkeypatch.setattr(calendar, "CALENDAR_CACHE", Path("/tmp/__nonexistent_calendar_test__.json"))
    monkeypatch.setattr(calendar, "refresh_trade_calendar", lambda: None)
    first = calendar.load_trade_calendar()
    second = calendar.load_trade_calendar()
    assert first is second  # 内存缓存生效
