# -*- coding: utf-8 -*-
"""Stub: data provider base"""

from __future__ import annotations


def normalize_stock_code(code: str) -> str:
    """Normalize stock code."""
    return str(code or "").strip()
