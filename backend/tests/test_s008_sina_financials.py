# -*- coding: utf-8 -*-
"""S008 新浪财报三表源单测：锁住 fetch_raw 返 period-keyed rows + mapper 映射。

新浪财报三表（利润表 lrb / 资产负债表 fzb / 现金流量表 llb）是 P1 基本面因子组
的数据地基——quality-screen 7 因子（ROE/FCF/利息覆盖/毛利率/OCF/净利率/股本膨胀）
与 earnings-review 5 异常信号（应收/存货/OCF<NI/资本化/非经常性）都从三表算。

不变量：
- ``fetch_raw(code, report_type, num)`` 返 ``list[dict]``，每期一条，按报告期倒序，
  keys 为中文科目 + ``"报告期"``，值字符串；含同比时附 ``"<科目>_同比"``；
- ``sina_financials_from_rows(rows, report_type)`` 映射 → ``list[FinancialPeriod]``，
  中文科目按别名表归一英文字段，值经 ``_numf`` 转 float，缺字段=None 不臆造。
"""
from data.sources import sina_financial
from data.mappers import sina_financials_from_rows
from models.financials import FinancialPeriod


def _lrb_response() -> dict:
    """利润表返回（result.data.report_list 按 period 键的 dict）。"""
    report_list = {
        "20260331": {"data": [
            {"item_title": "营业总收入", "item_value": "54702912385.23", "item_tongbi": "10.0"},
            {"item_title": "净利润", "item_value": "27242512886.45", "item_tongbi": "5.0"},
            {"item_title": "归属于母公司股东的净利润", "item_value": "27242512886.45"},
            {"item_title": "扣除非经常性损益后的净利润", "item_value": "26000000000.00"},
            {"item_title": "基本每股收益", "item_value": "21.76"},
            {"item_title": "", "item_value": "x"},  # 空 title 跳过
            {"item_title": "营业成本", "item_value": None},  # None 值跳过
        ]},
        "20251231": {"data": [
            {"item_title": "营业总收入", "item_value": "150000000000.00"},
            {"item_title": "净利润", "item_value": "25000000000.00"},
        ]},
    }
    return {"result": {"data": {"report_list": report_list}}}


def test_fetch_raw_returns_period_rows_desc(monkeypatch):
    monkeypatch.setattr(sina_financial, "_fetch_json",
                        lambda code, report_type="lrb", num=8: _lrb_response())
    rows = sina_financial.fetch_raw("600519", report_type="lrb", num=8)
    assert len(rows) == 2
    assert rows[0]["报告期"] == "2026-03-31"   # 倒序，最新期在前
    assert rows[1]["报告期"] == "2025-12-31"
    # 同比附在 _同比 键
    assert rows[0]["营业总收入"] == "54702912385.23"
    assert rows[0]["营业总收入_同比"] == "10.0"
    # 无同比的不附
    assert "净利润_同比" not in rows[1]


def test_fetch_raw_empty(monkeypatch):
    monkeypatch.setattr(sina_financial, "_fetch_json",
                        lambda code, report_type="lrb", num=8: {"result": {"data": {}}})
    assert sina_financial.fetch_raw("600519") == []


# ── mapper：中文科目 → 英文字段 ──────────────────────────────────────────

def test_mapper_income_statement():
    # 直接造 rows 喂 mapper（不经网络）
    rows = [
        {"报告期": "2026-03-31", "营业总收入": "54702912385.23",
         "净利润": "27242512886.45", "归属于母公司股东的净利润": "27242512886.45",
         "扣除非经常性损益后的净利润": "26000000000.00", "基本每股收益": "21.76",
         "营业成本": "5000000000.00", "营业利润": "30000000000.00"},
    ]
    periods = sina_financials_from_rows(rows, report_type="lrb")
    assert len(periods) == 1
    p = periods[0]
    assert isinstance(p, FinancialPeriod)
    assert p.period == "2026-03-31"
    assert p.revenue == 54702912385.23
    assert p.net_profit == 27242512886.45
    assert p.net_profit_attr_parent == 27242512886.45
    assert p.net_profit_excluding_nonrecurring == 26000000000.00
    assert p.eps_basic == 21.76
    assert p.operating_cost == 5000000000.0
    # 未提供的 balance/cashflow 字段 = None（不臆造）
    assert p.total_assets is None
    assert p.operating_cash_flow is None


def test_mapper_balance_sheet():
    rows = [
        {"报告期": "2026-03-31", "资产总计": "500000000000.00",
         "负债合计": "200000000000.00", "所有者权益合计": "300000000000.00",
         "应收账款": "1000000000.00", "存货": "800000000.00",
         "货币资金": "50000000000.00"},
    ]
    periods = sina_financials_from_rows(rows, report_type="fzb")
    p = periods[0]
    assert p.period == "2026-03-31"
    assert p.total_assets == 500000000000.0
    assert p.total_liabilities == 200000000000.0
    assert p.shareholders_equity == 300000000000.0
    assert p.accounts_receivable == 1000000000.0
    assert p.inventory == 800000000.0
    assert p.cash_and_equivalents == 50000000000.0
    # income 字段 = None
    assert p.revenue is None


def test_mapper_cashflow():
    rows = [
        {"报告期": "2026-03-31", "经营活动产生的现金流量净额": "30000000000.00",
         "投资活动产生的现金流量净额": "-5000000000.00",
         "筹资活动产生的现金流量净额": "-2000000000.00"},
    ]
    periods = sina_financials_from_rows(rows, report_type="llb")
    p = periods[0]
    assert p.operating_cash_flow == 30000000000.0
    assert p.investing_cash_flow == -5000000000.0
    assert p.financing_cash_flow == -2000000000.0


def test_mapper_alias_robustness():
    """科目名别名（'资产合计' == '资产总计'）应命中同一字段。"""
    rows = [{"报告期": "2026-03-31", "资产合计": "999.0", "负债总计": "888.0"}]
    p = sina_financials_from_rows(rows, report_type="fzb")[0]
    assert p.total_assets == 999.0
    assert p.total_liabilities == 888.0


def test_mapper_alias_priority_when_both_present():
    """同字段多别名同时出现时按优先级取首个（营业总收入 > 营业收入）。

    茅台 live 实测：'营业总收入'(54702912385) 与 '营业收入'(53909252220) 同在，
    应取前者（营业总收入口径），非被后者覆盖。
    """
    rows = [{"报告期": "2026-03-31",
             "营业总收入": "54702912385.23", "营业收入": "53909252220.51"}]
    p = sina_financials_from_rows(rows, report_type="lrb")[0]
    assert p.revenue == 54702912385.23  # 首别名（营业总收入）优先


def test_mapper_dash_values_become_none():
    """停牌/无数据 '-' → None，不臆造 0。"""
    rows = [{"报告期": "2026-03-31", "营业总收入": "-", "净利润": ""}]
    p = sina_financials_from_rows(rows, report_type="lrb")[0]
    assert p.revenue is None
    assert p.net_profit is None


def test_mapper_empty_rows():
    assert sina_financials_from_rows([], report_type="lrb") == []
