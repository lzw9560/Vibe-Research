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


# ── S220 P0-2 follow-up: _akshare feed eastmoney breaker（防封底线 §1.2）─────
# 根因：ak.stock_zh_a_hist 裸连东财 push2his 不走 em_get，失败不 feed breaker
# → breaker 永不 OPEN → :66 guard 永不触发 → 每只股都裸发东财请求加剧封禁
# （日志 2026-09-20 akshare failed RemoteDisconnected 每只股一次）。修：exception-only
# 契约对齐 sina.fetch_raw R7——失败 record_failure + re-raise，返 df record_success。

import pytest  # noqa: E402


class _FakeBreaker:
    """镜像 test_s134_sina_breaker._FakeBreaker：记 success/failure 计数。"""

    def __init__(self, allow: bool = True):
        self._allow = allow
        self.failures = 0
        self.successes = 0

    def allow_request(self) -> bool:
        return self._allow

    def record_success(self) -> None:
        self.successes += 1

    def record_failure(self) -> None:
        self.failures += 1


def test_akshare_failure_feeds_eastmoney_breaker(monkeypatch):
    """_akshare 网络异常 → record_failure + re-raise（exception-only，对齐 sina R7）。

    breaker 累积失败 5 次 OPEN 后 guard skip 不发请求——防裸连加剧封禁。
    """
    breaker = _FakeBreaker()
    monkeypatch.setattr("circuit_breaker.get_breaker", lambda name: breaker)

    class _FakeAk:
        def stock_zh_a_hist(self, **kw):
            raise ConnectionError("RemoteDisconnected")

    monkeypatch.setattr("data.sources.akshare_src._akshare", lambda: _FakeAk())
    with pytest.raises(ConnectionError):
        kr._akshare("600519")
    assert breaker.failures == 1
    assert breaker.successes == 0


def test_akshare_success_records_breaker_success(monkeypatch):
    """_akshare 返空 df（东财响应无数据）→ record_success 重置 failure_count。

    exception-only 契约：空 df 不是异常（东财 HTTP 200 响应了），算成功。
    """
    import pandas as pd  # noqa: PLC0415 — 测试 stub
    breaker = _FakeBreaker()
    monkeypatch.setattr("circuit_breaker.get_breaker", lambda name: breaker)

    class _FakeAk:
        def stock_zh_a_hist(self, **kw):
            return pd.DataFrame()

    monkeypatch.setattr("data.sources.akshare_src._akshare", lambda: _FakeAk())
    bars = kr._akshare("600519")
    assert bars == []
    assert breaker.successes == 1
    assert breaker.failures == 0


def test_akshare_breaker_open_skips_no_request(monkeypatch):
    """breaker OPEN → _akshare guard skip 返空，**不**调 stock_zh_a_hist（防封）。

    guard 拦截在 stock_zh_a_hist 之前，不发东财请求——这是 feed breaker 的收益：
    5 次失败 OPEN 后后续全 skip，不裸连。
    """
    breaker = _FakeBreaker(allow=False)
    monkeypatch.setattr("circuit_breaker.get_breaker", lambda name: breaker)
    called = []

    class _FakeAk:
        def stock_zh_a_hist(self, **kw):
            called.append("should_not_call")
            raise AssertionError("breaker OPEN 不应发 stock_zh_a_hist 请求")

    monkeypatch.setattr("data.sources.akshare_src._akshare", lambda: _FakeAk())
    bars = kr._akshare("600519")
    assert bars == []
    assert called == []
