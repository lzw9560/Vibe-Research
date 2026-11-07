# -*- coding: utf-8 -*-
"""数据处理工具"""

from __future__ import annotations



def normalize_model_used(value: str) -> str:
    """Normalize model name."""
    return str(value or "").strip()
