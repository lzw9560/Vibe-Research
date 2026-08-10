# -*- coding: utf-8 -*-
"""S045：漏斗层 passed 补分——R1/R2/R3 gene_score + R3 matched_triggers（得分显示/排序/多选筛选的数据基础）。"""
import pytest

from candidate_funnel import funnel, sources
from candidate_funnel.models import ThresholdConfig


class TestR3Triggers:
    """_r3_triggers 纯函数：与 _filter_r3 判定一致的触发类型派生。"""

    def test_三触发齐全(self):
        auction = {"000001": {"auction_open_pct": 2.0}}
        catalyst = {"000001": {"announcements": [{"title": "回购"}], "concepts": ["新能源"]}}
        assert funnel._r3_triggers("000001", auction, catalyst) == ["竞价异动", "公告催化", "概念联动"]

    def test_仅概念联动(self):
        catalyst = {"000002": {"announcements": [], "concepts": ["AI"]}}
        assert funnel._r3_triggers("000002", {}, catalyst) == ["概念联动"]

    def test_仅公告催化(self):
        catalyst = {"000003": {"announcements": [{"title": "业绩预增"}], "concepts": []}}
        assert funnel._r3_triggers("000003", {}, catalyst) == ["公告催化"]

    def test_仅竞价异动(self):
        auction = {"000004": {"auction_open_pct": 3.5}}
        assert funnel._r3_triggers("000004", auction, {"000004": {"announcements": [], "concepts": []}}) == ["竞价异动"]

    def test_无触发返空(self):
        assert funnel._r3_triggers("999999", {}, {}) == []


@pytest.fixture
def mock_sources(monkeypatch):
    genes = {
        "000001": {"name": "平安银行", "gene_score": 52.17},
        "000002": {"name": "万科A", "gene_score": 50.38},
    }
    monkeypatch.setattr(sources.gene, "fetch_genes", lambda date: genes)
    monkeypatch.setattr(sources.board_ladder, "fetch_board_ladder", lambda date: {})
    monkeypatch.setattr(
        sources.activity, "fetch_activity",
        lambda codes, date: {c: {"name": genes[c]["name"], "turnover_pct": 15.0} for c in codes},
    )
    monkeypatch.setattr(sources.fund_flow, "fetch_fund_flow", lambda codes, date: {c: {} for c in codes})
    monkeypatch.setattr(sources.auction, "fetch_auction", lambda date: {"000001": {"auction_open_pct": 2.0}})
    monkeypatch.setattr(
        sources.catalyst, "fetch_catalyst",
        lambda codes, date: {
            c: {"announcements": [{"title": "回购", "date": "2026-08-10"}], "concepts": [], "sector_flow": None}
            for c in codes
        },
    )
    monkeypatch.setattr(sources.watchlist_in, "get_watchlist_codes", lambda: [])
    monkeypatch.setattr(funnel, "_fetch_sentiment_phase", lambda date: None)
    return genes


def test_run_funnel_r1r2_passed_带gene_score(mock_sources):
    result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
    layers = {l.layer_id: l for l in result.layers}
    for lid in ("R1", "R2"):
        assert layers[lid].passed, f"{lid} passed 不应为空"
        for p in layers[lid].passed:
            assert p["gene_score"] == mock_sources[p["code"]]["gene_score"]


def test_run_funnel_r3_passed_带gene_score和matched_triggers(mock_sources):
    result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
    layers = {l.layer_id: l for l in result.layers}
    r3_by_code = {p["code"]: p for p in layers["R3"].passed}
    assert r3_by_code, "R3 passed 不应为空"
    # 000001 有竞价 + 公告 → 两触发
    assert r3_by_code["000001"]["gene_score"] == 52.17
    assert set(r3_by_code["000001"]["matched_triggers"]) == {"竞价异动", "公告催化"}
    # 000002 仅公告 → 单触发
    assert r3_by_code["000002"]["gene_score"] == 50.38
    assert r3_by_code["000002"]["matched_triggers"] == ["公告催化"]
