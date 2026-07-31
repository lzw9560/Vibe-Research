# -*- coding: utf-8 -*-
"""S008 T12：chat._exec_tool 五个 astock 工具返 S007 模型 model_dump。

前端不解析工具结果字段（只渲染工具调用 chip），故重命名只影响 LLM 提示，不破前端。
"""
import astock
import chat
import gstock


def _raw_tencent():
    return {"600519": {
        "name": "贵州茅台", "price": 1700.0, "last_close": 1680.0, "open": 1690.0,
        "change_pct": 2.3, "change_amt": 38.0, "amount_wan": 123456.0,
        "turnover_pct": 0.5, "pe_ttm": 30.0, "amplitude_pct": 3.2,
        "mcap_yi": 21000.0, "float_mcap_yi": 20900.0, "pb": 10.0,
        "limit_up": 1870.0, "limit_down": 1530.0, "vol_ratio": 2.1, "pe_static": 29.0,
    }}


def test_query_quote_returns_model_dict(monkeypatch):
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _raw_tencent())
    out = chat._exec_tool("query_quote", {"codes": ["600519"]})
    q = out["600519"]
    assert q["turnover_rate"] == 0.5        # turnover_pct→turnover_rate
    assert q["limit_up_price"] == 1870.0    # limit_up→limit_up_price
    assert q["limit_down_price"] == 1530.0
    assert q["last_close"] == 1680.0
    assert q["market_cap"] == 21000.0 * 1e8  # 亿→元
    assert "turnover_pct" not in q and "limit_up" not in q


def test_query_valuation_returns_model_dict(monkeypatch):
    raw = {"name": "贵州茅台", "code": "600519", "price": 1700.0, "mcap_yi": 21000.0,
           "pe_ttm": 30.0, "pb": 10.0, "eps_26e": 2.0, "eps_27e": 2.4,
           "pe_26e": 50.0, "cagr_pct": 20.0, "peg": 2.5, "digest_years": 3.0,
           "analyst_count": 12, "forecast_note": "一致预期需安装 akshare"}
    monkeypatch.setattr(astock, "full_valuation", lambda code: raw)
    out = chat._exec_tool("query_valuation", {"code": "600519"})
    assert out["forward_pe"] == 50.0       # pe_26e→forward_pe
    assert out["consensus_eps"] == 2.0     # eps_26e→consensus_eps
    assert out["market_cap"] == 21000.0 * 1e8
    assert out["peg"] == 2.5
    assert out["note"] == "一致预期需安装 akshare"  # sidecar 保留


def test_query_reports_returns_model_dict(monkeypatch):
    rows = [{"title": "T1", "orgSName": "中金", "publishDate": "2026-07-29",
             "emRatingName": "买入", "researcherName": "张三"}]
    monkeypatch.setattr(astock, "eastmoney_reports", lambda code, max_pages=1: rows)
    out = chat._exec_tool("query_reports", {"code": "600519"})
    assert isinstance(out, list)
    r = out[0]
    assert r["title"] == "T1"
    assert r["org"] == "中金"               # orgSName→org
    assert r["publish_date"] == "2026-07-29"
    assert r["report_type"] == "买入"       # emRatingName→ReportType


def test_query_reports_unknown_rating_safe(monkeypatch):
    rows = [{"title": "T", "emRatingName": "强推（罕见）"}]
    monkeypatch.setattr(astock, "eastmoney_reports", lambda code, max_pages=1: rows)
    r = chat._exec_tool("query_reports", {"code": "600519"})[0]
    assert r["report_type"] in (None, "买入", "增持")  # 未知值降级，不抛


def test_query_news_returns_model_dict(monkeypatch):
    rows = [{"新闻标题": "N1", "发布时间": "2026-07-29", "文章来源": "东财"}]
    monkeypatch.setattr(astock, "stock_news", lambda code, limit=15: rows)
    out = chat._exec_tool("query_news", {"code": "600519"})
    n = out[0]
    assert n["title"] == "N1"
    assert n["publish_time"] == "2026-07-29"
    assert n["source"] == "东财"


def test_query_global_stock_returns_model_dict(monkeypatch):
    raw = {"code": "AAPL", "name": "苹果", "market": "NASDAQ",
           "quote": {"price": 185.0, "prev_close": 182.0, "amount": 1.2e9,
                     "mcap": 2.8e12, "change_pct": 1.5},
           "metrics": {"eps": 6.5, "roe": 0.4}}
    monkeypatch.setattr(gstock, "us_hk_stock", lambda symbol: raw)
    out = chat._exec_tool("query_global_stock", {"symbol": "AAPL"})
    assert out["code"] == "AAPL"
    assert out["quote"]["price"] == 185.0
    assert out["quote"]["last_close"] == 182.0
    assert out["metrics"]["eps"] == 6.5


def test_query_global_stock_not_found(monkeypatch):
    monkeypatch.setattr(gstock, "us_hk_stock", lambda symbol: {})
    out = chat._exec_tool("query_global_stock", {"symbol": "ZZZ"})
    assert out.get("error")
