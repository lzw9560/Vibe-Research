# -*- coding: utf-8 -*-
"""S008 T13d：公司基本面模型 + value_funnel quality/l3_analysis 迁模型。

锁住：
- financials_from_dict / valuation_percentile_from_dict（nested）/ company_info_from_individual_info 映射；
- l3_analysis.build_analysis_skeleton 经模型读字段（财务摘要/估值分位/行业）；
- quality._listing_info 经 CompanyInfo 读行业/上市日期。
"""
import astock
from data.mappers import (
    company_info_from_individual_info,
    financials_from_dict,
    valuation_percentile_from_dict,
)
from value_funnel import quality
from value_funnel.sources import l3_analysis


# ── mapper ───────────────────────────────────────────────────────────────

def test_financials_from_dict():
    f = financials_from_dict({"revenue": 1e9, "net_profit": 2e8, "roe": 15.0,
                              "gross_margin": 60.0, "net_margin": 20.0, "period": "2026Q1"})
    assert f.revenue == 1e9
    assert f.net_profit == 2e8
    assert f.roe == 15.0
    assert f.gross_margin == 60.0
    assert f.net_margin == 20.0
    assert f.period == "2026Q1"


def test_financials_empty():
    f = financials_from_dict({})
    assert f.revenue is None
    assert f.period is None


def test_valuation_percentile_from_dict_nested():
    v = valuation_percentile_from_dict(
        {"pe_ttm": {"percentile": 35.0}, "pb": {"percentile": 12.0}})
    assert v.pe_ttm_percentile == 35.0
    assert v.pb_percentile == 12.0


def test_valuation_percentile_missing():
    v = valuation_percentile_from_dict({"pe_ttm": {}})
    assert v.pe_ttm_percentile is None
    assert v.pb_percentile is None


def test_company_info_from_individual_info():
    c = company_info_from_individual_info({"行业": "白酒", "上市时间": "2001-08-27"})
    assert c.industry == "白酒"
    assert c.listing_date == "2001-08-27"
    # 上市日期 兜底
    c2 = company_info_from_individual_info({"行业": "汽车", "上市日期": "2010-06-01"})
    assert c2.listing_date == "2010-06-01"


# ── l3_analysis 经模型读字段 ─────────────────────────────────────────────

def test_l3_analysis_skeleton_via_model(monkeypatch):
    monkeypatch.setattr(astock, "financials", lambda c: {
        "revenue": 1e9, "net_profit": 2e8, "roe": 15.0, "gross_margin": 60.0,
        "net_margin": 20.0, "period": "2026Q1"})
    monkeypatch.setattr(astock, "valuation_percentile", lambda c: {
        "pe_ttm": {"percentile": 35.0}, "pb": {"percentile": 12.0}})
    monkeypatch.setattr(astock, "individual_info", lambda c: {"行业": "白酒"})
    a = l3_analysis.build_analysis_skeleton("600519", "贵州茅台")
    assert a.code == "600519"
    assert "营收" in a.financials_summary
    assert "ROE" in a.financials_summary
    assert "2026Q1" in a.financials_summary
    assert "PE-TTM" in a.valuation_position
    assert "PB" in a.valuation_position
    assert "白酒" in a.business_model


def test_l3_analysis_empty_data(monkeypatch):
    monkeypatch.setattr(astock, "financials", lambda c: {})
    monkeypatch.setattr(astock, "valuation_percentile", lambda c: {})
    monkeypatch.setattr(astock, "individual_info", lambda c: {})
    a = l3_analysis.build_analysis_skeleton("600519", "茅台")
    assert a.financials_summary == "（财务数据未取得）"
    assert a.valuation_position == "（估值分位未取得）"


# ── quality._listing_info 经 CompanyInfo ─────────────────────────────────

def test_quality_listing_info_via_model(monkeypatch):
    monkeypatch.setattr(astock, "individual_info", lambda c: {"行业": "白酒", "上市时间": "2001-08-27"})
    years, industry = quality._listing_info("600519")
    assert industry == "白酒"
    assert years >= 20


def test_quality_listing_info_failure(monkeypatch):
    monkeypatch.setattr(astock, "individual_info", lambda c: (_ for _ in ()).throw(RuntimeError("net")))
    assert quality._listing_info("600519") == (0, "")
