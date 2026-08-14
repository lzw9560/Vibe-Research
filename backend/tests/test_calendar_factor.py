# -*- coding: utf-8 -*-
"""S066 §6 日历因子测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.calendar_factor import (
    calendar_factor,
    is_pre_holiday_last_day,
    is_post_holiday_first_day,
    is_pre_holiday,
    post_holiday_confirmation,
)


class TestCalendarFactor:
    """日历因子仓位乘数。"""

    def test_friday_reduces_position(self):
        """周五 ×0.7（周末 gap 风险）。2026-08-14 是周五。"""
        mult, reason = calendar_factor("2026-08-14")
        assert mult == 0.7
        assert "周五" in reason

    def test_thursday_no_reduction(self):
        """周四 ×1.0（逆势涨停=强信号，不降仓）。2026-08-13 是周四。"""
        mult, reason = calendar_factor("2026-08-13")
        assert mult == 1.0
        assert "周四" in reason

    def test_pre_holiday_last_day_max_reduction(self):
        """节前最后交易日 ×0.3（最高优先级）。2026-02-13 是春节前最后交易日。"""
        mult, reason = calendar_factor("2026-02-13")
        assert mult == 0.3
        assert "节前" in reason

    def test_pre_holiday_3days_reduction(self):
        """节前 3 日内 ×0.5。2026-02-10 在春节前 3 日内（末日 02-13）。"""
        mult, reason = calendar_factor("2026-02-10")
        assert mult == 0.5
        assert "节前" in reason

    def test_normal_day_no_reduction(self):
        """普通交易日 ×1.0。2026-08-12 是周二。"""
        mult, reason = calendar_factor("2026-08-12")
        assert mult == 1.0
        assert reason == ""

    def test_pre_holiday_last_day_priority_over_friday(self):
        """节前末日优先级高于周五（min 取更保守）。2026-01-01 是元旦末日也是周四。"""
        # 2026-01-01 在 pre_holiday_last_trading_day 列表
        mult, _ = calendar_factor("2026-01-01")
        assert mult == 0.3  # 节前末日 ×0.3，不是周四 ×1.0

    def test_is_pre_holiday_last_day_true(self):
        assert is_pre_holiday_last_day("2026-02-13") is True

    def test_is_pre_holiday_last_day_false(self):
        assert is_pre_holiday_last_day("2026-08-14") is False

    def test_is_post_holiday_first_day_true(self):
        assert is_post_holiday_first_day("2026-02-23") is True

    def test_is_post_holiday_first_day_false(self):
        assert is_post_holiday_first_day("2026-08-14") is False

    def test_is_pre_holiday_within_3_days(self):
        """2026-02-11 在春节末日 02-13 前 2 天。"""
        assert is_pre_holiday("2026-02-11", days=3) is True

    def test_is_pre_holiday_outside_range(self):
        """2026-08-01 不在任何节前 3 日内。"""
        assert is_pre_holiday("2026-08-01", days=3) is False


class TestPostHolidayConfirmation:
    """节后红包确认策略。"""

    def test_red_envelope_high_open(self):
        """跳空高开 > 3% → 红包确认信号，仓位 0.6。"""
        signal, mult, reason = post_holiday_confirmation(10.3, 10.0)
        assert signal == "red_envelope"
        assert mult == 0.6
        assert "红包" in reason

    def test_capital_flight_low_open(self):
        """跳空低开 > 2% → 资金出逃，清退（仓位 0）。"""
        signal, mult, reason = post_holiday_confirmation(9.7, 10.0)
        assert signal == "capital_flight"
        assert mult == 0.0
        assert "出逃" in reason

    def test_normal_small_gap(self):
        """小 gap → 正常处理，仓位 ×0.5。"""
        signal, mult, reason = post_holiday_confirmation(10.1, 10.0)
        assert signal == "normal"
        assert mult == 0.5

    def test_no_prev_close_reference(self):
        """无前收盘参考 → 正常 ×0.5。"""
        signal, mult, _ = post_holiday_confirmation(10.0, 0.0)
        assert signal == "normal"
        assert mult == 0.5
