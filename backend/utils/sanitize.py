# -*- coding: utf-8 -*-
"""文本 sanitize 工具"""

from __future__ import annotations


def sanitize_diagnostic_text(text: str) -> str:
    """Sanitize diagnostic text for safe logging."""
    if not text:
        return ""
    return text.replace("\n", " ").replace("\r", " ")[:500]
