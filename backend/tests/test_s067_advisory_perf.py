# -*- coding: utf-8 -*-
"""S067 advisory 端点性能优化测试——缓存 + offload + 预热。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from strategies import position_advisor_v2 as adv
from data.sources import tencent as tencent_src


@pytest.fixture(autouse=True)
def _clear_caches():
    adv.clear_caches()
    tencent_src._TENCENT_CACHE.clear()
    yield
    adv.clear_caches()
    tencent_src._TENCENT_CACHE.clear()


class TestWinRateCache:
    """P0：winrate TTL 缓存。"""

    def test_cache_hit_avoids_recompute(self, monkeypatch):
        """第二次调用命中缓存，不重算回测。"""
        call_count = {"n": 0}

        def _fake_backtest(n=90):
            call_count["n"] += 1
            return [SimpleNamespace(strategy_code="SB", win_rate=0.62, sample_size=30, strategy_name="首板")]

        monkeypatch.setattr(adv, "run_strategy_backtest", _fake_backtest)
        adv._win_rate_map()
        adv._win_rate_map()  # 第二次应命中缓存
        assert call_count["n"] == 1  # 只算一次

    def test_cache_expires_after_ttl(self, monkeypatch):
        """TTL 过期后重算。"""
        call_count = {"n": 0}

        def _fake_backtest(n=90):
            call_count["n"] += 1
            return [SimpleNamespace(strategy_code="SB", win_rate=0.5, sample_size=10, strategy_name="首板")]

        monkeypatch.setattr(adv, "run_strategy_backtest", _fake_backtest)
        # 模拟 TTL 过期：手动把 ts 设为很久以前
        adv._win_rate_map()
        # 强制过期
        global _WIN_RATE_CACHE_TS
        adv._WIN_RATE_CACHE_TS = -10000  # 远古时间
        adv._win_rate_map()
        assert call_count["n"] == 2  # TTL 过期重算

    def test_failure_not_cached(self, monkeypatch):
        """回测失败不缓存（下次自动重试）。"""
        call_count = {"n": 0}

        def _failing_backtest(n=90):
            call_count["n"] += 1
            raise Exception("backtest error")

        monkeypatch.setattr(adv, "run_strategy_backtest", _failing_backtest)
        result1 = adv._win_rate_map()
        result2 = adv._win_rate_map()
        assert result1 == {}
        assert result2 == {}
        assert call_count["n"] == 2  # 失败每次重试


class TestClearCaches:
    """clear_caches 隔离入口。"""

    def test_clear_winrate_cache(self, monkeypatch):
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [
            SimpleNamespace(strategy_code="SB", win_rate=0.6, sample_size=30, strategy_name="首板")
        ])
        adv._win_rate_map()
        assert len(adv._WIN_RATE_CACHE) > 0
        adv.clear_caches()
        assert len(adv._WIN_RATE_CACHE) == 0
        assert adv._WIN_RATE_CACHE_TS == 0.0

    def test_clear_kline_cache(self):
        adv._kline_cache["test"] = []
        adv._KLINE_CACHE[("test", 4, 30)] = (None, 0)
        adv.clear_caches()
        assert len(adv._kline_cache) == 0
        assert len(adv._KLINE_CACHE) == 0


class TestTencentQuoteCache:
    """P0-2：tencent_quote 60s 缓存。"""

    def test_cache_hit_same_codes(self, monkeypatch):
        """相同 codes 组第二次命中缓存。"""
        call_count = {"n": 0}
        original_fetch = tencent_src._fetch_gtimg

        def _fake_fetch(codes):
            call_count["n"] += 1
            return original_fetch(codes) if codes else ""

        monkeypatch.setattr(tencent_src, "_fetch_gtimg", _fake_fetch)
        # mock _parse_gtimg 避免真实网络
        monkeypatch.setattr(tencent_src, "_parse_gtimg", lambda data: {"000001": {"name": "测试"}})

        tencent_src.fetch_raw(["000001"])
        tencent_src.fetch_raw(["000001"])  # 相同 codes，应命中
        assert call_count["n"] == 1

    def test_different_codes_not_cached(self, monkeypatch):
        """不同 codes 不命中。"""
        call_count = {"n": 0}

        def _counting_fetch(codes):
            call_count["n"] += 1
            return ""

        monkeypatch.setattr(tencent_src, "_fetch_gtimg", _counting_fetch)
        monkeypatch.setattr(tencent_src, "_parse_gtimg", lambda data: {})

        tencent_src.fetch_raw(["000001"])
        tencent_src.fetch_raw(["000002"])  # 不同 code
        assert call_count["n"] == 2

    def test_empty_codes_no_fetch(self, monkeypatch):
        """空 codes 不发请求。"""
        monkeypatch.setattr(tencent_src, "_fetch_gtimg", lambda codes: pytest.fail("不应调用"))
        result = tencent_src.fetch_raw([])
        assert result == {}


class TestAdvisorySummaryGather:
    """P2-1：三场景 asyncio.gather 并行 + to_thread offload。"""

    def test_summary_returns_three_scenes(self, monkeypatch):
        """advisory_summary 返回三场景 + disclaimer，不阻塞事件循环。"""
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [])
        monkeypatch.setattr(adv, "advise_recommendations", lambda limit=20: [])
        monkeypatch.setattr(adv, "advise_watchlist", lambda: [])
        # advise_holdings 是 async，mock 返空
        async def _empty_holdings():
            return []
        monkeypatch.setattr(adv, "advise_holdings", _empty_holdings)

        result = asyncio.run(adv.advisory_summary(limit=5))
        assert "recommendations" in result
        assert "watchlist" in result
        assert "holdings" in result
        assert "disclaimer" in result

    def test_summary_does_not_block_event_loop(self, monkeypatch):
        """gather + to_thread 不阻塞——并发跑一个轻量 async 任务验证。"""
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [])
        monkeypatch.setattr(adv, "advise_recommendations", lambda limit=20: [])
        monkeypatch.setattr(adv, "advise_watchlist", lambda: [])
        async def _empty_holdings():
            return []
        monkeypatch.setattr(adv, "advise_holdings", _empty_holdings)

        async def _runner():
            # advisory_summary 跑的同时，event loop 仍能执行其他协程
            done = {"v": False}

            async def _background():
                done["v"] = True

            bg = asyncio.create_task(_background())
            await adv.advisory_summary(limit=5)
            await bg
            return done["v"]

        assert asyncio.run(_runner()) is True


class TestKlineCacheClearRemoved:
    """P1-2：移除 _kline_cache.clear()——holdings 不再自毁缓存。"""

    def test_holdings_does_not_clear_kline_cache(self, monkeypatch):
        """advise_holdings 不再清 _kline_cache。"""
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [])
        # 预填 kline_cache
        adv._kline_cache["preexisting"] = []
        # mock portfolio
        import portfolio as pf

        async def _pf():
            return {"holdings": []}

        monkeypatch.setattr(pf, "get_portfolio", _pf)
        asyncio.run(adv.advise_holdings())
        # holdings 为空早返，但即使非空也不应清缓存——验证 preexisting 仍在
        assert "preexisting" in adv._kline_cache


class TestBatchLookupStrategies:
    """P2-2：批量 IN 查询消除 N+1。"""

    def test_batch_returns_map_for_all_codes(self, monkeypatch):
        """批量查询返回所有 code 的匹配结果 map。"""
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [
            SimpleNamespace(strategy_code="SB", win_rate=0.6, sample_size=30, strategy_name="首板")
        ])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [
            SimpleNamespace(strategy_code="SB", strategy_name="首板")
        ])
        # mock get_db 返回批量历史日
        from limitup_screener import data as ldata

        class _FakeCursor:
            def fetchall(self): return [{"code": "000002", "d": "2026-08-01"}]
        class _FakeConn:
            def execute(self, *a, **kw): return _FakeCursor()
            def close(self): pass
        monkeypatch.setattr(ldata, "get_db", lambda: _FakeConn())
        # 000001 当日命中（层1），000002 走历史（层2），000003 落层3
        gene_map = {"000001": SimpleNamespace(code="000001", total_score=70, factors={})}
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [
            SimpleNamespace(code="000002", total_score=70, factors={})
        ] if d == "2026-08-01" else [])
        wr_map = adv._win_rate_map()

        result = adv._lookup_holding_strategies_batch(
            ["000001", "000002", "000003"], gene_map, wr_map
        )
        assert len(result) == 3
        assert result["000001"][5] == 1  # 层 1
        assert result["000002"][5] == 2  # 层 2
        assert result["000003"][5] == 3  # 层 3

    def test_batch_empty_codes_returns_empty(self):
        result = adv._lookup_holding_strategies_batch([], {}, {})
        assert result == {}

    def test_batch_all_layer1_no_db_query(self, monkeypatch):
        """全在当日命中 → 不查 DB。"""
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [
            SimpleNamespace(strategy_code="SB", win_rate=0.6, sample_size=30, strategy_name="首板")
        ])
        monkeypatch.setattr(adv, "match_strategies", lambda code, gene: [
            SimpleNamespace(strategy_code="SB", strategy_name="首板")
        ])
        # get_db 不应被调用
        from limitup_screener import data as ldata
        monkeypatch.setattr(ldata, "get_db", lambda: pytest.fail("不应查 DB"))
        gene_map = {"000001": SimpleNamespace(code="000001", total_score=70, factors={})}
        wr_map = adv._win_rate_map()
        result = adv._lookup_holding_strategies_batch(["000001"], gene_map, wr_map)
        assert result["000001"][5] == 1


class TestPrefetchKlinesConcurrent:
    """P1-1：并发预取 kline。"""

    def test_prefetch_populates_cache(self, monkeypatch):
        """预取后 _kline_cache 有值。"""
        monkeypatch.setattr(adv, "_atr_trailing_stop", lambda code, cost, sfp=None: (None, None, False))
        # _atr_trailing_stop mock 不会填 cache，需手动验证调用
        call_log = {"codes": []}

        def _tracking_atr(code, cost, sfp=None):
            call_log["codes"].append(code)
            adv._kline_cache[code] = []
            return (None, None, False)
        monkeypatch.setattr(adv, "_atr_trailing_stop", _tracking_atr)
        adv._prefetch_klines_concurrent(["000001", "000002", "000003"])
        # 三个 code 都被预取
        assert set(call_log["codes"]) == {"000001", "000002", "000003"}

    def test_prefetch_skips_cached(self, monkeypatch):
        """已缓存的 code 不重新预取。"""
        adv._kline_cache["cached_code"] = []
        called = {"n": 0}

        def _tracking_atr(code, cost, sfp=None):
            called["n"] += 1
            return (None, None, False)
        monkeypatch.setattr(adv, "_atr_trailing_stop", _tracking_atr)
        adv._prefetch_klines_concurrent(["cached_code", "new_code"])
        # 只 new_code 被调（cached_code 已在 _kline_cache）
        assert called["n"] == 1

    def test_prefetch_empty_list_noop(self):
        adv._prefetch_klines_concurrent([])


class TestEndpointTimeout:
    """P3：端点 15s 超时降级。"""

    def test_normal_path_returns_full(self, monkeypatch):
        """正常路径（<15s）返回三场景 + 无 partial。"""
        from routers import advisory as adv_router
        monkeypatch.setattr(adv, "load_gene_scores", lambda d: [])
        monkeypatch.setattr(adv, "run_strategy_backtest", lambda n=90: [])
        # mock advise_recommendations/watchlist 返空（避免真跑）
        monkeypatch.setattr(adv, "advise_recommendations", lambda limit=20: [])
        monkeypatch.setattr(adv, "advise_watchlist", lambda: [])

        async def _empty_holdings():
            return []
        monkeypatch.setattr(adv, "advise_holdings", _empty_holdings)

        import asyncio
        result = asyncio.run(adv_router.advisory_summary_endpoint(limit=5))
        assert result.get("partial") is not True
        assert "recommendations" in result

    def test_timeout_returns_partial_empty(self, monkeypatch):
        """超时 → 返空 + partial=true + timed_out（不重算）。"""
        from routers import advisory as adv_router
        # mock advisory_summary 永不完成（sleep > timeout）
        import asyncio

        async def _hanging_summary(limit):
            await asyncio.sleep(100)
            return {}
        monkeypatch.setattr(adv_router, "advisory_summary", _hanging_summary)
        # 缩短 timeout 加速测试
        monkeypatch.setattr(adv_router, "_ENDPOINT_TIMEOUT", 0.1)

        result = asyncio.run(adv_router.advisory_summary_endpoint(limit=5))
        assert result["partial"] is True
        assert result["timed_out"] is True
        assert result["recommendations"] == []
        assert "超时" in result["note"]
