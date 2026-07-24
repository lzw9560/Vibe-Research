# -*- coding: utf-8 -*-
"""数据处理工具"""

from __future__ import annotations


def normalize_model_used(value: str) -> str:
    """Normalize model name."""
    return str(value or "").strip()


def _safe_float(value, default: float = 0.0) -> float:
    """Best-effort float conversion."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default
