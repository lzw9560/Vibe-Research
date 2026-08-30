# -*- coding: utf-8 -*-
"""S085 A6 残留 — topology stock_fund_flow_120d 传 date 单测。

bug：topology.py:104 `fetch_fn=lambda code, _d: astock.stock_fund_flow_120d(code)`——
_d（date）被签名忽略，replay（date=H）时取最新 120 日（含今日），extract_fn 取最近 N 日含今日→误。
修复：stock_fund_flow_120d 加可选 date 过滤 ≤date + topology 传 d（同 :170 dragon_tiger 传 d 范式）。

承重：topology 共享资金流边（≥3 天同向才连边）。replay 误取今日→边集合错。
fund_flow.py 走 A6 内部过滤不复用此参数；risk_models 实时取最新不传 date（实时风险对）。
"""
from __future__ import annotations

from unittest import mock

from data.sources import eastmoney
from routers import topology


class _FakeResp:
    def __init__(self, data): self._d = data
    def json(self): return self._d


def _kline_json(rows):
    """造 push2his fflow klines 返回（_parse_fflow_klines 解析格式）。"""
    klines = [f"{r['date']},{r['main_net']},0,0,0,0" for r in rows]
    return {"data": {"klines": klines}}


def test_stock_fund_flow_120d_filters_by_date(monkeypatch):
    """stock_fund_flow_120d(code, date=H) 过滤 flows ≤ H（修 replay 误取今日）。"""
    # bc197ca：≥5 条才算有效（<5 降级新浪），mock 新浪返 [] 让东财路径生效
    monkeypatch.setattr(eastmoney, "_sina_fund_flow_fallback", lambda code, num=120: [])
    rows = [
        {"date": "2026-08-10", "main_net": 0},  # 补足 5 条
        {"date": "2026-08-11", "main_net": 0},
        {"date": "2026-08-12", "main_net": 0},
        {"date": "2026-08-14", "main_net": 1e8},
        {"date": "2026-08-15", "main_net": 2e8},
        {"date": "2026-08-16", "main_net": 3e8},  # > as_of
        {"date": "2026-08-17", "main_net": 4e8},  # > as_of
    ]
    monkeypatch.setattr(eastmoney, "em_get",
                       lambda url, params=None, headers=None, timeout=15: _FakeResp(_kline_json(rows)))
    out = eastmoney.stock_fund_flow_120d("600519", date="2026-08-15")
    assert len(out) == 5  # 08-10~08-15 ≤ 08-15（共 5 条）
    assert all(r["date"] <= "2026-08-15" for r in out)


def test_stock_fund_flow_120d_no_date_returns_all(monkeypatch):
    """不传 date（fund_flow.py/risk_models/routers 用）→ 不过滤，既有行为。"""
    monkeypatch.setattr(eastmoney, "_sina_fund_flow_fallback", lambda code, num=120: [])
    # bc197ca：≥5 条才算有效，给 5 条
    rows = [{"date": "2026-08-%02d" % d, "main_net": d * 1e8} for d in range(10, 15)]
    monkeypatch.setattr(eastmoney, "em_get",
                       lambda url, params=None, headers=None, timeout=15: _FakeResp(_kline_json(rows)))
    out = eastmoney.stock_fund_flow_120d("600519")
    assert len(out) == 5  # 不过滤


def test_topology_fund_flow_passes_date_to_stock_fund_flow(monkeypatch):
    """topology FundFlowEdgeProvider.build_edges 传 date 给 stock_fund_flow_120d（修 _d 被忽略）。"""
    captured: dict = {}

    def fake_fflow(code, date=None):
        captured["code"] = code
        captured["date"] = date
        return [{"date": "2026-08-14", "main_net": 1e8}, {"date": "2026-08-15", "main_net": -5e7}]

    import astock
    monkeypatch.setattr(astock, "stock_fund_flow_120d", fake_fflow)
    # 构造候选 + build_edges
    provider = topology.FundFlowEdgeProvider() if hasattr(topology, "FundFlowEdgeProvider") else None
    if provider is None:
        # 找提供者类
        for name in dir(topology):
            obj = getattr(topology, name)
            if isinstance(obj, type) and hasattr(obj, "build_edges") and "fund" in name.lower():
                provider = obj()
                break
    assert provider is not None, "未找到 FundFlowEdgeProvider"
    edges = provider.build_edges(
        [{"code": "600519", "name": "X"}, {"code": "000001", "name": "Y"}],
        date="2026-08-15",
    )
    # 验 stock_fund_flow_120d 收到 date（不是被忽略）
    assert captured.get("date") == "2026-08-15", (
        f"topology 应传 date 给 stock_fund_flow_120d，实得 {captured.get('date')}"
    )
