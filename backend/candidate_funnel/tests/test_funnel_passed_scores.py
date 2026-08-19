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
    board = {"lianban_stocks": [{"code": "000001", "boards": 2}, {"code": "000002", "boards": 1}]}
    monkeypatch.setattr(sources.gene, "fetch_genes", lambda date: genes)
    monkeypatch.setattr(sources.board_ladder, "fetch_board_ladder", lambda date: board)
    monkeypatch.setattr(
        sources.activity, "fetch_activity",
        lambda codes, date: {c: {"name": genes[c]["name"], "turnover_pct": 15.0, "vol_ratio": 1.8, "amount_yi": 12.0, "amplitude_pct": 5.0} for c in codes},
    )
    monkeypatch.setattr(sources.fund_flow, "fetch_fund_flow", lambda codes, date, sectors=None, industry_map=None: {c: {"main_net_inflow": 5000.0, "main_net_5d": 20000.0, "northbound": 800.0} for c in codes})
    monkeypatch.setattr(sources.auction, "fetch_auction", lambda date: {"000001": {"auction_open_pct": 2.0}})
    monkeypatch.setattr(
        sources.catalyst, "fetch_catalyst",
        lambda codes, date: {
            c: {"announcements": [{"title": "回购", "date": "2026-08-10"}], "concepts": [], "sector_flow": None}
            for c in codes
        },
    )
    monkeypatch.setattr(sources.watchlist_in, "get_watchlist_codes", lambda: [])
    monkeypatch.setattr(funnel, "_fetch_sentiment_phase", lambda date, ctx=None: None)
    return genes


def test_run_funnel_r1r2_passed_带gene_score(mock_sources):
    funnel.clear_funnel_cache()
    result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
    layers = {l.layer_id: l for l in result.layers}
    for lid in ("R1", "R2"):
        assert layers[lid].passed, f"{lid} passed 不应为空"
        for p in layers[lid].passed:
            assert p["gene_score"] == mock_sources[p["code"]]["gene_score"]


def test_run_funnel_r3_passed_带gene_score和matched_triggers(mock_sources):
    funnel.clear_funnel_cache()
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


# ---- S049 D1：全参数 passed dict 字段契约 ----


def test_r1_passed_带consec_boards(mock_sources):
    funnel.clear_funnel_cache()
    result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
    r1 = {l.layer_id: l for l in result.layers}["R1"]
    by_code = {p["code"]: p for p in r1.passed}
    assert by_code["000001"]["consec_boards"] == 2
    assert by_code["000002"]["consec_boards"] == 1


def test_r2_passed_全参数(mock_sources):
    funnel.clear_funnel_cache()
    result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
    r2 = {l.layer_id: l for l in result.layers}["R2"]
    p = r2.passed[0]
    assert p["turnover_pct"] == 15.0
    assert p["vol_ratio"] == 1.8
    assert p["amount_yi"] == 12.0
    assert p["amplitude_pct"] == 5.0
    assert p["main_net_inflow"] == 5000.0
    assert p["main_net_5d"] == 20000.0
    assert p["northbound"] == 800.0


def test_r3_passed_带auction_open_pct和catalyst_summary(mock_sources):
    funnel.clear_funnel_cache()
    result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
    r3 = {l.layer_id: l for l in result.layers}["R3"]
    by_code = {p["code"]: p for p in r3.passed}
    assert by_code["000001"]["auction_open_pct"] == 2.0
    assert by_code["000001"]["catalyst_summary"] == "回购"


def test_r2_passed_missing源字段为None(mock_sources):
    """未采集字段 None（AC6 缺数据诚实）—— fund 缺某 code 时 northbound=None。"""
    funnel.clear_funnel_cache()
    monkeypatch_t = type("M", (), {})()
    import candidate_funnel.funnel as fmod
    # fund 只给 000001，000002 缺
    orig = sources.fund_flow.fetch_fund_flow
    sources.fund_flow.fetch_fund_flow = lambda codes, date, sectors=None, industry_map=None: {"000001": {"main_net_inflow": 5000.0, "main_net_5d": 20000.0, "northbound": 800.0}}
    try:
        result = funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
        r2 = {l.layer_id: l for l in result.layers}["R2"]
        by_code = {p["code"]: p for p in r2.passed}
        if "000002" in by_code:
            assert by_code["000002"]["main_net_inflow"] is None
            assert by_code["000002"]["northbound"] is None
    finally:
        sources.fund_flow.fetch_fund_flow = orig
    funnel.clear_funnel_cache()


# ---- S049 D6：run_funnel (date,config) 缓存 ----


def test_run_funnel缓存命中不重复采集(mock_sources):
    """同 (date,config) 二跑命中缓存——fetch_genes 只调一次。"""
    funnel.clear_funnel_cache()
    call_count = {"n": 0}
    orig = sources.gene.fetch_genes

    def counting(date):
        call_count["n"] += 1
        return orig(date)

    sources.gene.fetch_genes = counting
    try:
        funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
        funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
        assert call_count["n"] == 1  # 缓存命中第二次不调
    finally:
        sources.gene.fetch_genes = orig
    funnel.clear_funnel_cache()


def test_run_funnel_force绕过缓存(mock_sources):
    """run_funnel_force 清缓存重跑——fetch_genes 调两次。"""
    funnel.clear_funnel_cache()
    call_count = {"n": 0}
    orig = sources.gene.fetch_genes

    def counting(date):
        call_count["n"] += 1
        return orig(date)

    sources.gene.fetch_genes = counting
    try:
        funnel.run_funnel("pre_market", "2026-08-10", ThresholdConfig())
        funnel.run_funnel_force("pre_market", "2026-08-10", ThresholdConfig())
        assert call_count["n"] == 2
    finally:
        sources.gene.fetch_genes = orig
    funnel.clear_funnel_cache()


def test不同config不命中缓存(mock_sources):
    """不同 config → 不同缓存键 → 不命中。"""
    funnel.clear_funnel_cache()
    call_count = {"n": 0}
    orig = sources.gene.fetch_genes

    def counting(date):
        call_count["n"] += 1
        return orig(date)

    sources.gene.fetch_genes = counting
    try:
        c1 = ThresholdConfig()
        c2 = ThresholdConfig(mode="manual")
        funnel.run_funnel("pre_market", "2026-08-10", c1)
        funnel.run_funnel("pre_market", "2026-08-10", c2)
        assert call_count["n"] == 2
    finally:
        sources.gene.fetch_genes = orig
    funnel.clear_funnel_cache()
