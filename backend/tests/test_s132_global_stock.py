# -*- coding: utf-8 -*-
"""S132 R1 — query_global_stock 源断诚实化测试。

契约（spec §3 R1.4）：
- ① _push2_stock_get 返 None（双 host 全挂）+ valid symbol → GlobalStock.quote_status='unavailable'
- ② 正常 → quote_status=None
- ③ invalid symbol → {}（resolve_symbol 失败，原行为不破）
"""
from __future__ import annotations

import gstock
from data import mappers


def _valid_info():
    return {"secid_prefix": "116", "code": "AAPL", "name": "Apple",
            "market": "US", "secucode": "116.AAPL"}


def test_quote_status_unavailable_on_source_failure(monkeypatch):
    """① 双 host 全挂（_push2_stock_get None）+ valid symbol → quote_status='unavailable'."""
    monkeypatch.setattr(gstock, "resolve_symbol", lambda q: _valid_info())
    monkeypatch.setattr(gstock, "_push2_stock_get", lambda secid, fields: None)  # 源断
    monkeypatch.setattr(gstock, "_key_metrics", lambda sc: None)  # avoid F10 fetch

    raw = gstock.us_hk_stock("AAPL")
    assert raw["quote_status"] == "unavailable"
    assert raw["quote"]["price"] is None  # null quote shape preserved

    gs = mappers.global_stock_from_gstock(raw)
    assert gs.quote_status == "unavailable"
    assert gs.code == "AAPL"


def test_quote_status_none_on_success(monkeypatch):
    """② 正常取数 → quote_status=None（不标）。"""
    monkeypatch.setattr(gstock, "resolve_symbol", lambda q: _valid_info())
    monkeypatch.setattr(gstock, "_push2_stock_get", lambda secid, fields: {
        "f57": "AAPL", "f58": "Apple", "f43": 18000, "f170": 50,  # 东财原始字段
        "f48": 1e7, "f116": 3e12, "_is_delayed": False,
    })
    monkeypatch.setattr(gstock, "_key_metrics", lambda sc: None)

    raw = gstock.us_hk_stock("AAPL")
    assert raw["quote_status"] is None
    assert raw["quote"]["price"] == 180.0  # f43/100 真值

    gs = mappers.global_stock_from_gstock(raw)
    assert gs.quote_status is None


def test_invalid_symbol_returns_empty(monkeypatch):
    """③ invalid symbol → {}（resolve_symbol 失败，原行为不破，无 quote_status）。"""
    monkeypatch.setattr(gstock, "resolve_symbol", lambda q: None)
    raw = gstock.us_hk_stock("BOGUS")
    assert raw == {}
