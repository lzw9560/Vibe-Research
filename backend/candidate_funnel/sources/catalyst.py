# -*- coding: utf-8 -*-
"""R3 公告 + 板块联动（B6）。"""

from __future__ import annotations

import astock


def fetch_catalyst(codes: list[str], as_of: str) -> dict[str, dict]:
    """返回 {code: {announcements, concepts, sector_flow, missing?}}。"""
    out: dict[str, dict] = {}
    for c in codes:
        entry: dict = {"announcements": [], "concepts": [], "sector_flow": None, "missing": {}}
        try:
            anns = astock.announcements(c, limit=10) or []
            entry["announcements"] = [
                {"title": a.get("title"), "date": a.get("date"), "type": a.get("type")}
                for a in anns
            ]
            if not entry["announcements"]:
                entry["missing"]["announcements"] = "近期无公告"
        except Exception:
            entry["missing"]["announcements"] = "公告未取得"
        try:
            cb = astock.concept_blocks(c) or {}
            entry["concepts"] = [
                b.get("name") for b in cb.get("boards", []) if b.get("name")
            ]
        except Exception:
            entry["missing"]["concepts"] = "板块未取得"
        out[c] = entry
    return out
