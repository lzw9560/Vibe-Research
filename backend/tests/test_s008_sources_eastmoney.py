# -*- coding: utf-8 -*-
"""S008 东财源单测：monkeypatch em_get（transport）→ 锁委派不改行为。

东财端点走 data.transport.eastmoney_get（防封底线）；本测 patch 源模块的 em_get
别名，断言 market_turnover_rank / stock_fund_flow_120d 仍返原 shape 的 raw dict。
"""
from data.sources import eastmoney

import pytest


@pytest.fixture(autouse=True)
def _mock_sina_fund_flow_fallback(monkeypatch):
    """S109/bc197ca：stock_fund_flow_120d 东财双 host 失败/数据不足(<5条)时降级新浪。
    本测东财链路语义，mock 新浪 fallback 返 []（不联网 + 保"东财失败→空"旧断言）。
    东财成功路径（payload ≥5 条）不触发 fallback。"""
    monkeypatch.setattr(eastmoney, "_sina_fund_flow_fallback",
                        lambda code, num=120: [])


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def test_market_turnover_rank_shape(monkeypatch):
    payload = {"data": {"diff": [
        {"f12": "600519", "f14": "贵州茅台", "f2": 1700, "f3": 2.3,
         "f6": 12_000_000, "f20": 2e12, "f21": 1.5e12, "f100": "白酒"},
    ]}}
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _FakeResp(payload))
    rows = eastmoney.market_turnover_rank(5)
    assert len(rows) == 1
    r = rows[0]
    assert r["code"] == "600519"
    assert r["name"] == "贵州茅台"
    assert r["price"] == 1700.0
    assert r["pct"] == 2.3
    assert r["amount"] == 12_000_000.0
    assert r["mcap"] == 2e12
    assert r["float_cap"] == 1.5e12
    assert r["industry"] == "白酒"


def test_stock_fund_flow_120d_shape(monkeypatch):
    # push2his klines: "date,main,small,mid,large,super,..."
    # S109/bc197ca：≥5 条才算有效历史（<5 降级新浪），故给 5 条测 shape
    klines = ["2026-07-2%d,1000,-500,200,300,800" % d for d in (9, 8, 7, 6, 5)]
    payload = {"data": {"klines": klines}}
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _FakeResp(payload))
    rows = eastmoney.stock_fund_flow_120d("600519")
    assert len(rows) == 5
    r = rows[0]
    assert r["date"] == "2026-07-29"
    assert r["main_net"] == 1000.0
    assert r["small_net"] == -500.0
    assert r["mid_net"] == 200.0
    assert r["large_net"] == 300.0
    assert r["super_net"] == 800.0


def test_fund_flow_120d_first_host_ok_no_fallback(monkeypatch):
    """S049a R5：push2his 成功(≥5条) → 用首 host，不降级（em_get 只调 1 次）。"""
    hosts = []
    klines = ["2026-08-0%d,100,-50,20,30,80" % d for d in range(1, 6)]
    payload = {"data": {"klines": klines}}

    def fake_em_get(url, *a, **k):
        hosts.append(url)
        return _FakeResp(payload)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    rows = eastmoney.stock_fund_flow_120d("600519")
    assert len(rows) == 5
    assert len(hosts) == 1
    assert "push2his." in hosts[0]


def test_fund_flow_120d_fallback_to_push2delay(monkeypatch):
    """S049a R5：push2his 断连 + push2delay 成功(≥5条) → 用 push2delay（em_get 调 2 次）。"""
    hosts = []
    klines = ["2026-08-0%d,664611600,-1,2,3,4" % d for d in range(1, 6)]
    payload = {"data": {"klines": klines}}

    def fake_em_get(url, *a, **k):
        hosts.append(url)
        if "push2his." in url:
            raise ConnectionError("Max retries exceeded")
        return _FakeResp(payload)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    rows = eastmoney.stock_fund_flow_120d("600519")
    assert len(rows) == 5
    assert rows[0]["main_net"] == 664611600.0
    assert len(hosts) == 2
    assert "push2delay." in hosts[1]


def test_fund_flow_120d_empty_klines_falls_back(monkeypatch):
    """S049a/bc197ca：push2his 返空 klines → push2delay 返<5条不足 → 降级新浪。"""
    hosts = []
    # push2delay 返 1 条（<5）→ 视为不足，降级新浪（fixture mock 返 []）
    ok = {"data": {"klines": ["2026-08-08,5,5,5,5,5"]}}

    def fake_em_get(url, *a, **k):
        hosts.append(url)
        if "push2his." in url:
            return _FakeResp({"data": {"klines": []}})
        return _FakeResp(ok)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    rows = eastmoney.stock_fund_flow_120d("600519")
    # push2delay 1 条<5 → 降级新浪（mock []）→ 返 []
    assert rows == []
    assert len(hosts) == 2


def test_fund_flow_120d_both_hosts_fail_empty(monkeypatch):
    """S049a R4：两 host 都失败 → 空列表（现状行为，上层标 missing）。"""
    def fake_em_get(url, *a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    assert eastmoney.stock_fund_flow_120d("600519") == []


def test_em_zt_topic_pool_caches(monkeypatch):
    """同 (endpoint,date,sort) 二次调用不重复请求（24h 缓存）。"""
    eastmoney._ztb_cache.clear()
    calls = []
    payload = {"data": {"pool": [{"lbc": 3}]}}

    def fake_em_get(*a, **k):
        calls.append(1)
        return _FakeResp(payload)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    r1 = eastmoney.em_zt_topic_pool("getTopicZTPool", "20260729")
    r2 = eastmoney.em_zt_topic_pool("getTopicZTPool", "20260729")
    assert r1 == [{"lbc": 3}]
    assert r2 == [{"lbc": 3}]
    assert len(calls) == 1  # 缓存命中，只请求一次
