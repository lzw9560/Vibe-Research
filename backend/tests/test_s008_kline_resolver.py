# -*- coding: utf-8 -*-
"""S008 kline 解析器单测：baostock 单源（2026-09-20 精简，本环境唯一可用源）。

不依赖真实网络——monkeypatch _baostock 注入成功/抛异常/返空，验证解析器的
诚实契约（不抛、不臆造，空返 ([], None)）。
"""
from data.sources import kline_resolver as kr


def _stub(bars=None, exc=None):
    """造一个源 stub：返 bars / 抛 exc / 返空。"""
    def fn(code):
        if exc:
            raise exc
        return bars or []
    return fn


def test_first_success_wins(monkeypatch):
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "baostock"
    assert len(bars) == 1


def test_fallback_on_empty(monkeypatch):
    """baostock 返空（该股无数据/新股）→ ([], None) 诚实返。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[]))
    bars, src = kr.fetch_kline("600519")
    assert bars == []
    assert src is None


def test_all_fail_returns_empty_honest(monkeypatch):
    """baostock 抛异常 → ([], None)，不抛、不臆造。"""
    monkeypatch.setattr(kr, "_baostock", _stub(exc=ConnectionError("baostock down")))
    bars, src = kr.fetch_kline("600519")
    assert bars == []
    assert src is None


def test_list_sources_order():
    """源链：只 baostock（本环境唯一可用源）。"""
    assert kr.list_sources() == ["baostock"]


def test_list_sources_by_adjust():
    """list_sources(adjust) 按口径筛选——qfq 返 baostock，none 返空。"""
    assert kr.list_sources(adjust="qfq") == ["baostock"]
    assert kr.list_sources(adjust="none") == []


def test_adjust_of_map():
    """各源原生口径声明（单一事实源）。"""
    assert kr.adjust_of("baostock") == "qfq"
    assert kr.adjust_of("unknown") is None


def test_adjust_qfq_returns_baostock(monkeypatch):
    """adjust='qfq' 命中 baostock。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519", adjust="qfq")
    assert src == "baostock"
    assert len(bars) == 1


def test_adjust_none_returns_empty_no_source(monkeypatch):
    """adjust='none' 无源（baostock 是 qfq）→ 诚实返空，不臆造复权因子。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1", "close": 999.0}]))
    bars, src = kr.fetch_kline("600519", adjust="none")
    assert bars == []
    assert src is None


def test_source_subset(monkeypatch):
    """sources 参数限定子集——['baostock'] 命中，['sina']（已删）返空。"""
    monkeypatch.setattr(kr, "_baostock", _stub(bars=[{"date": "d1"}]))
    bars, src = kr.fetch_kline("600519", sources=["baostock"])
    assert src == "baostock"
    bars, src = kr.fetch_kline("600519", sources=["sina"])  # 已删，不在 _SOURCES
    assert src is None
