# -*- coding: utf-8 -*-
"""S008 多源 kline 解析器单测：锁住职责链回退、子集、全失败诚实返空。

不依赖任何真实网络——monkeypatch 各源 fetch 函数注入成功/抛异常/返空，
验证解析器的回退顺序与诚实契约（不抛、不臆造，空返 ([], None)）。
"""
from data.sources import kline_resolver as kr


def _stub(name: str, bars=None, exc=None):
    """造一个源 stub：返 bars / 抛 exc / 返空。"""
    def fn(code):
        if exc:
            raise exc
        return bars or []
    return fn


def test_first_success_wins(monkeypatch):
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "baidu"
    assert len(bars) == 1


def test_fallback_on_exception(monkeypatch):
    """baidu 抛异常 → 回退 sina。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", exc=ConnectionError("banned")))
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d1", "close": 10.0}]))
    monkeypatch.setattr(kr, "_mootdx", _stub("mootdx"))
    monkeypatch.setattr(kr, "_akshare", _stub("akshare"))
    bars, src = kr.fetch_kline("600519")
    assert src == "sina"
    assert len(bars) == 1


def test_fallback_on_empty(monkeypatch):
    """baidu 返空（不限流但该股无数据）→ 回退 sina。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", bars=[]))
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d1"}]))
    bars, src = kr.fetch_kline("600519")
    assert src == "sina"


def test_all_fail_returns_empty_honest(monkeypatch):
    """全源失败 → ([], None)，不抛、不臆造。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", exc=ConnectionError("x")))
    monkeypatch.setattr(kr, "_sina", _stub("sina", exc=TimeoutError("x")))
    monkeypatch.setattr(kr, "_mootdx", _stub("mootdx", exc=RuntimeError("no dep")))
    monkeypatch.setattr(kr, "_akshare", _stub("akshare", bars=[]))
    bars, src = kr.fetch_kline("600519")
    assert bars == []
    assert src is None


def test_source_subset(monkeypatch):
    """sources 参数限定子集——跳过未选源。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", bars=[{"date": "d1"}]))
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d2"}]))
    bars, src = kr.fetch_kline("600519", sources=["sina"])
    assert src == "sina"   # baidu 被排除，直接命中 sina


def test_list_sources_order():
    """源链顺序：独立源在前，akshare 兜底。"""
    assert kr.list_sources() == ["baidu", "sina", "mootdx", "akshare"]


def test_list_sources_by_adjust():
    """list_sources(adjust) 按口径筛选——qfq 只返百度+akshare，none 返新浪+mootdx。"""
    assert kr.list_sources(adjust="qfq") == ["baidu", "akshare"]
    assert kr.list_sources(adjust="none") == ["sina", "mootdx"]


def test_adjust_of_map():
    """各源原生口径声明（单一事实源）。"""
    assert kr.adjust_of("baidu") == "qfq"
    assert kr.adjust_of("sina") == "none"
    assert kr.adjust_of("mootdx") == "none"
    assert kr.adjust_of("akshare") == "qfq"
    assert kr.adjust_of("unknown") is None


def test_adjust_qfq_skips_raw_sources(monkeypatch):
    """adjust='qfq' 时百度命中即返，**不**回退到新浪/mootdx（raw）——口径隔离。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", bars=[{"date": "d1", "close": 10.0}]))
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d1", "close": 999.0}]))
    monkeypatch.setattr(kr, "_mootdx", _stub("mootdx", bars=[{"date": "d1", "close": 999.0}]))
    monkeypatch.setattr(kr, "_akshare", _stub("akshare"))
    bars, src = kr.fetch_kline("600519", adjust="qfq")
    assert src == "baidu"
    assert len(bars) == 1


def test_adjust_qfq_falls_to_akshare_not_raw(monkeypatch):
    """百度抛异常 → 跳过新浪/mootdx（raw，口径不符）→ 命中 akshare（qfq）。
    关键：不回退 raw 源——混用口径会污染收益。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", exc=ConnectionError("banned")))
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d1", "close": 999.0}]))
    monkeypatch.setattr(kr, "_mootdx", _stub("mootdx", bars=[{"date": "d1", "close": 999.0}]))
    monkeypatch.setattr(kr, "_akshare", _stub("akshare", bars=[{"date": "d1", "close": 10.0}]))
    bars, src = kr.fetch_kline("600519", adjust="qfq")
    assert src == "akshare"   # sina/mootdx 被口径过滤掉，不是被试过再跳过


def test_adjust_qfq_no_source_returns_empty_honest(monkeypatch):
    """百度+akshare 都失败 → adjust='qfq' 诚实返空，**不**回退到 raw 源（新浪/mootdx 可用也不取）。
    不臆造复权因子重算 raw→qfq。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", exc=ConnectionError("x")))
    monkeypatch.setattr(kr, "_akshare", _stub("akshare", exc=ConnectionError("x")))
    # raw 源可用——但 adjust='qfq' 不应取它们
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d1", "close": 999.0}]))
    monkeypatch.setattr(kr, "_mootdx", _stub("mootdx", bars=[{"date": "d1", "close": 999.0}]))
    bars, src = kr.fetch_kline("600519", adjust="qfq")
    assert bars == []
    assert src is None


def test_adjust_none_uses_raw_sources(monkeypatch):
    """adjust='none' 只走 raw 源——百度（qfq）可用也跳过，命中新浪。"""
    monkeypatch.setattr(kr, "_baidu", _stub("baidu", bars=[{"date": "d1", "close": 10.0}]))
    monkeypatch.setattr(kr, "_sina", _stub("sina", bars=[{"date": "d1", "close": 11.0}]))
    bars, src = kr.fetch_kline("600519", adjust="none")
    assert src == "sina"


def test_adjust_with_sources_subset(monkeypatch):
    """sources + adjust 复合筛选：sources 限 akshare，adjust=qfq → 仍命中 akshare。
    sources 排除 akshare → adjust=qfq 无可用源返空。"""
    monkeypatch.setattr(kr, "_akshare", _stub("akshare", bars=[{"date": "d1", "close": 10.0}]))
    monkeypatch.setattr(kr, "_baidu", _stub("baidu"))
    bars, src = kr.fetch_kline("600519", sources=["akshare"], adjust="qfq")
    assert src == "akshare"
    bars, src = kr.fetch_kline("600519", sources=["sina"], adjust="qfq")
    assert src is None   # sina 是 none 口径，不在 qfq 筛选内
