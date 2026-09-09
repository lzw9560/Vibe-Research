# -*- coding: utf-8 -*-
"""安全类型转换工具（P2 DRY：抽 _safe_float 26 处→1）。

统一 float 转换逻辑：处理 None / int/float / "3.2%" / "1,234" 等形状。
default 参数控制失败行为：None→返 None（notification 用），0.0→返 0.0（data_processing 用）。
"""
from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float | None = None) -> float | None:
    """Best-effort float conversion; handles ``"3.2%"`` and ``"1,234"`` shapes.

    Args:
        value: 输入值（None / int / float / str）。
        default: 失败时返回值（None=返 None，0.0=返 0.0）。

    Returns:
        float 或 default。处理百分号（去 %）、千分号（去 ,）、空串。
    """
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
