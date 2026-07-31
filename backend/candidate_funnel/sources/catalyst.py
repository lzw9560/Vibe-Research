# -*- coding: utf-8 -*-
"""R3 公告 + 板块联动（B6）。"""

from __future__ import annotations

import astock
from data.mappers import announcement_from_dict, concept_blocks_from_dict


def fetch_catalyst(codes: list[str], as_of: str) -> dict[str, dict]:
    """返回 {code: {announcements, concepts, sector_flow, missing?}}。

    读侧经 mapper 拿 Announcement / ConceptBlock 模型，输出 dict shape 保持不变
    （下游 candidate_funnel/funnel 依赖此 shape，本轮不迁下游）。
    """
    out: dict[str, dict] = {}
    for c in codes:
        entry: dict = {"announcements": [], "concepts": [], "sector_flow": None, "missing": {}}
        try:
            anns = astock.announcements(c, limit=10) or []
            entry["announcements"] = [
                {"title": a.title, "date": a.date, "type": a.type}
                for a in (announcement_from_dict(a) for a in anns)
            ]
            if not entry["announcements"]:
                entry["missing"]["announcements"] = "近期无公告"
        except Exception:
            entry["missing"]["announcements"] = "公告未取得"
        try:
            cb = astock.concept_blocks(c) or {}
            entry["concepts"] = [
                b.name for b in concept_blocks_from_dict(cb) if b.name
            ]
        except Exception:
            entry["missing"]["concepts"] = "板块未取得"
        out[c] = entry
    return out
