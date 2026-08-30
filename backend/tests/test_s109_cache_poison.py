# -*- coding: utf-8 -*-
"""S109 缓存治理 Tier-1 测试——空结果毒缓存根除。

契约（spec §5 验收标准）：
- A1 stock_financial _cached valid 守卫：失败空不缓存
- A2 dict 陷阱（dragon_tiger/lockup/blocks）内容感知 valid 拦住失败 dict
- A3 tencent fetch_raw 空不缓存
- A4 limitup_screener 空涨停池返 expired
- A5 _PCT_CACHE 内容感知（{"metrics":{}} 不缓存，bool 漏网）
- A6 _FIN/_ANN_CACHE 空不缓存
- A7 industry {"top":[]} 不缓存
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_caches():
    """每用例前清所有缓存，防串扰。"""
    from routers import stock_financial as sf
    sf._DC_CACHE.clear()
    from routers import stock_data as sd
    sd._PCT_CACHE.clear()
    sd._FIN_CACHE.clear()
    sd._ANN_CACHE.clear()
    from data.sources import tencent as tc
    tc._TENCENT_CACHE.clear()
    yield
    sf._DC_CACHE.clear()
    sd._PCT_CACHE.clear()
    sd._FIN_CACHE.clear()
    sd._ANN_CACHE.clear()
    tc._TENCENT_CACHE.clear()


# ── A1：stock_financial _cached valid 守卫 ────────────────────────────────────


class TestStockFinancialCached:
    def test_list_empty_not_cached(self):
        """A1：margin 失败返 [] 不缓存，下次重试。"""
        from routers.stock_financial import _cached
        call_count = 0
        def fetch():
            nonlocal call_count
            call_count += 1
            return []
        r1 = _cached("margin", "600519", 1800, fetch)
        r2 = _cached("margin", "600519", 1800, fetch)  # 应重试（空没缓存）
        assert r1 == [] and r2 == []
        assert call_count == 2  # 第二次没命中缓存，重试了

    def test_list_nonempty_cached(self):
        """A1 正路：非空 list 缓存命中。"""
        from routers.stock_financial import _cached
        call_count = 0
        def fetch():
            nonlocal call_count
            call_count += 1
            return [{"x": 1}]
        r1 = _cached("margin", "600519", 1800, fetch)
        r2 = _cached("margin", "600519", 1800, fetch)
        assert r1 == r2 == [{"x": 1}]
        assert call_count == 1  # 命中缓存


# ── A2：dict 陷阱内容感知 valid ───────────────────────────────────────────────


class TestDictTrap:
    def test_dragon_tiger_empty_records_not_cached(self):
        """A2：dragon_tiger 失败 dict {"records":[]} 不缓存（bool 漏网，lambda 拦）。"""
        from routers.stock_financial import _cached
        call_count = 0
        def fetch():
            nonlocal call_count
            call_count += 1
            return {"records": [], "seats": {"buy": [], "sell": []}, "institution": {}}
        valid = lambda v: bool(v.get("records")) if isinstance(v, dict) else bool(v)
        _cached("dt", "600519", 1800, fetch, valid=valid)
        _cached("dt", "600519", 1800, fetch, valid=valid)
        assert call_count == 2  # 空 records 不缓存，重试

    def test_lockup_empty_not_cached(self):
        """A2：lockup {"history":[],"upcoming":[]} 不缓存。"""
        from routers.stock_financial import _cached
        call_count = 0
        def fetch():
            nonlocal call_count
            call_count += 1
            return {"history": [], "upcoming": []}
        valid = lambda v: bool(v.get("history") or v.get("upcoming")) if isinstance(v, dict) else bool(v)
        _cached("lockup", "600519", 1800, fetch, valid=valid)
        _cached("lockup", "600519", 1800, fetch, valid=valid)
        assert call_count == 2

    def test_blocks_empty_boards_not_cached(self):
        """A2：blocks {"total":0,"boards":[]} 不缓存。"""
        from routers.stock_financial import _cached
        call_count = 0
        def fetch():
            nonlocal call_count
            call_count += 1
            return {"total": 0, "boards": [], "concept_tags": []}
        valid = lambda v: bool(v.get("boards")) if isinstance(v, dict) else bool(v)
        _cached("blocks", "600519", 1800, fetch, valid=valid)
        _cached("blocks", "600519", 1800, fetch, valid=valid)
        assert call_count == 2


# ── A3：tencent fetch_raw 空不缓存 ────────────────────────────────────────────


class TestTencent:
    def test_empty_result_not_cached(self):
        """A3：gtimg 返空 {} 不写 _TENCENT_CACHE。"""
        from data.sources import tencent as tc
        with patch.object(tc, "_fetch_gtimg", return_value="v=...."), \
             patch.object(tc, "_parse_gtimg", return_value={}):
            r1 = tc.fetch_raw(["600519"])
        assert r1 == {}
        assert not any(k for k in tc._TENCENT_CACHE.values() if k[0] == {})  # 空 {} 没写入

    def test_nonempty_cached(self):
        """A3 正路：非空缓存命中。"""
        from data.sources import tencent as tc
        call_count = 0
        def fake_fetch(*a):
            nonlocal call_count
            call_count += 1
            return "raw"
        with patch.object(tc, "_fetch_gtimg", side_effect=fake_fetch), \
             patch.object(tc, "_parse_gtimg", return_value={"600519": {"price": 100}}):
            r1 = tc.fetch_raw(["600519"])
            r2 = tc.fetch_raw(["600519"])
        assert r1 == r2
        assert call_count == 1


# ── A5/A6：stock_data 三缓存 ─────────────────────────────────────────────────


class TestStockDataCache:
    def test_pct_cache_dict_trap_not_cached(self):
        """A5：_PCT_CACHE 失败 dict {"metrics":{}} 不缓存（bool 漏网，内容感知拦）。"""
        from routers import stock_data as sd
        call_count = 0
        def fake_pct(code):
            nonlocal call_count
            call_count += 1
            return {"period": "近5年", "metrics": {}}
        with patch.object(sd.astock, "valuation_percentile", side_effect=fake_pct):
            from routers.stock_data import valuation_percentile
            valuation_percentile("600519")
            valuation_percentile("600519")
        assert call_count == 2  # {"metrics":{}} 不缓存，重试

    def test_fin_cache_empty_not_cached(self):
        """A6：_FIN_CACHE 空 {} 不缓存。"""
        from routers import stock_data as sd
        call_count = 0
        def fake_fin(code):
            nonlocal call_count
            call_count += 1
            return {}
        with patch.object(sd.astock, "financials", side_effect=fake_fin):
            from routers.stock_data import financials
            financials("600519")
            financials("600519")
        assert call_count == 2

    def test_ann_cache_empty_not_cached(self):
        """A6：_ANN_CACHE 空 [] 不缓存。"""
        from routers import stock_data as sd
        call_count = 0
        def fake_ann(code):
            nonlocal call_count
            call_count += 1
            return []
        with patch.object(sd.astock, "announcements", side_effect=fake_ann):
            from routers.stock_data import announcements
            announcements("600519")
            announcements("600519")
        assert call_count == 2


# ── A4：limitup_screener 空涨停池返 expired ──────────────────────────────────


class TestLimitupScreener:
    def test_empty_pool_returns_expired_not_fresh(self):
        """A4：空涨停池返 data_freshness=expired（非 fresh），不缓存空。"""
        # 直接测 _empty_screener_result 返 expired
        from limitup_screener.service import _empty_screener_result
        r = _empty_screener_result("20260830", reason="空池")
        assert r.data_freshness == "expired"
        assert r.gene_scores == []


# ── A7：industry dict 陷阱 ────────────────────────────────────────────────────


class TestIndustryCache:
    def test_industry_empty_top_not_cached(self):
        """A7：industry {"top":[]} 不缓存。"""
        from routers import stock_financial as sf
        call_count = 0
        def fake_industry(*a, **kw):
            nonlocal call_count
            call_count += 1
            return {"top": [], "bottom": [], "total": 0}
        with patch.object(sf.astock, "industry_comparison", side_effect=fake_industry):
            sf.industry(top=20)
            sf.industry(top=20)
        assert call_count == 2  # {"top":[]} 不缓存，重试
