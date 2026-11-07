# -*- coding: utf-8 -*-
"""数据处理工具"""

from __future__ import annotations

from utils.safe_convert import safe_float as _safe_float  # P2 DRY: 统一 safe_float


def normalize_model_used(value: str) -> str:
    """Normalize model name."""
    return str(value or "").strip()
