# -*- coding: utf-8 -*-
"""S008 T13c-part1：ZTPoolItem 模型 + 直连 astock 的池消费者迁模型。

锁住：
- ``zt_pool_item_from_dict`` 映射 raw→ZTPoolItem 全字段（c/n/lbc/fbt/zbc/zje/open/
  seal_amount/float_shares/prev_close/zdp/hybk）+ pool_date 合成注入；
- daily_review 三方法经模型读字段（sector_heat/summarize_zt_stocks/prev_zt_performance）；
- auction_screener 候选提取经模型读字段（lbc/fbt/zbc/zje/open/seal_amount/float_shares/prev_close）。
"""
import astock
import auction_screener
import daily_review
from data.mappers import zt_pool_item_from_dict


def _raw_pool_item(code="600519", **over):
    base = {
        "c": code, "n": "贵州茅台", "lbc": 3, "fbt": 93500, "zbc": 1,
        "zje": 1850.0, "open": 1800.0, "seal_amount": 5e8,
        "float_shares": 1e8, "prev_close": 1680.0, "zdp": 10.0, "hybk": "白酒",
    }
    base.update(over)
    return base


# ── mapper ───────────────────────────────────────────────────────────────

def test_zt_pool_item_from_dict_maps_all_fields():
    it = zt_pool_item_from_dict(_raw_pool_item(), pool_date="2026-07-30")
    assert it.code == "600519"
    assert it.name == "贵州茅台"
    assert it.boards == 3.0
    assert it.seal_time == 93500.0
    assert it.broken_count == 1.0
    assert it.limit_price == 1850.0
    assert it.open == 1800.0
    assert it.seal_amount == 5e8
    assert it.float_shares == 1e8
    assert it.prev_close == 1680.0
    assert it.limit_pct == 10.0
    assert it.industry == "白酒"
    assert it.pool_date == "2026-07-30"


def test_zt_pool_item_from_dict_missing_fields_none():
    it = zt_pool_item_from_dict({"c": "000001"})
    assert it.code == "000001"
    assert it.name is None
    assert it.boards is None
    assert it.seal_amount is None
    assert it.pool_date is None


# ── daily_review 经模型读字段 ───────────────────────────────────────────

def _pool(items: list[dict]) -> list:
    return [zt_pool_item_from_dict(it) for it in items]


def test_daily_review_sector_heat_via_model():
    r = daily_review.DailyReviewer()
    pool = _pool([_raw_pool_item("600519"), _raw_pool_item("000858", hybk="白酒"),
                  _raw_pool_item("002594", hybk="汽车")])
    heat = r._calculate_sector_heat(pool)
    sectors = {h.sector for h in heat}
    assert "白酒" in sectors
    # 白酒 2 只，排第一
    assert heat[0].sector == "白酒"
    assert heat[0].zt_count == 2


def test_daily_review_summarize_zt_stocks_via_model():
    r = daily_review.DailyReviewer()
    pool = _pool([_raw_pool_item("600519"), _raw_pool_item("000858")])
    stocks = r._summarize_zt_stocks(pool)
    assert len(stocks) == 2
    s = stocks[0] if stocks[0].code == "600519" else stocks[1]
    assert s.code == "600519"
    assert s.name == "贵州茅台"
    assert s.lbc == 3
    assert s.zbc == 1


def test_daily_review_summarize_skips_non_a_codes():
    r = daily_review.DailyReviewer()
    pool = _pool([_raw_pool_item("00700"), _raw_pool_item("600519")])  # 00700 非 6 位 A
    stocks = r._summarize_zt_stocks(pool)
    assert all(s.code == "600519" for s in stocks)


def test_daily_review_prev_zt_performance_via_model():
    r = daily_review.DailyReviewer()
    yzt = _pool([_raw_pool_item("600519"), _raw_pool_item("000858")])
    zt = _pool([_raw_pool_item("600519")])  # 1 只昨日仍在今日涨停池
    perf = r._calculate_prev_zt_performance(yzt, zt)
    assert perf["prev_zt_count"] == 2
    assert perf["retention_rate"] == 50.0  # 1/2


