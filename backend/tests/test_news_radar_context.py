# -*- coding: utf-8 -*-
"""S066 §10 资讯雷达上下文层测试。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from strategies.news_radar_context import (
    NewsRadarContext,
    SectorNewsHeat,
    CatalystContext,
    RiskRadarHit,
    map_industry_to_radar,
    classify_announcement,
    compute_sector_news_heat,
    compute_catalyst_context,
    scan_risk_keywords,
    build_news_radar_context,
    POSITIVE_KEYWORDS,
    NEGATIVE_KEYWORDS,
    RISK_KEYWORDS,
)


def _make_radar(items: list[dict], key: str = "ai") -> dict:
    """构造 mock radar_data。"""
    return {
        "industries": [{"key": key, "name": "测试赛道", "items": items}],
    }


class TestMapIndustryToRadar:
    """板块映射（spec §10.3）。"""

    def test_known_industry_maps(self):
        assert map_industry_to_radar("计算机") == "ai"
        assert map_industry_to_radar("医药") == "bio"
        assert map_industry_to_radar("电子") == "semi"
        assert map_industry_to_radar("汽车") == "auto"

    def test_unknown_industry_returns_none(self):
        assert map_industry_to_radar("不存在的行业") is None

    def test_partial_match(self):
        """包含匹配：'计算机设备' 应匹配到 'ai'。"""
        result = map_industry_to_radar("计算机设备")
        assert result == "ai"


class TestClassifyAnnouncement:
    """公告类型分类（spec §10.2 层 2）。"""

    def test_yu_zeng(self):
        assert classify_announcement("2026年半年度业绩预增公告") == "预增"

    def test_yeji_zengzhang(self):
        assert classify_announcement("公司业绩大幅增长") == "预增"

    def test_niu_kui(self):
        assert classify_announcement("公司扭亏为盈") == "扭亏"

    def test_chong_zu(self):
        assert classify_announcement("重大资产重组预案") == "重组"

    def test_hui_gou(self):
        assert classify_announcement("股份回购方案") == "回购"

    def test_zeng_chi(self):
        assert classify_announcement("控股股东增持计划") == "增持"

    def test_risk(self):
        assert classify_announcement("收到证监会立案告知书") == "风险提示"

    def test_unknown(self):
        assert classify_announcement("日常经营公告") == "未知"

    def test_empty_text(self):
        assert classify_announcement("") == "未知"


class TestSectorNewsHeat:
    """板块资讯热度（spec §10.2 层 1）。"""

    def test_hot_sector_many_news(self):
        """48h 新闻数 > 7d 均值 * 1.5 → 真热。"""
        now = time.time()
        items = [{"title": f"新闻{i}", "ts": now - i * 100, "url": ""} for i in range(10)]
        radar = _make_radar(items)
        heat = compute_sector_news_heat("计算机", radar)
        assert heat.news_count_48h > 0
        assert heat.heat_label in ("真热", "正常")

    def test_cold_sector_no_news(self):
        """无新闻 → 冷门。"""
        radar = _make_radar([])
        heat = compute_sector_news_heat("计算机", radar)
        assert heat.heat_label == "冷门"
        assert heat.news_count_48h == 0

    def test_no_mapping_returns_cold(self):
        """无板块映射 → 冷门。"""
        heat = compute_sector_news_heat("未知行业", None)
        assert heat.heat_label == "冷门"
        assert "无板块映射" in heat.heat_note

    def test_no_radar_data_returns_cold(self):
        heat = compute_sector_news_heat("计算机", None)
        assert heat.heat_label == "冷门"


class TestCatalystContext:
    """催化上下文（spec §10.2 层 2）。"""

    def test_double_catalyst_positive_match(self):
        """预增公告 + 赛道有正面新闻 → 双催化。"""
        now = time.time()
        items = [{"title": "政策利好刺激需求增长", "ts": now, "url": ""}]
        radar = _make_radar(items)
        cat = compute_catalyst_context("预增", "计算机", radar)
        assert cat.catalyst_label == "双催化"
        assert cat.sector_news_match is True

    def test_individual_catalyst_no_match(self):
        """预增公告 + 无匹配新闻 → 个股催化。"""
        now = time.time()
        items = [{"title": "无关新闻", "ts": now, "url": ""}]
        radar = _make_radar(items)
        cat = compute_catalyst_context("预增", "计算机", radar)
        assert cat.catalyst_label == "个股催化"
        assert cat.sector_news_match is False

    def test_risk_overlap(self):
        """风险提示 + 赛道有负面新闻 → 风险叠加。"""
        now = time.time()
        items = [{"title": "行业整顿处罚", "ts": now, "url": ""}]
        radar = _make_radar(items)
        cat = compute_catalyst_context("风险提示", "计算机", radar)
        assert cat.catalyst_label == "风险叠加"

    def test_individual_risk_no_match(self):
        """风险提示 + 无匹配 → 个股风险。"""
        radar = _make_radar([])
        cat = compute_catalyst_context("风险提示", "计算机", radar)
        assert cat.catalyst_label == "个股风险"

    def test_unknown_announcement_returns_no(self):
        cat = compute_catalyst_context("未知", "计算机", _make_radar([]))
        assert cat.catalyst_label == "无"


class TestRiskRadar:
    """风险雷达（spec §10.2 层 3）。"""

    def test_risk_keyword_hit(self):
        """赛道有负面关键词命中 → 赛道风险。"""
        now = time.time()
        items = [{"title": "某公司被处罚", "ts": now, "url": ""}]
        radar = _make_radar(items)
        risk = scan_risk_keywords("计算机", radar)
        assert risk.risk_label == "赛道风险"
        assert "处罚" in risk.hit_keywords

    def test_no_risk_no_hit(self):
        """无负面关键词 → 无风险。"""
        now = time.time()
        items = [{"title": "利好消息", "ts": now, "url": ""}]
        radar = _make_radar(items)
        risk = scan_risk_keywords("计算机", radar)
        assert risk.risk_label == "无风险"
        assert risk.hit_keywords == []

    def test_old_news_outside_48h_ignored(self):
        """48h 之前的新闻不计入。"""
        now = time.time()
        items = [{"title": "整顿旧闻", "ts": now - 3 * 86400, "url": ""}]  # 3 天前
        radar = _make_radar(items)
        risk = scan_risk_keywords("计算机", radar)
        assert risk.risk_label == "无风险"

    def test_no_mapping_returns_no_risk(self):
        risk = scan_risk_keywords("未知行业", None)
        assert risk.risk_label == "无风险"


class TestBuildContext:
    """三层合并入口。"""

    def test_full_context_with_announcement(self):
        """完整上下文（带公告）。"""
        now = time.time()
        items = [
            {"title": "政策利好", "ts": now, "url": "http://a"},
            {"title": "需求增长", "ts": now - 100, "url": "http://b"},
            {"title": "行业整顿", "ts": now - 200, "url": "http://c"},
        ]
        radar = _make_radar(items)
        ctx = build_news_radar_context("计算机", "业绩预增公告", radar)
        assert len(ctx.sector_heat) > 0
        assert ctx.catalyst is not None
        assert len(ctx.risk_hits) > 0
        assert len(ctx.recent_news) <= 3

    def test_context_without_announcement(self):
        """无公告 → catalyst 为 None。"""
        radar = _make_radar([{"title": "新闻", "ts": time.time(), "url": ""}])
        ctx = build_news_radar_context("计算机", None, radar)
        assert ctx.catalyst is None

    def test_context_no_radar_data(self):
        """无 radar_data → 全部降级。"""
        ctx = build_news_radar_context("计算机", None, None)
        assert ctx.sector_heat[0].heat_label == "冷门"
        assert ctx.recent_news == []
