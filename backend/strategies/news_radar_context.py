# -*- coding: utf-8 -*-
"""S066 §10 资讯雷达上下文层——板块资讯热度 + 催化上下文 + 风险雷达关键词命中。

spec §10 定位：资讯雷达是**定性上下文层**，不是量化因子。
- 不参与策略分计算，在量化因子之上提供人机协作的研判信息
- 三层接入（§10.2）：
  1. 板块资讯热度（半量化，辅助板块热度过滤）
  2. 催化上下文（定性，辅助 R3 催化判断）
  3. 风险雷达（定性，辅助风险标注）

数据源（spec §10.5）：
- 个股新闻主源：akshare stock_news_em()（已有 akshare_src.stock_news）
- 板块新闻源：newsradar RSS（已有 newsradar.get_radar）
- 板块映射：backend/data/sector_mapping.json（雷达赛道→东财行业）

不做 NLP 情感分析引擎（spec §10.6）——用 LLM API 替代（走 chat 层）。
关键词匹配做粗筛，LLM 做精细分类（利好/利空/风险提示）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "sector_mapping.json"
_MAPPING_CACHE: dict | None = None

# 关键词词库（spec §10.2 层 2/3）
POSITIVE_KEYWORDS = ["预增", "扭亏", "重组", "回购", "增持", "补贴", "政策利好", "需求增长", "突破"]
NEGATIVE_KEYWORDS = ["整顿", "处罚", "违规", "下降", "亏损", "减持", "解禁", "风险", "问询", "立案"]
RISK_KEYWORDS = ["整顿", "处罚", "违规", "下降", "亏损", "减持", "解禁", "风险", "问询", "立案", "退市", "爆雷"]


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass(frozen=True)
class SectorNewsHeat:
    """板块资讯热度（spec §10.2 层 1）。"""
    sector_name: str
    news_count_48h: int
    avg_count_7d: float
    heat_label: str          # 真热 / 情绪 / 事件 / 冷门
    heat_note: str = ""


@dataclass(frozen=True)
class CatalystContext:
    """催化上下文（spec §10.2 层 2）。"""
    announcement_type: str   # 公告类型（预增/扭亏/重组/回购/风险提示）
    sector_news_match: bool  # 对应赛道是否有相关新闻
    catalyst_label: str      # 双催化 / 风险叠加 / 个股催化 / 无
    matched_headlines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskRadarHit:
    """风险雷达命中（spec §10.2 层 3）。"""
    sector_name: str
    hit_keywords: list[str]
    risk_label: str          # 赛道风险 / 无风险
    matched_headlines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NewsRadarContext:
    """资讯雷达完整上下文（三层合并）。"""
    sector_heat: list[SectorNewsHeat]
    catalyst: CatalystContext | None
    risk_hits: list[RiskRadarHit]
    recent_news: list[dict]  # 最近 3 条相关新闻


# ===========================================================================
# 板块映射
# ===========================================================================

def _load_mapping() -> dict:
    """加载雷达赛道→东财行业映射表。"""
    global _MAPPING_CACHE
    if _MAPPING_CACHE is not None:
        return _MAPPING_CACHE
    try:
        _MAPPING_CACHE = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
    except Exception:
        _MAPPING_CACHE = {}
    return _MAPPING_CACHE


def map_industry_to_radar(industry_name: str) -> str | None:
    """东财行业名 → 雷达赛道 key。无匹配返 None。"""
    mapping = _load_mapping().get("mappings", {})
    for radar_key, info in mapping.items():
        em_industries = info.get("eastmoney_industries", [])
        for em_name in em_industries:
            if em_name in industry_name or industry_name in em_name:
                return radar_key
    return None


# ===========================================================================
# 层 1：板块资讯热度（spec §10.2）
# ===========================================================================

def compute_sector_news_heat(
    sector_name: str,
    radar_data: dict | None = None,
    recent_news: list[dict] | None = None,
) -> SectorNewsHeat:
    """计算板块资讯热度。

    新闻条数阈值：取最近 7 日各板块平均新闻条数，
    超过均值 * 1.5 = "多"，低于均值 * 0.5 = "少"。

    radar_data: newsradar.get_radar() 返回的 12 赛道数据
    recent_news: 个股新闻列表（akshare stock_news）
    """
    radar_key = map_industry_to_radar(sector_name)
    if not radar_key or not radar_data:
        return SectorNewsHeat(
            sector_name=sector_name, news_count_48h=0, avg_count_7d=0.0,
            heat_label="冷门", heat_note="无板块映射或无资讯数据",
        )

    # 从 radar_data 找对应赛道的新闻数
    industries = radar_data.get("industries", [])
    target_ind = next((i for i in industries if i.get("key") == radar_key), None)
    if not target_ind:
        return SectorNewsHeat(
            sector_name=sector_name, news_count_48h=0, avg_count_7d=0.0,
            heat_label="冷门", heat_note="赛道无资讯",
        )

    items = target_ind.get("items", [])
    now = datetime.now()
    cutoff_48h = now - timedelta(hours=48)
    cutoff_7d = now - timedelta(days=7)

    count_48h = 0
    count_7d = 0
    for item in items:
        ts = item.get("ts", 0)
        if ts > 0:
            item_dt = datetime.fromtimestamp(ts)
            if item_dt > cutoff_48h:
                count_48h += 1
            if item_dt > cutoff_7d:
                count_7d += 1

    # 7 日日均
    avg_7d = count_7d / 7.0 if count_7d > 0 else 0.0

    # 热度标签（spec §10.2 层 1）
    if count_48h > avg_7d * 1.5 and avg_7d > 0:
        heat_label = "真热"
        note = "新闻多——有基本面驱动"
    elif count_48h < avg_7d * 0.5 and avg_7d > 0:
        heat_label = "情绪"
        note = "新闻少——可能纯情绪炒作"
    elif count_48h == 0:
        heat_label = "冷门"
        note = "无板块资讯"
    else:
        heat_label = "正常"
        note = "资讯热度正常"

    return SectorNewsHeat(
        sector_name=sector_name,
        news_count_48h=count_48h,
        avg_count_7d=round(avg_7d, 2),
        heat_label=heat_label,
        heat_note=note,
    )


# ===========================================================================
# 层 2：催化上下文（spec §10.2）
# ===========================================================================

def classify_announcement(announcement_text: str) -> str:
    """公告类型分类（关键词粗筛，spec §10.2 层 2）。

    返回：预增 / 扭亏 / 重组 / 回购 / 增持 / 风险提示 / 未知
    """
    if not announcement_text:
        return "未知"
    text = announcement_text.lower()
    for kw in ["预增", "业绩增长", "大幅增长"]:
        if kw in text:
            return "预增"
    for kw in ["扭亏", "摘帽"]:
        if kw in text:
            return "扭亏"
    for kw in ["重组", "并购", "吸收合并"]:
        if kw in text:
            return "重组"
    for kw in ["回购", "股份回购"]:
        if kw in text:
            return "回购"
    for kw in ["增持", "股东增持"]:
        if kw in text:
            return "增持"
    for kw in ["风险提示", "问询", "立案", "违规", "退市"]:
        if kw in text:
            return "风险提示"
    return "未知"


def compute_catalyst_context(
    announcement_type: str,
    sector_name: str,
    radar_data: dict | None = None,
) -> CatalystContext:
    """催化上下文（spec §10.2 层 2）。

    公告类型 × 赛道新闻匹配 → 催化标签。
    - 预增 + 赛道政策利好新闻 → 双催化
    - 风险提示 + 赛道监管收紧新闻 → 风险叠加
    - 预增 + 无相关新闻 → 个股催化
    """
    radar_key = map_industry_to_radar(sector_name)
    matched_headlines: list[str] = []

    if radar_key and radar_data:
        industries = radar_data.get("industries", [])
        target_ind = next((i for i in industries if i.get("key") == radar_key), None)
        if target_ind:
            items = target_ind.get("items", [])[:20]
            for item in items:
                title = item.get("title", "")
                if _matches_announcement_type(announcement_type, title):
                    matched_headlines.append(title)

    sector_match = len(matched_headlines) > 0

    # 催化标签
    if announcement_type in ("预增", "扭亏", "重组", "回购", "增持") and sector_match:
        label = "双催化"
    elif announcement_type == "风险提示" and sector_match:
        label = "风险叠加"
    elif announcement_type in ("预增", "扭亏", "重组", "回购", "增持"):
        label = "个股催化"
    elif announcement_type == "风险提示":
        label = "个股风险"
    else:
        label = "无"

    return CatalystContext(
        announcement_type=announcement_type,
        sector_news_match=sector_match,
        catalyst_label=label,
        matched_headlines=matched_headlines[:3],
    )


def _matches_announcement_type(ann_type: str, title: str) -> bool:
    """新闻标题是否匹配公告类型（粗筛）。

    正面公告（预增/扭亏/重组/回购/增持）→ 匹配正面关键词
    风险公告 → 匹配风险关键词
    """
    if not title:
        return False
    if ann_type in ("预增", "扭亏", "重组", "回购", "增持"):
        return any(kw in title for kw in POSITIVE_KEYWORDS)
    if ann_type == "风险提示":
        return any(kw in title for kw in RISK_KEYWORDS[:5])
    return False


# ===========================================================================
# 层 3：风险雷达（spec §10.2）
# ===========================================================================

def scan_risk_keywords(
    sector_name: str,
    radar_data: dict | None = None,
) -> RiskRadarHit:
    """风险雷达关键词命中（spec §10.2 层 3）。

    检查候选股所在赛道最近 48h 是否有负面新闻关键词命中。
    """
    radar_key = map_industry_to_radar(sector_name)
    if not radar_key or not radar_data:
        return RiskRadarHit(
            sector_name=sector_name, hit_keywords=[],
            risk_label="无风险", matched_headlines=[],
        )

    industries = radar_data.get("industries", [])
    target_ind = next((i for i in industries if i.get("key") == radar_key), None)
    if not target_ind:
        return RiskRadarHit(
            sector_name=sector_name, hit_keywords=[],
            risk_label="无风险", matched_headlines=[],
        )

    now = datetime.now()
    cutoff_48h = now - timedelta(hours=48)
    items = target_ind.get("items", [])

    hit_kws: set[str] = set()
    matched: list[str] = []
    for item in items:
        ts = item.get("ts", 0)
        if ts > 0:
            item_dt = datetime.fromtimestamp(ts)
            if item_dt < cutoff_48h:
                continue
        title = item.get("title", "")
        for kw in RISK_KEYWORDS:
            if kw in title:
                hit_kws.add(kw)
                if title not in matched:
                    matched.append(title)

    return RiskRadarHit(
        sector_name=sector_name,
        hit_keywords=sorted(hit_kws),
        risk_label="赛道风险" if hit_kws else "无风险",
        matched_headlines=matched[:3],
    )


# ===========================================================================
# 三层合并入口
# ===========================================================================

def build_news_radar_context(
    sector_name: str,
    announcement_text: str | None = None,
    radar_data: dict | None = None,
    recent_news: list[dict] | None = None,
) -> NewsRadarContext:
    """资讯雷达三层合并上下文。

    sector_name: 候选股所在板块（东财行业名）
    announcement_text: 公告文本（如有）
    radar_data: newsradar.get_radar() 返回
    recent_news: 个股新闻列表
    """
    heat = compute_sector_news_heat(sector_name, radar_data, recent_news)

    catalyst = None
    if announcement_text:
        ann_type = classify_announcement(announcement_text)
        catalyst = compute_catalyst_context(ann_type, sector_name, radar_data)

    risk = scan_risk_keywords(sector_name, radar_data)

    # 最近 3 条相关新闻
    recent_3: list[dict] = []
    radar_key = map_industry_to_radar(sector_name)
    if radar_key and radar_data:
        industries = radar_data.get("industries", [])
        target_ind = next((i for i in industries if i.get("key") == radar_key), None)
        if target_ind:
            recent_3 = [
                {"title": item.get("title", ""), "url": item.get("url", ""), "time": item.get("time", "")}
                for item in target_ind.get("items", [])[:3]
            ]

    return NewsRadarContext(
        sector_heat=[heat],
        catalyst=catalyst,
        risk_hits=[risk],
        recent_news=recent_3,
    )