def test_daily_review_prev_zt_empty():
    r = daily_review.DailyReviewer()
    perf = r._calculate_prev_zt_performance([], [])
    assert perf["prev_zt_count"] == 0
    assert perf["retention_rate"] == 0.0


# ── auction_screener 经模型读字段 ───────────────────────────────────────

def test_auction_screener_screen_via_model(monkeypatch):
    """monkeypatch 池 + 基因缓存 + sti，跑 analyze()，断言候选字段经模型正确提取。"""
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda endpoint, date, sort="fbt:asc": [_raw_pool_item()])
    screener = auction_screener.AuctionScreener()
    monkeypatch.setattr(screener, "_get_gene_scores_cache", lambda: {"600519": {"total_score": 75, "zt_count_30d": 3}})
    monkeypatch.setattr(screener, "_get_sti_result", lambda d: {"score": 50, "phase": "启动"})
    result = screener.analyze("2026-07-30")
    assert result.total_analyzed >= 1
    cands = [c for c in result.candidates if c.get("code") == "600519"]
    assert cands, "候选应含 600519"
    # 经模型提取的字段正确（lbc/name/seal_amount/float_shares）
    assert cands[0]["name"] == "贵州茅台"
    assert cands[0]["seal_amount"] == 5e8
    assert cands[0]["float_shares"] == 1e8


# ── T13c-part2：limitup_screener service/models entangled 路径 ──────────

def test_compute_gene_score_reads_pool_item_model():
    """compute_gene_score 经 ZTPoolItem 读 pool_item（seal_amount/float_shares/prev_close）+ history(pool_date/boards)。"""
    from limitup_screener.models import compute_gene_score
    history = [
        zt_pool_item_from_dict(_raw_pool_item("600519"), pool_date="20260725"),
        zt_pool_item_from_dict(_raw_pool_item("600519", lbc=2), pool_date="20260726"),
    ]
    pool_item = zt_pool_item_from_dict(_raw_pool_item("600519"), pool_date="20260730")
    g = compute_gene_score("600519", "贵州茅台", history, [], [], include_backtest=True, pool_item=pool_item)
    assert g.code == "600519"
    assert g.name == "贵州茅台"
    # pool_date 经模型注入 → last_zt_dates 非空
    assert "20260725" in g.last_zt_dates or "20260726" in g.last_zt_dates
    assert g.zt_count_250d == 2


def test_collect_zt_history_batch_injects_pool_date(monkeypatch):
    """_collect_zt_history_batch 用 frozen 模型构造 ZTPoolItem 注入 pool_date（替代旧 dict(item,_pool_date=d)）。"""
    import asyncio
    from limitup_screener.service import _collect_zt_history_batch
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda endpoint, date, sort="fbt:asc": [_raw_pool_item("600519")] if endpoint == "getTopicZTPool" else [])
    res = asyncio.run(_collect_zt_history_batch({"600519"}, "20260730", lookback=5))
    assert "600519" in res
    assert len(res["600519"]) >= 1
    item = res["600519"][0]
    # frozen ZTPoolItem，pool_date 已注入（非旧 _pool_date dict 键）
    from models import ZTPoolItem
    assert isinstance(item, ZTPoolItem)
    assert item.pool_date is not None
    assert item.code == "600519"


def test_compute_gene_score_backtest_uses_model_fields():
    """回测路径：compute_factors(history_for_bt) + h.boards/h.pool_date 经模型读。"""
    from limitup_screener.models import compute_gene_score
    history = [
        zt_pool_item_from_dict(_raw_pool_item("600519", lbc=1), pool_date="20260720"),
        zt_pool_item_from_dict(_raw_pool_item("600519", lbc=2), pool_date="20260721"),
        zt_pool_item_from_dict(_raw_pool_item("600519", lbc=3), pool_date="20260722"),
    ]
    g = compute_gene_score("600519", "X", history, [], [], include_backtest=True)
    # 回测点 date 来自 h.pool_date，actual_next_day 来自 h.boards>=2
    assert len(g.backtest_points) >= 1
    assert all("date" in p for p in g.backtest_points)
