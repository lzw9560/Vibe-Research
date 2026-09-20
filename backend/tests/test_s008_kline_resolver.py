# -*- coding: utf-8 -*-
"""S008 kline 解析器单测：多源 fallback 链（baostock → 东方财富 → cache）。

2026-09-20 恢复多源：baostock 被拉黑后 fallback 东方财富，两源都失败用 cache。

不依赖真实网络——monkeypatch _baostock / _eastmoney / _cache_bars 注入
成功/抛异常/返空，验证解析器的 fallback 契约（顺序降级、不抛、不臆造、空返
([], None)）。
"""
from data.sources import kline_resolver as kr


def _stub(bars=None, exc=None):
    """造一个源 stub：返 bars / 抛 exc / 返空。"""
    def fn(code):
        if exc:
            raise exc
        return bars or []
    return fn


# --- baostock 首选成功（不调东财）---

def test_baostock_first_success(monkeypatch):
    """baostock 成功 → 用 baostock，不调东财。"""
    em_calls: list[str] = []
    def _em_spy(code):
        em_calls.append(code)
        return [{"date": "em"}]  # 不该被调
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1", "close": 10.0}]))
    monkeypatch.setattr(kr, "_eastmoney", _em_spy)
    bars, src = kr.fetch_kline("600519")
    assert src == "baostock"
    assert len(bars) == 1
    assert em_calls == []  # baostock 成功，东财未被调


# --- baostock 失败 → fallback 东财 ---

def test_baostock_empty_fallback_eastmoney(monkeypatch):
    """baostock 返空（黑名单/新股/无数据）→ fallback 东财成功。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[]))
    monkeypatch.setattr(kr, "_eastmoney", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "eastmoney"
    assert len(bars) == 1


def test_baostock_exc_fallback_eastmoney(monkeypatch):
    """baostock 抛异常（黑名单报错/超时）→ fallback 东财成功。"""
    monkeypatch.setattr(kr, "_baostock", _stub(exc=ConnectionError("10001011 黑名单用户")))
    monkeypatch.setattr(kr, "_eastmoney", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "eastmoney"
    assert len(bars) == 1


# --- 两源都失败 → cache fallback ---

def test_both_sources_empty_use_cache(monkeypatch):
    """baostock + 东财都返空 → cache fallback 成功。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[]))
    monkeypatch.setattr(kr, "_eastmoney", _stub(bars=[]))
    monkeypatch.setattr(kr, "_cache_bars", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "cache"
    assert len(bars) == 1


def test_both_sources_fail_use_cache(monkeypatch):
    """baostock + 东财都抛异常 → cache fallback 成功。"""
    monkeypatch.setattr(kr, "_baostock", _stub(exc=RuntimeError("baostock 黑名单")))
    monkeypatch.setattr(kr, "_eastmoney", _stub(exc=RuntimeError("em_get 熔断")))
    monkeypatch.setattr(kr, "_cache_bars", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "cache"
    assert len(bars) == 1


# --- 全失败（含 cache）→ 诚实返空 ---

def test_all_fail_including_cache_returns_empty(monkeypatch):
    """baostock + 东财 + cache 都空/失败 → ([], None)，不抛、不臆造。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[]))
    monkeypatch.setattr(kr, "_eastmoney", _stub(bars=[]))
    monkeypatch.setattr(kr, "_cache_bars", _stub(bars=[]))
    bars, src = kr.fetch_kline("600519")
    assert bars == []
    assert src is None


def test_all_sources_exc_cache_exc_returns_empty(monkeypatch):
    """baostock + 东财 + cache 都抛异常 → ([], None)，cache 异常也吞。"""
    monkeypatch.setattr(kr, "_baostock", _stub(exc=RuntimeError("bs down")))
    monkeypatch.setattr(kr, "_eastmoney", _stub(exc=RuntimeError("em down")))
    monkeypatch.setattr(kr, "_cache_bars", _stub(exc=RuntimeError("cache corrupt")))
    bars, src = kr.fetch_kline("600519")
    assert bars == []
    assert src is None


# --- 源链注册表 ---

def test_list_sources_order():
    """源链：baostock + 东方财富（cache 不在 _SOURCES，是最后兜底）。"""
    assert kr.list_sources() == ["baostock", "eastmoney"]


def test_list_sources_by_adjust():
    """list_sources(adjust) 按口径筛选——qfq 返两源，none 返空。"""
    assert kr.list_sources(adjust="qfq") == ["baostock", "eastmoney"]
    assert kr.list_sources(adjust="none") == []


def test_adjust_of_map():
    """各源原生口径声明（单一事实源）。baostock + 东财均 qfq。"""
    assert kr.adjust_of("baostock") == "qfq"
    assert kr.adjust_of("eastmoney") == "qfq"
    assert kr.adjust_of("unknown") is None


# --- adjust / sources 参数筛选 ---

def test_adjust_qfq_returns_baostock(monkeypatch):
    """adjust='qfq' 命中 baostock（首选）。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519", adjust="qfq")
    assert src == "baostock"
    assert len(bars) == 1


def test_adjust_none_returns_empty_no_source(monkeypatch):
    """adjust='none' 无源（baostock/eastmoney 均是 qfq）→ 诚实返空，不臆造复权。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1", "close": 999.0}]))
    bars, src = kr.fetch_kline("600519", adjust="none")
    assert bars == []
    assert src is None


def test_source_subset(monkeypatch):
    """sources 参数限定子集——['baostock'] 只试 baostock（失败不再 fallback 东财）。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1"}]))
    bars, src = kr.fetch_kline("600519", sources=["baostock"])
    assert src == "baostock"
    # sources=['baostock'] 时 baostock 空也不试东财（子集限定）
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[]))
    monkeypatch.setattr(kr, "_eastmoney", _stub(bars=[{"date": "em"}]))
    bars, src = kr.fetch_kline("600519", sources=["baostock"])
    assert src is None  # 子集不含 eastmoney，不 fallback
    # sources=['eastmoney'] 只试东财
    bars, src = kr.fetch_kline("600519", sources=["eastmoney"])
    assert src == "eastmoney"


def test_source_subset_unknown_returns_empty(monkeypatch):
    """sources=['sina']（不在 _SOURCES）→ 空链 → ([], None)。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1"}]))
    bars, src = kr.fetch_kline("600519", sources=["sina"])
    assert src is None
