# -*- coding: utf-8 -*-
"""S175 T1 — bars_provider 双源（A股 cache + ETF fetch_etf_hist）测试。

grill C1: kline cache stock-only（5226 股），ETF 512890 不在内 → floor 须走
fetch_etf_hist 非 cache。bars_provider composite dispatch by code 类型。

A股 cache bar 格式（baostock_kline_cache.json）：{date, open, high, low, close,
volume, amount, turn, pctChg, isST}——有 OHLC，breakout path_return 够用。
ETF bar 格式（fetch_etf_hist）：{date, close, ret}——floor MTM 够用（只需 close）。
"""
import json

import pytest


def _stock_bar(date="2026-09-07", close=100.0, open_=100.0, high=101.0, low=99.0):
    return {"date": date, "open": open_, "high": high, "low": low,
            "close": close, "volume": 1000.0}


def _etf_bar(date="2026-09-07", close=1.05):
    return {"date": date, "close": close, "ret": 0.0}


def _write_cache(tmp_path, cache):
    (tmp_path / "baostock_kline_cache.json").write_text(json.dumps(cache))


@pytest.fixture(autouse=True)
def _isolate_vr_data_dir(monkeypatch, tmp_path):
    """每个 test 独立 VR_DATA_DIR（tmp_path）+ 清模块 cache。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    from engine.bars_provider import KlineCacheBarsProvider
    KlineCacheBarsProvider.reload()


class TestDispatch:
    """双源 dispatch：A股 code→cache，ETF code→fetch_etf_hist。"""

    def test_stock_code_reads_cache_ohlc(self, tmp_path):
        from engine.bars_provider import KlineCacheBarsProvider
        _write_cache(tmp_path, {"600519": [_stock_bar()]})
        bars = KlineCacheBarsProvider()("600519")
        assert len(bars) == 1
        assert bars[0]["close"] == 100.0
        assert "open" in bars[0]  # A股 OHLC for path_return stop/take
        assert "high" in bars[0] and "low" in bars[0]

    def test_etf_code_calls_fetch_etf_hist_and_normalizes(self, tmp_path, monkeypatch):
        # ETF code 512890 → fetch_etf_hist 分支（mock，不联网）+ 规范化补 open/high/low
        # spec grill SH6: fetch_etf_hist 返 {date,close,ret} 无 open → Executor entry_f=0 全 unbuyable
        from engine.bars_provider import KlineCacheBarsProvider
        monkeypatch.setattr(
            "tools.fetch_etf_tracking.fetch_etf_hist",
            lambda code: [_etf_bar(close=1.05)])
        bars = KlineCacheBarsProvider()("512890")
        assert len(bars) == 1
        assert bars[0]["close"] == 1.05
        # 规范化：open/high/low = close（ETF 净值口径四价相等，Executor T1OpenFill 需 open）
        assert bars[0]["open"] == 1.05
        assert bars[0]["high"] == 1.05
        assert bars[0]["low"] == 1.05
        assert bars[0].get("ret") == 0.0  # 保留原 ret 字段

    def test_unknown_stock_returns_empty(self, tmp_path):
        from engine.bars_provider import KlineCacheBarsProvider
        _write_cache(tmp_path, {})
        assert KlineCacheBarsProvider()("999999") == []

    def test_etf_fetch_returns_empty_on_failure(self, tmp_path, monkeypatch):
        from engine.bars_provider import KlineCacheBarsProvider
        monkeypatch.setattr(
            "tools.fetch_etf_tracking.fetch_etf_hist", lambda code: [])
        monkeypatch.setattr(
            "engine.bars_provider._baostock_etf_hist", lambda code: [])  # baostock 也挂
        assert KlineCacheBarsProvider()("512890") == []

    def test_missing_cache_file_stock_returns_empty(self, tmp_path, monkeypatch):
        """cache miss + baostock fallback fail → A股 返 [] 不崩（降级）。S175 A股 baostock fallback 后 mock baostock fail 测降级。"""
        monkeypatch.setattr("engine.bars_provider._baostock_a_share_hist", lambda code: [])
        from engine.bars_provider import KlineCacheBarsProvider
        assert KlineCacheBarsProvider()("600519") == []

    def test_etf_510300_also_routes_to_fetch(self, tmp_path, monkeypatch):
        """510300（CSI300 ETF）也走 ETF 分支，不读 stock cache。"""
        from engine.bars_provider import KlineCacheBarsProvider
        called = []
        monkeypatch.setattr(
            "tools.fetch_etf_tracking.fetch_etf_hist",
            lambda code: (called.append(code), [_etf_bar(close=0.5)])[1])
        bars = KlineCacheBarsProvider()("510300")
        assert called == ["510300"]
        assert bars[0]["close"] == 0.5

    def test_etf_baostock_fallback_when_fetch_hist_empty(self, tmp_path, monkeypatch):
        """fetch_etf_hist 返空（东财端点挂）→ baostock fallback（不封 IP，支持 ETF）。"""
        from engine.bars_provider import KlineCacheBarsProvider
        monkeypatch.setattr(
            "tools.fetch_etf_tracking.fetch_etf_hist", lambda code: [])  # 东财挂
        monkeypatch.setattr(
            "engine.bars_provider._baostock_etf_hist",
            lambda code: [{"date": "2026-09-09", "open": 1.20, "high": 1.21, "low": 1.19, "close": 1.21}])
        bars = KlineCacheBarsProvider()("512890")
        assert len(bars) == 1
        assert bars[0]["close"] == 1.21
        assert bars[0]["open"] == 1.20  # baostock 已含 open/high/low，规范化不覆盖

    def test_etf_both_sources_empty_returns_empty(self, tmp_path, monkeypatch):
        """fetch_etf_hist + baostock 都空 → []（graceful degrade）。"""
        from engine.bars_provider import KlineCacheBarsProvider
        monkeypatch.setattr("tools.fetch_etf_tracking.fetch_etf_hist", lambda code: [])
        monkeypatch.setattr("engine.bars_provider._baostock_etf_hist", lambda code: [])
        assert KlineCacheBarsProvider()("512890") == []

    def test_etf_normalization_multi_bar_and_filters_bad(self, tmp_path, monkeypatch):
        """多 bar 规范化补 open/high/low + close 缺失/0 的坏 bar 过滤。"""
        from engine.bars_provider import KlineCacheBarsProvider
        monkeypatch.setattr(
            "tools.fetch_etf_tracking.fetch_etf_hist",
            lambda code: [
                {"date": "2026-09-01", "close": 1.0, "ret": 0.0},
                {"date": "2026-09-02", "close": 0.0, "ret": -1.0},  # close=0 过滤
                {"date": "2026-09-03", "ret": 0.01},  # 无 close 过滤
                {"date": "2026-09-04", "close": 1.05, "ret": 0.05},
            ])
        bars = KlineCacheBarsProvider()("512890")
        assert len(bars) == 2  # 只留 2 个有 close 的 bar
        assert bars[0]["close"] == 1.0
        assert bars[0]["open"] == 1.0 and bars[0]["high"] == 1.0 and bars[0]["low"] == 1.0
        assert bars[1]["close"] == 1.05
        assert bars[1]["open"] == 1.05


class TestReload:
    def test_reload_rereads_cache(self, tmp_path):
        from engine.bars_provider import KlineCacheBarsProvider
        _write_cache(tmp_path, {"600519": [_stock_bar()]})
        prov = KlineCacheBarsProvider()
        assert len(prov("600519")) == 1
        # 改 cache 文件 → reload → 新数据（kline_refresh 后重读）
        _write_cache(tmp_path, {"600519": [
            _stock_bar(), _stock_bar(date="2026-09-08", close=101.0)]})
        KlineCacheBarsProvider.reload()
        bars = KlineCacheBarsProvider()("600519")
        assert len(bars) == 2
        assert bars[1]["close"] == 101.0

    def test_corrupt_cache_degrades_to_empty(self, tmp_path, monkeypatch):
        """cache 损坏（非 JSON）+ baostock fail → 降级返空不崩。S175 A股 baostock fallback 后 mock baostock fail 测降级。"""
        monkeypatch.setattr("engine.bars_provider._baostock_a_share_hist", lambda code: [])
        from engine.bars_provider import KlineCacheBarsProvider
        (tmp_path / "baostock_kline_cache.json").write_text("not json{")
        KlineCacheBarsProvider.reload()
        assert KlineCacheBarsProvider()("600519") == []
