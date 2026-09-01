# -*- coding: utf-8 -*-
"""S135 A1/A2 — /api/global/stock 响应 data.quote.is_delayed 端到端（last-mile）。

覆盖 spec A1（字段存在）+ A2（push2delay 降级→true / push2 实时→false）。
mock _push2_stock_get（底层，注入 _is_delayed），让 _quote_from 层转换（_is_delayed→is_delayed）
+ us_hk_stock 包装 + global_stock_from_gstock + quote_from_gstock_us_hk + response_model 序列化
全链跑——端到端验 is_delayed 从 gstock 产出到 HTTP 响应不被剥离。

为何端到端而非仅 mapper 测：mapper 测（test_s008_mappers::quote_from_gstock_us_hk_passes_is_delayed）
已覆盖 mapper 透传，但不覆盖 _quote_from 的 _is_delayed→is_delayed 层转换 + response_model 序列化。
若 _quote_from 漏放 is_delayed、或 global_stock_from_gstock 重构不调 quote_from_gstock_us_hk、
或 response_model 剥离字段——mapper 测绿但端点响应丢字段。本测守住整链。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
import gstock

client = TestClient(app_module.app)


def _valid_info():
    return {"secid_prefix": "116", "code": "AAPL", "name": "Apple",
            "market": "US", "secucode": "116.AAPL"}


def _patch_gstock(monkeypatch, is_delayed: bool):
    """mock resolve_symbol + _push2_stock_get（注入 _is_delayed）+ _key_metrics（避 F10 网络）。"""
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(gstock, "resolve_symbol", lambda q: _valid_info())
    monkeypatch.setattr(gstock, "_push2_stock_get", lambda secid, fields: {
        "f57": "AAPL", "f58": "Apple", "f43": 18000, "f170": 50,
        "f48": 1e7, "f116": 3e12, "_is_delayed": is_delayed,
    })
    monkeypatch.setattr(gstock, "_key_metrics", lambda sc: None)


def test_global_stock_endpoint_is_delayed_true_on_push2delay(monkeypatch):
    """A1+A2：push2delay 降级（_is_delayed=True）→ 响应 data.quote.is_delayed===true。

    端到端：_push2_stock_get 注入 _is_delayed → _quote_from 层转 is_delayed → us_hk_stock
    包装 raw["quote"] → quote_from_gstock_us_hk 读 inner.is_delayed → Quote → response_model 序列化。
    """
    _patch_gstock(monkeypatch, is_delayed=True)
    r = client.get("/api/global/stock?symbol=AAPL")
    assert r.status_code == 200
    q = r.json()["data"]["quote"]
    assert "is_delayed" in q  # A1 字段存在（response_model 未剥离）
    assert q["is_delayed"] is True  # A2 push2delay 镜像→true


def test_global_stock_endpoint_is_delayed_false_on_push2_live(monkeypatch):
    """A2+A5：push2 实时（_is_delayed=False）→ is_delayed===false（不误标实时为延时）。"""
    _patch_gstock(monkeypatch, is_delayed=False)
    r = client.get("/api/global/stock?symbol=AAPL")
    assert r.status_code == 200
    q = r.json()["data"]["quote"]
    assert q["is_delayed"] is False
