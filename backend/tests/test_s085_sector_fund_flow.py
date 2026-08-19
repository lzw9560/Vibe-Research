# -*- coding: utf-8 -*-
"""S085 A5 — 板块资金 em_get 防封单测。

bug：market._sectors() 裸调 akshare.stock_fund_flow_industry（打同花顺 dataapi.10jqka.com.cn，
raw requests 无熔断）——同花顺封 IP 风险。
修复：换源东财 push2 clist 行业板块（fs=m:90+t:2, fid=f62 净额）走 em_get + 双 host 降级
（push2→push2delay）。

probe 证实（2026-08-19 live）：
- akshare 打同花顺（非东财），§1.2 东财 scope 不强制——A5 是防封工程改进，非选股 bug。
- 东财 push2 直连断（RemoteDisconnected），push2delay 可达（双 host 降级必要）。
- 东财行业板块无 inflow/outflow 字段（只有 f62 净额 + f104/f105 涨跌家数）。
- sector_net_inflow/inflow/outflow 全 dead fields（无下游消费，含前端）→ 换源丢 inflow/outflow 无影响。
单位：东财 f62（元）→ net/1e8（亿），与 akshare 净额（亿）同单位。
"""
from __future__ import annotations

import pytest

from data.sources import eastmoney


class _FakeResp:
    def __init__(self, data): self._data = data
    def json(self): return self._data


def test_sector_fund_flow_dual_host_fallback(monkeypatch):
    """push2 断 → 降级 push2delay 成功（market_turnover_rank 双 host 范式）。"""
    calls: list = []
    def fake_em_get(url, params=None, headers=None, timeout=15):
        calls.append(url)
        if "push2delay.eastmoney.com" not in url and "push2.eastmoney.com" in url:
            raise Exception("push2 down (RemoteDisconnected)")
        return _FakeResp({"data": {"diff": [
            {"f12": "BK0437", "f14": "煤炭", "f3": 1.66, "f62": 1179380208.0, "f104": 21, "f105": 13}
        ]}})
    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    rows = eastmoney.sector_fund_flow()
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "煤炭"
    assert r["pct"] == 1.66
    assert r["net"] == round(1179380208.0 / 1e8, 2)  # 11.79 亿
    assert r["firms"] == 34  # f104+f105
    assert r["inflow"] is None  # 东财无此字段（dead field 保形状）
    assert r["outflow"] is None
    # 验双 host 降级
    assert any("push2.eastmoney.com" in u for u in calls)
    assert any("push2delay.eastmoney.com" in u for u in calls)


def test_sector_fund_flow_push2_ok_no_fallback(monkeypatch):
    """push2 直连成功时不降级 push2delay（首非空 host 即用）。"""
    def fake_em_get(url, params=None, headers=None, timeout=15):
        if "push2delay" in url:
            pytest.fail("push2 成功不应降级 push2delay")
        return _FakeResp({"data": {"diff": [
            {"f14": "煤炭", "f3": 1.0, "f62": 1e9, "f104": 10, "f105": 5}
        ]}})
    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    rows = eastmoney.sector_fund_flow()
    assert rows[0]["net"] == round(1e9 / 1e8, 2)  # 10 亿


def test_sector_fund_flow_empty_when_both_hosts_fail(monkeypatch):
    """双 host 都断 → 返空（不臆造，不抛）。"""
    def fake_em_get(url, **kw): raise Exception("all down")
    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    assert eastmoney.sector_fund_flow() == []


def test_sector_fund_flow_handles_missing_fields(monkeypatch):
    """字段缺失（None/'-'）→ 数值 0 / firms 0（不崩，不臆造）。"""
    monkeypatch.setattr(eastmoney, "em_get", lambda url, **kw: _FakeResp({"data": {"diff": [
        {"f14": "某板块", "f3": None, "f62": "-", "f104": None, "f105": None}
    ]}}))
    rows = eastmoney.sector_fund_flow()
    assert rows[0]["name"] == "某板块"
    assert rows[0]["pct"] == 0.0
    assert rows[0]["net"] == 0.0
    assert rows[0]["firms"] == 0
