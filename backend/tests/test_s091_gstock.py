# -*- coding: utf-8 -*-
"""S091 gstock._push2_stock_get timeout 缩 5 + 限流 fast-fail + global_indices 部分缺失跳过。"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_push2_stock_get_timeout_is_5(monkeypatch):
    """S091：_push2_stock_get 传 em_get timeout=5（缩 10→5 限流 fast-fail）。"""
    import gstock

    calls: list = []

    def fake_em_get(url, params=None, headers=None, timeout=10):
        calls.append(timeout)
        return MagicMock(json=lambda: {"data": {"f58": "x"}})

    monkeypatch.setattr(gstock.astock, "em_get", fake_em_get)
    gstock._push2_stock_get("100.DJIA", "f43,f170")
    assert calls, "em_get 应被调用"
    assert calls[0] == 5, f"S091 timeout 应缩到 5，实={calls[0]}"


def test_push2_stock_get_none_on_all_fail(monkeypatch):
    """限流全失败（push2 + push2delay 都连不上）→ None，global_indices 跳过 missing。"""
    import gstock

    def boom(url, params=None, headers=None, timeout=10):
        raise ConnectionError("限流")

    monkeypatch.setattr(gstock.astock, "em_get", boom)
    assert gstock._push2_stock_get("100.DJIA", "f43,f170") is None


def test_push2_stock_get_latch_to_push2delay(monkeypatch):
    """push2 失败 → 降级 push2delay 取数据（_gs_host latch）。"""
    import gstock

    gstock._gs_host[0] = 0  # 重置从 push2 开始
    calls: list = []

    def fake_em_get(url, params=None, headers=None, timeout=10):
        calls.append(url)
        if "push2.eastmoney.com" in url:  # push2 失败
            raise ConnectionError("限流")
        return MagicMock(json=lambda: {"data": {"f58": "x"}})  # push2delay 成功

    monkeypatch.setattr(gstock.astock, "em_get", fake_em_get)
    d = gstock._push2_stock_get("100.DJIA", "f43,f170")
    assert d is not None  # push2delay 兜底取到
    assert gstock._gs_host[0] == 1  # latch 到 push2delay


def test_global_indices_skips_missing_returns_partial(monkeypatch):
    """global_indices 限流时返部分（道指取到 + 标普跳过 + SOX datacenter 兜底）。"""
    import gstock

    def fake_em_get(url, params=None, headers=None, timeout=10):
        secid = (params or {}).get("secid", "")
        if "100.DJIA" in secid:  # 道指取到
            return MagicMock(json=lambda: {"data": {"f43": 100, "f57": "DJI", "f58": "道琼斯", "f59": 2, "f170": 100}})
        raise ConnectionError("限流")  # 其他指数限流

    monkeypatch.setattr(gstock.astock, "em_get", fake_em_get)
    monkeypatch.setattr(gstock, "_fetch_sox_datacenter",
                        lambda: {"key": "sox", "name": "费城半导体", "region": "外围半导体", "price": 11738, "change_pct": -2.12})
    out = gstock.global_indices()
    keys = {i["key"] for i in out}
    assert "dji" in keys  # 道指取到
    assert "spx" not in keys  # 标普限流跳过（missing）
    assert "sox" in keys  # SOX datacenter 兜底
