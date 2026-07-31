# -*- coding: utf-8 -*-
"""S020 P4 market 全球宏观/地缘分块单测。monkeypatch worldmonitor，零网络。"""
import market


def _mcp(payload):
    """把裸 dict/list 包成 MCP tools/call 响应（content text = json）。"""
    import json
    return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _patch_wm(monkeypatch, market_rows=None, cii=None, hotspots=None):
    from data.sources import worldmonitor as wm
    monkeypatch.setattr(wm, "fetch_market_data", lambda jmespath=None: _mcp(market_rows or []))
    monkeypatch.setattr(wm, "fetch_country_risk", lambda jmespath=None: _mcp(cii or {}))
    monkeypatch.setattr(wm, "fetch_hotspot_escalation", lambda jmespath=None: _mcp(hotspots or {}))


def test_get_global_macro_partitions(monkeypatch):
    rows = [
        {"symbol": "CL", "price": "80.5"},
        {"symbol": "XAU", "price": "2400"},
        {"symbol": "DXY", "price": "120.7"},
        {"symbol": "USDCNH", "price": "7.2"},
        {"symbol": "FOO", "price": "1"},  # 不属商品/外汇，过滤掉
    ]
    _patch_wm(monkeypatch, rows, {"countries": [{"country": "US", "cii": "85"}]},
              {"hotspots": [{"name": "Mideast", "level": "high"}]})
    out = market.get_global_macro()
    assert out["available"] is True
    assert len(out["commodities"]) == 2  # CL, XAU
    assert len(out["fx"]) == 2  # DXY, USDCNH
    assert out["cii"]["source"] == "worldmonitor_composite"
    assert len(out["hotspots"]) == 1


def test_get_global_macro_unreachable_degrades(monkeypatch):
    """worldmonitor 全 None → available=False，空子块，不抛。"""
    _patch_wm(monkeypatch, None, None, None)
    out = market.get_global_macro()
    assert out["available"] is False
    assert out["commodities"] == [] and out["fx"] == []
    assert out["source"] == "worldmonitor"
