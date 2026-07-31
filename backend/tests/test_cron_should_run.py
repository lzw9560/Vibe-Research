# -*- coding: utf-8 -*-
"""CronScheduler._should_run / cron_match 单测（S011-A R1）。

覆盖 cron 5 段匹配：``*`` / 单值 / ``*/n`` 步进 / ``a-b`` 范围 /
``a-b/n`` 范围步进 / 逗号 OR / 边界 / 非法输入。不引入 APScheduler。

参考约定：weekday 用 Python ``datetime.weekday()`` —— 0=周一..6=周日。
"""

import pytest
from datetime import datetime

from scheduled_tasks import ScheduledTask, cron_match


def _m(minute, hour=10, day=1, month=1, year=2024):
    """便捷构造：默认 2024-01-01（周一）某时某分。"""
    return datetime(year, month, day, hour, minute)


# 2024-01-01 是周一（weekday=0）；2024-01-06 是周六（weekday=5）
MON_1530 = datetime(2024, 1, 1, 15, 30)
MON_0000 = datetime(2024, 1, 1, 0, 0)
SAT_0000 = datetime(2024, 1, 6, 0, 0)


# ---------------------------------------------------------------------------
# 通配 *
class TestStar:
    def test_star_all_matches(self):
        assert cron_match("* * * * *", MON_1530) is True

    def test_star_matches_every_minute(self):
        for m in (0, 15, 30, 45, 59):
            assert cron_match("* * * * *", _m(m)) is True


# ---------------------------------------------------------------------------
# 单值
class TestSingleValue:
    def test_exact_minute_hour(self):
        assert cron_match("30 15 * * *", MON_1530) is True

    def test_wrong_minute(self):
        assert cron_match("29 15 * * *", MON_1530) is False

    def test_wrong_hour(self):
        assert cron_match("30 16 * * *", MON_1530) is False

    def test_month_field(self):
        assert cron_match("30 15 1 1 *", MON_1530) is True
        assert cron_match("30 15 1 2 *", MON_1530) is False

    def test_day_field(self):
        assert cron_match("30 15 1 * *", MON_1530) is True
        assert cron_match("30 15 2 * *", MON_1530) is False


# ---------------------------------------------------------------------------
# */n 步进
class TestStep:
    def test_every_15_min_hits(self):
        for m in (0, 15, 30, 45):
            assert cron_match("*/15 * * * *", _m(m)) is True

    def test_every_15_min_miss(self):
        for m in (1, 7, 14, 16, 29, 31, 44, 46, 59):
            assert cron_match("*/15 * * * *", _m(m)) is False

    def test_step_one_equals_star(self):
        assert cron_match("*/1 * * * *", MON_1530) is True

    def test_step_zero_invalid(self):
        assert cron_match("*/0 * * * *", MON_1530) is False

    def test_step_nonnumeric_invalid(self):
        assert cron_match("*/x * * * *", MON_1530) is False

    def test_hour_step(self):
        assert cron_match("0 */6 * * *", datetime(2024, 1, 1, 6, 0)) is True
        assert cron_match("0 */6 * * *", datetime(2024, 1, 1, 7, 0)) is False


# ---------------------------------------------------------------------------
# 范围 a-b
class TestRange:
    def test_weekday_range_mon_fri(self):
        # 0-4 = 周一..周五
        assert cron_match("0 0 * * 0-4", MON_0000) is True   # 周一
        assert cron_match("0 0 * * 0-4", SAT_0000) is False  # 周六

    def test_weekday_range_tue_sat(self):
        # 1-5 = 周二..周六
        assert cron_match("0 0 * * 1-5", MON_0000) is False  # 周一不在
        assert cron_match("0 0 * * 1-5", SAT_0000) is True    # 周六在

    def test_minute_range_inclusive_bounds(self):
        assert cron_match("10-20 * * * *", _m(10)) is True
        assert cron_match("10-20 * * * *", _m(20)) is True
        assert cron_match("10-20 * * * *", _m(9)) is False
        assert cron_match("10-20 * * * *", _m(21)) is False


