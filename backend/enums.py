# -*- coding: utf-8 -*-
"""枚举定义"""

from enum import Enum


class ReportType(str, Enum):
    """报告类型"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ALERT = "alert"
    SYSTEM = "system"
