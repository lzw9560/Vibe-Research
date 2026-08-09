# -*- coding: utf-8 -*-
"""R3 公告 + 板块联动（B6）。"""

from __future__ import annotations

import astock
from data.mappers import announcement_from_dict, concept_blocks_from_dict
from predict.features.fund_flow import fetch_sector_flow


# S044 R3：公告类型化——按 title 关键词机械分类（预增/重组/回购/其他），客观不含方向判断。
_ANN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("预增", ("预增", "业绩预增", "净利润预增", "扭亏", "大幅增长")),
    ("重组", ("重组", "并购", "吸收合并", "借壳", "重大资产重组")),
    ("回购", ("回购", "增持计划", "股东增持")),
)


def classify_announcement(ann: dict) -> str:
    """按 title 关键词分类公告：预增/重组/回购/其他。

    客观机械匹配（关键词命中即归类），不引入方向判断。供 R3 按类型过滤与诊断卡展示。
    缺 title / 无命中 → "其他"。
    """
    title = (ann.get("title") or "") if isinstance(ann, dict) else ""
    for type_name, keywords in _ANN_KEYWORDS:
        if any(kw in title for kw in keywords):
            return type_name
    return "其他"


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
            models = [announcement_from_dict(a) for a in anns]
            entry["announcements"] = [
                {"title": m.title, "date": m.date, "type": classify_announcement({"title": m.title})}
                for m in models
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
        try:
            sf = fetch_sector_flow(c, as_of)
            entry["sector_flow"] = sf
            if sf is None:
                entry["missing"]["sector_flow"] = "板块资金流未取得（行业/板块匹配/端点限流）"
        except Exception:
            entry["missing"]["sector_flow"] = "板块资金流取数失败"
        out[c] = entry
    return out
