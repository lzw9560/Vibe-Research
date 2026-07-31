# -*- coding: utf-8 -*-
"""S008 T13e：龙虎榜/席位/行业/公告/概念模型 + 杂项消费者迁模型。

锁住：
- dragon_tiger_from_dict / billboard_detail_from_dict / industry_sector_from_dict /
  announcement_from_dict / concept_blocks_from_dict 映射；
- risk_models 龙虎榜（records[].net_buy）+ fund_flow source（institution_net）经 DragonTiger；
- seat_engine._merge_record_into_profile + 席位循环经 BillboardDetail（含 OPERATEDEPT_CODE）；
- sector_divergence 经 IndustrySector（name/change_pct/up_count/down_count）；
- catalyst 经 Announcement/ConceptBlock（输出 shape 不变兼容下游）。
"""
import astock
import risk_models
from candidate_funnel.sources import catalyst, fund_flow
from data.mappers import (
    announcement_from_dict,
    billboard_detail_from_dict,
    concept_blocks_from_dict,
    dragon_tiger_from_dict,
    industry_sector_from_dict,
)
import sector_divergence
from seat_engine.service import SeatProfile


# ── mapper ───────────────────────────────────────────────────────────────

def test_dragon_tiger_from_dict():
    dt = dragon_tiger_from_dict({"records": [{"net_buy": 1e8}, {"net_buy": -5e7}],
                                "institution": {"net_amt": 3e8}})
    assert len(dt.records) == 2
    assert dt.records[0].net_buy == 1e8
    assert dt.records[1].net_buy == -5e7
    assert dt.institution_net == 3e8


def test_dragon_tiger_empty():
    dt = dragon_tiger_from_dict({})
    assert dt.records == ()
    assert dt.institution_net is None


def test_billboard_detail_from_dict():
    b = billboard_detail_from_dict({"BUY": 1e8, "SELL": 5e7, "NET": 5e7,
                                    "SECURITY_CODE": "600519",
                                    "TRADE_DATE": "2026-07-30T00:00:00",
                                    "OPERATEDEPT_NAME": "华泰证券",
                                    "OPERATEDEPT_CODE": "0"})
    assert b.buy == 1e8
    assert b.sell == 5e7
    assert b.net == 5e7
    assert b.security_code == "600519"
    assert b.trade_date == "2026-07-30"
    assert b.operate_dept_name == "华泰证券"
    assert b.operate_dept_code == "0"


def test_industry_sector_from_dict():
    s = industry_sector_from_dict({"name": "白酒", "change_pct": 2.3,
                                    "up_count": 30, "down_count": 10})
    assert s.name == "白酒"
    assert s.change_pct == 2.3
    assert s.up_count == 30
    assert s.down_count == 10


def test_announcement_and_concept_blocks():
    a = announcement_from_dict({"title": "回购", "date": "2026-07-30", "type": "利好"})
    assert a.title == "回购"
    assert a.date == "2026-07-30"
    assert a.type == "利好"
    cbs = concept_blocks_from_dict({"boards": [{"name": "新能源"}, {"name": ""}, {}]})
    assert len(cbs) == 3
    assert cbs[0].name == "新能源"


# ── risk_models 龙虎榜经模型 ─────────────────────────────────────────────

def test_risk_concentration_via_model(monkeypatch):
    monkeypatch.setattr(astock, "dragon_tiger_board", lambda code, look_back=10: {
        "records": [{"net_buy": 1e8}, {"net_buy": 5e7}, {"net_buy": 3e7},
                    {"net_buy": 2e7}, {"net_buy": 1e7}]})
    r = __import__("asyncio").run(risk_models._calculate_concentration_risk("600519"))
    assert r > 0


def test_risk_dragon_tiger_empty(monkeypatch):
    monkeypatch.setattr(astock, "dragon_tiger_board", lambda code, look_back=10: {"records": []})
    assert __import__("asyncio").run(risk_models._calculate_concentration_risk("600519")) == 0.0


# ── seat_engine 经 BillboardDetail ───────────────────────────────────────

def test_seat_engine_merge_record_via_model():
    from seat_engine.service import SeatEngine
    eng = SeatEngine.__new__(SeatEngine)  # 不走 __init__ 的依赖
    profile = SeatProfile(seat_name="测试席位")
    record = {"BUY": 1e8, "SELL": 5e7, "NET": 5e7, "SECURITY_CODE": "600519",
              "TRADE_DATE": "2026-07-30", "OPERATEDEPT_NAME": "测试席位", "OPERATEDEPT_CODE": "0"}
    eng._merge_record_into_profile(record, profile, side="buy")
    assert profile.total_buy_amt == 1e8
    assert profile.net_amt == 5e7
    assert "600519" in profile._stocks_traded


# ── sector_divergence 经 IndustrySector ──────────────────────────────────

def test_sector_divergence_via_model(monkeypatch):
    monkeypatch.setattr(astock, "industry_comparison", lambda top_n=100: {
        "top": [{"name": "白酒", "change_pct": 2.3, "up_count": 30, "down_count": 10}],
        "bottom": [{"name": "地产", "change_pct": -1.5, "up_count": 5, "down_count": 35}]})
    import asyncio
    res = asyncio.run(sector_divergence.calculate_sector_divergence())
    assert len(res) == 2
    names = {d.sector for d in res}
    assert "白酒" in names and "地产" in names


def test_sector_rotation_via_model(monkeypatch):
    monkeypatch.setattr(astock, "industry_comparison", lambda top_n=100: {
        "top": [{"name": "白酒", "change_pct": 2.3, "up_count": 30, "down_count": 10}],
        "bottom": []})
    import asyncio
    rot = asyncio.run(sector_divergence.calculate_sector_rotation())
    assert rot is not None
    assert "白酒" in rot.hot_sectors
    # sectors 字段是 dict shape（model_dump，下游兼容）
    assert isinstance(rot.sectors[0], dict)
    assert rot.sectors[0]["name"] == "白酒"


# ── catalyst 经模型（输出 shape 不变）───────────────────────────────────

def test_catalyst_via_model(monkeypatch):
    monkeypatch.setattr(astock, "announcements", lambda c, limit=10: [
        {"title": "回购", "date": "2026-07-30", "type": "利好"}])
    monkeypatch.setattr(astock, "concept_blocks", lambda c: {"boards": [{"name": "新能源"}]})
    out = catalyst.fetch_catalyst(["600519"], "2026-07-30")
    e = out["600519"]
    assert e["announcements"] == [{"title": "回购", "date": "2026-07-30", "type": "利好"}]
    assert e["concepts"] == ["新能源"]


def test_fund_flow_dragon_tiger_via_model(monkeypatch):
    monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda c: [])
    monkeypatch.setattr(astock, "dragon_tiger_board", lambda c: {"institution": {"net_amt": 3e8}})
    out = fund_flow.fetch_fund_flow(["600519"], "2026-07-30")
    assert out["600519"]["dragon_tiger_inst_net"] == 3e8
