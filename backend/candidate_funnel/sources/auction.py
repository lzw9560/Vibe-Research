# -*- coding: utf-8 -*-
"""R3 集合竞价异动（B5）。复用 auction_screener。"""

from __future__ import annotations

import astock  # noqa: F401


def fetch_auction(date: str) -> dict[str, dict]:
    """返回 {code: {name, auction_open_pct}}。取不到返回 {}。"""
    try:
        import auction_screener as asc
        result = asc.get_screener().analyze(date)
    except Exception:
        return {}

    items = getattr(result, "candidates", None)
    if items is None:
        items = result if isinstance(result, list) else []
    out: dict[str, dict] = {}
    for it in items:
        if isinstance(it, dict):
            code = it.get("code")
            name = it.get("name")
            open_pct = it.get("open_pct") or it.get("auction_open_pct")
        else:
            code = getattr(it, "code", None)
            name = getattr(it, "name", None)
            open_pct = getattr(it, "open_pct", None) or getattr(it, "auction_open_pct", None)
        if not code:
            continue
        out[code] = {"name": name, "auction_open_pct": open_pct}
    return out
