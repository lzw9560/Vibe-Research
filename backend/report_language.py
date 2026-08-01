# -*- coding: utf-8 -*-
"""报告语言本地化工具"""

from __future__ import annotations

from typing import Optional


def normalize_report_language(value: Optional[str]) -> str:
    """Normalize report language code."""
    if not value:
        return "zh"
    return str(value).strip().lower()


def get_report_labels(report_type: Optional[str]) -> dict[str, str]:
    """Get localized report labels."""
    return {
        "title": "股票分析报告",
        "date": "日期",
        "summary": "摘要",
    }


def get_signal_level(score: Optional[float]) -> str:
    """Get signal level label from score."""
    if score is None:
        return "未知"
    if score >= 80:
        return "强烈看多"
    if score >= 60:
        return "看多"
    if score >= 40:
        return "中性"
    if score >= 20:
        return "看空"
    return "强烈看空"


def get_localized_stock_name(code: Optional[str]) -> str:
    """Get localized stock name."""
    return str(code or "").strip()


def localize_operation_advice(advice: Optional[str]) -> str:
    """Localize operation advice."""
    return str(advice or "").strip()


def localize_trend_prediction(trend: Optional[str]) -> str:
    """Localize trend prediction."""
    return str(trend or "").strip()


def localize_chip_health(health: Optional[str]) -> str:
    """Localize chip health."""
    return str(health or "").strip()


def get_chip_unavailable_reason(reason: Optional[str]) -> str:
    """Get chip unavailable reason."""
    return str(reason or "数据不可用").strip()


def is_chip_structure_unavailable(structure: Optional[str]) -> bool:
    """Check if chip structure is unavailable."""
    return not structure or str(structure).strip() in ("", "unknown", "none")
