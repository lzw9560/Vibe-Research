# -*- coding: utf-8 -*-
"""S008 东财源单测：monkeypatch em_get（transport）→ 锁委派不改行为。

东财端点走 data.transport.eastmoney_get（防封底线）；本测 patch 源模块的 em_get
别名，断言 market_turnover_rank / stock_fund_flow_120d 仍返原 shape 的 raw dict。
"""
from data.sources import eastmoney


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
    payload = {"data": {"klines": ["2026-07-29,1000,-500,200,300,800"]}}
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _FakeResp(payload))
    rows = eastmoney.stock_fund_flow_120d("600519")
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-07-29"
    assert r["main_net"] == 1000.0
    assert r["small_net"] == -500.0
    assert r["mid_net"] == 200.0
    assert r["large_net"] == 300.0
    assert r["super_net"] == 800.0


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
