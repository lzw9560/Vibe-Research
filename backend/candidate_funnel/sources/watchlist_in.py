# -*- coding: utf-8 -*-
"""自选/手动并行通道（B7）。接 routers/watchlist。"""

from __future__ import annotations


def get_watchlist_codes() -> list[str]:
    """返回用户自选股代码清单；取不到返回 []。"""
    try:
        from routers import watchlist
        data = watchlist.watchlist_get() or {}
        codes = data.get("codes") or []
        return list(dict.fromkeys(c for c in codes if c))
    except Exception:
        return []