# ---------------------------------------------------------------------------
# 范围步进 a-b/n
class TestRangeStep:
    def test_10_20_step_5(self):
        assert cron_match("10-20/5 * * * *", _m(10)) is True
        assert cron_match("10-20/5 * * * *", _m(15)) is True
        assert cron_match("10-20/5 * * * *", _m(20)) is True
        assert cron_match("10-20/5 * * * *", _m(5)) is False
        assert cron_match("10-20/5 * * * *", _m(25)) is False

    def test_0_59_step_30(self):
        assert cron_match("0-59/30 * * * *", _m(0)) is True
        assert cron_match("0-59/30 * * * *", _m(30)) is True
        assert cron_match("0-59/30 * * * *", _m(15)) is False


# ---------------------------------------------------------------------------
# 逗号 OR
class TestComma:
    def test_two_minutes(self):
        assert cron_match("0,30 * * * *", _m(0)) is True
        assert cron_match("0,30 * * * *", _m(30)) is True
        assert cron_match("0,30 * * * *", _m(15)) is False

    def test_comma_with_range(self):
        # 0-30 或 45
        assert cron_match("0-30,45 * * * *", _m(15)) is True
        assert cron_match("0-30,45 * * * *", _m(45)) is True
        assert cron_match("0-30,45 * * * *", _m(31)) is False
        assert cron_match("0-30,45 * * * *", _m(46)) is False

    def test_comma_weekday(self):
        # 周一(0) 或 周六(5)
        TUE = datetime(2024, 1, 2, 0, 0)  # weekday=1
        assert cron_match("0 0 * * 0,5", MON_0000) is True
        assert cron_match("0 0 * * 0,5", SAT_0000) is True
        assert cron_match("0 0 * * 0,5", TUE) is False


# ---------------------------------------------------------------------------
# 边界
class TestBoundary:
    def test_minute_bounds(self):
        assert cron_match("0 * * * *", _m(0)) is True
        assert cron_match("59 * * * *", _m(59)) is True
        assert cron_match("59 * * * *", _m(0)) is False

    def test_hour_bounds(self):
        assert cron_match("0 0 * * *", datetime(2024, 1, 1, 0, 0)) is True
        assert cron_match("0 23 * * *", datetime(2024, 1, 1, 23, 0)) is True
        assert cron_match("0 23 * * *", datetime(2024, 1, 1, 0, 0)) is False

    def test_day_bound(self):
        assert cron_match("0 0 1 * *", datetime(2024, 1, 1, 0, 0)) is True
        assert cron_match("0 0 31 * *", datetime(2024, 1, 31, 0, 0)) is True

    def test_month_bound(self):
        assert cron_match("0 0 1 1 *", datetime(2024, 1, 1, 0, 0)) is True
        assert cron_match("0 0 1 12 *", datetime(2024, 12, 1, 0, 0)) is True


# ---------------------------------------------------------------------------
# 非法 / 容错
class TestInvalid:
    def test_too_few_fields(self):
        assert cron_match("* * * *", MON_1530) is False

    def test_too_many_fields(self):
        assert cron_match("* * * * * *", MON_1530) is False

    def test_empty(self):
        assert cron_match("", MON_1530) is False

    def test_whitespace_collapsed(self):
        # 双空格仍应解析为 5 段（str.split() 折叠空白）
        assert cron_match("30  15 * * *", MON_1530) is True

    def test_garbage_field(self):
        assert cron_match("abc * * * *", MON_1530) is False


# ---------------------------------------------------------------------------
# CronScheduler._should_run 委托 cron_match
class TestShouldRun:
    def test_should_run_star(self, cron_scheduler):
        task = ScheduledTask(cron_expr="* * * * *")
        assert cron_scheduler._should_run(task, MON_1530) is True

    def test_should_run_exact(self, cron_scheduler):
        task = ScheduledTask(cron_expr="0 0 * * *")
        assert cron_scheduler._should_run(task, datetime(2024, 1, 1, 0, 0)) is True
        assert cron_scheduler._should_run(task, MON_1530) is False

    def test_should_run_step(self, cron_scheduler):
        task = ScheduledTask(cron_expr="*/30 * * * *")
        assert cron_scheduler._should_run(task, _m(0)) is True
        assert cron_scheduler._should_run(task, _m(30)) is True
        assert cron_scheduler._should_run(task, _m(7)) is False

    def test_should_run_range(self, cron_scheduler):
        task = ScheduledTask(cron_expr="0 0 * * 0-4")
        assert cron_scheduler._should_run(task, MON_0000) is True
        assert cron_scheduler._should_run(task, SAT_0000) is False
