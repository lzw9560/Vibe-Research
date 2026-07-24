# -*- coding: utf-8 -*-
"""Stub: history comparison service"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def get_signal_changes_batch(
    codes: List[str],
    limit: int = 5,
    exclude_query_ids: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Stub implementation."""
    return {code: [] for code in codes}
