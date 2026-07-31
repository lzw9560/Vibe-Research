# -*- coding: utf-8 -*-
"""通知模块的枚举类型。

注：``ReportType`` 在此是**通知分类**（daily/weekly/monthly/alert/system），
与 S007 ``models.enums.ReportType``（研报评级 买入/增持/中性/…）是**不同概念**，
不可合并。本文件由根 ``backend/enums.py`` 机械迁入（S008 T16 B2）。

⚠️ 已知潜在 bug（机械搬迁保留现状，留独立小 spec 修）：
``notification_report_generator`` 用 ``ReportType.BRIEF``、
``notification_formatters`` 用 ``ReportType.from_str``，但本枚举无此二成员
（既有定义仅 5 个通知分类）。这些是 notification 模块的死代码/坏路径，
搬迁不引入新 bug、也不修旧 bug。
"""

from enum import Enum


class ReportType(str, Enum):
    """报告类型（通知分类）。"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ALERT = "alert"
    SYSTEM = "system"
