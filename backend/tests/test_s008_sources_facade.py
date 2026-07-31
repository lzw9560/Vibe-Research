# -*- coding: utf-8 -*-
"""S008 astock 门面非回归测：公开签名/返回 shape 不变，内部委派到 data.sources。

锁住迁移零行为变更——28 个消费者继续吃 astock 的 raw dict。
"""
import data.transport
import astock
from data.sources import tencent, eastmoney


def test_tencent_quote_is_source_fetch_raw():
    """astock.tencent_quote 门面直接委派到 sources.tencent.fetch_raw（同对象）。"""
    assert astock.tencent_quote is tencent.fetch_raw
    assert astock.index_quote is tencent.index_raw


def test_em_get_is_transport():
    """astock.em_get 即 data.transport.eastmoney_get（防封底线，不裸调 requests）。"""
    assert astock.em_get is data.transport.eastmoney_get


def test_internal_helpers_reexported():
    """被外部直访的内部名保留 re-export（auction_screener/market/seat_engine 等依赖）。"""
    assert astock._numf is eastmoney._numf
    assert astock.UA
    assert astock.DependencyMissing is not None
    assert astock.get_prefix("600519") == "sh"
    assert astock._parse_gtimg("") == {}
    # _akshare 可调用（不实际触发 import）
    assert callable(astock._akshare)


def test_public_surface_intact():
    """公开取数函数全部仍可解析为 callable（签名未丢）。"""
    expected = [
        "tencent_quote", "index_quote", "em_get", "eastmoney_reports",
        "eastmoney_industry_reports", "pdf_url", "announcements", "em_zt_topic_pool",
        "market_turnover_rank", "eastmoney_datacenter", "margin_trading", "block_trade",
        "holder_num_change", "dividend_history", "stock_fund_flow_120d",
        "dragon_tiger_board", "lockup_expiry", "concept_blocks", "hot_concepts",
        "industry_comparison", "profit_forecast", "stock_news", "individual_info",
        "disclosure", "financials", "valuation_percentile", "kline", "finance",
        "investor_qa", "calc_peg", "pe_digestion", "full_valuation",
    ]
    missing = [name for name in expected if not hasattr(astock, name)]
    assert missing == [], f"astock 门面缺公开名: {missing}"


def test_tencent_quote_returns_full_field_dict(monkeypatch):
    """非回归：astock.tencent_quote 返 raw dict 含 last_close/open/vol_ratio
    （bidding_monitor / candidate_funnel 依赖——防 R5 类静默退化）。"""
    parts = ["0"] * 55
    parts[1] = "贵州茅台"
    parts[3] = "1194.45"
    parts[4] = "1180.0"   # last_close
    parts[5] = "1190.0"   # open
    parts[49] = "2.3"     # vol_ratio
    monkeypatch.setattr(tencent, "_fetch_gtimg", lambda codes: 'v_sh600519="' + "~".join(parts) + '";')
    q = astock.tencent_quote(["600519"])["600519"]
    assert q["last_close"] == 1180.0
    assert q["open"] == 1190.0
    assert q["vol_ratio"] == 2.3
