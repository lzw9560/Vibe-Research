"""Tests for backend/predict/features/calendar.py — S018 calendar feature specs.

TDD: (a)-(g) covering FeatureSpec construction, registration, look-ahead guard,
and pure calendar functions (is_holiday, is_option_delivery_day, is_meeting_period).

All tests are offline (no network calls).
"""

import pytest


# ── (a) 3 个 FeatureSpec 构造合法 ─────────────────────────────────

def test_feature_specs_valid():
    """3 个 FeatureSpec 构造合法，stage/compliance_flag 校验通过。"""
    from predict.features.calendar import CALENDAR_SPECS

    assert len(CALENDAR_SPECS) == 3
    names = {s.name for s in CALENDAR_SPECS}
    assert names == {"is_holiday", "is_delivery_day", "meeting_dummy"}
    for spec in CALENDAR_SPECS:
        assert spec.source == "computed"
        assert spec.category == "calendar"
        assert spec.availability_offset == 0
        assert spec.stage == "s2"
        assert spec.compliance_flag == "ok"
        assert spec.description


# ── (b) register_calendar 注册成功，get_by_name 能取回 ──────────────

def test_register_calendar_registers_all_three():
    """register_calendar 把 3 个 spec 注册进新 Registry 实例。"""
    from predict.features.calendar import register_calendar, CALENDAR_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_calendar(registry)

    for spec in CALENDAR_SPECS:
        assert registry.get_by_name(spec.name) is spec


# ── (c) 重复注册同名 raise KeyError ─────────────────────────────────

def test_register_calendar_duplicate_raises():
    """重复注册同名 feature 时 Registry 抛 KeyError。"""
    from predict.features.calendar import register_calendar, CALENDAR_SPECS
    from predict.features.registry import Registry

    registry = Registry()
    register_calendar(registry)
    with pytest.raises(KeyError, match="already registered"):
        register_calendar(registry)


# ── (d) list_for_stage look-ahead 防护 ────────────────────────────────

def test_list_for_stage_s2_includes_all_three():
    """list_for_stage('s2') 包含全部 3 个 calendar 特征。"""
    from predict.features.calendar import register_calendar
    from predict.features.registry import Registry

    registry = Registry()
    register_calendar(registry)
    s2_names = {s.name for s in registry.list_for_stage("s2")}
    assert s2_names == {"is_holiday", "is_delivery_day", "meeting_dummy"}


def test_list_for_stage_s1_excludes_all_three():
    """list_for_stage('s1') **排除**全部 3 个（look-ahead 核心防护）。"""
    from predict.features.calendar import register_calendar
    from predict.features.registry import Registry

    registry = Registry()
    register_calendar(registry)
    s1_names = {s.name for s in registry.list_for_stage("s1")}
    assert s1_names == set()


# ── (e) is_holiday 纯函数：节假日/交易日/周末 ────────────────────────

def test_is_holiday_known_holiday_returns_true():
    """硬编码已知节假日（如 2026-01-01 元旦）返回 True。"""
    from predict.features.calendar import is_holiday

    assert is_holiday("2026-01-01") is True


def test_is_holiday_regular_trading_day_returns_false():
    """普通交易日（如 2026-07-29 周三）返回 False。"""
    from predict.features.calendar import is_holiday

    assert is_holiday("2026-07-29") is False


def test_is_holiday_weekend_returns_true():
    """周末（如 2026-08-01 周六）返回 True（非交易日视为 holiday）。"""
    from predict.features.calendar import is_holiday

    assert is_holiday("2026-08-01") is True


# ── (f) is_option_delivery_day 纯函数：交割日/非交割日 ───────────────

def test_is_option_delivery_day_fourth_wednesday():
    """每月第四个周三为 ETF 期权交割日，返回 True。"""
    from predict.features.calendar import is_option_delivery_day

    # 2026-07-22 is the 4th Wednesday of July 2026
    assert is_option_delivery_day("2026-07-22") is True


def test_is_option_delivery_day_third_friday():
    """每月第三个周五为股指期货交割日，返回 True。"""
    from predict.features.calendar import is_option_delivery_day

    # 2026-07-17 is the 3rd Friday of July 2026
    assert is_option_delivery_day("2026-07-17") is True


def test_is_option_delivery_day_regular_day_returns_false():
    """普通日既不是第四个周三也不是第三个周五，返回 False。"""
    from predict.features.calendar import is_option_delivery_day

    # 2026-07-29 is a Wednesday, not the 4th
    assert is_option_delivery_day("2026-07-29") is False


def test_is_option_delivery_day_second_wednesday():
    """每月第二个周三不是交割日，返回 False。"""
    from predict.features.calendar import is_option_delivery_day

    # 2026-07-08 is the 2nd Wednesday of July 2026
    assert is_option_delivery_day("2026-07-08") is False


def test_is_option_delivery_day_first_friday():
    """每月第一个周五不是交割日，返回 False。"""
    from predict.features.calendar import is_option_delivery_day

    # 2026-07-03 is the 1st Friday of July 2026
    assert is_option_delivery_day("2026-07-03") is False


# ── (g) is_meeting_period 纯函数：两会期间/非会议期 ──────────────────

def test_is_meeting_period_two_sessions_returns_true():
    """两会期间（如 2026-03-05）返回 True。"""
    from predict.features.calendar import is_meeting_period

    assert is_meeting_period("2026-03-05") is True


def test_is_meeting_period_central_econ_meeting_returns_true():
    """中央经济工作会议期间（如 2026-12-11）返回 True。"""
    from predict.features.calendar import is_meeting_period

    assert is_meeting_period("2026-12-11") is True


def test_is_meeting_period_non_meeting_day_returns_false():
    """非会议期（如 2026-07-15）返回 False。"""
    from predict.features.calendar import is_meeting_period

    assert is_meeting_period("2026-07-15") is False
