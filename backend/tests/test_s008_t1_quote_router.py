# -*- coding: utf-8 -*-
"""S008 T1：/api/quote 返 S007 ``Quote`` 模型（response_model + mapper 投影）。

锁住 HTTP 响应为 Quote 序列化 shape：
- 新字段在：``last_close`` / ``turnover_rate`` / ``limit_up_price`` / ``limit_down_price``
  （前端 StockDeep/Watchlist 消费的更名/新增字段）；
- 旧字段名不在：``turnover_pct`` / ``limit_up`` / ``limit_down``（防前端读到旧名 undefined）。
"""
from fastapi.testclient import TestClient

import app as app_module
import astock

client = TestClient(app_module.app)


def _raw_quote():
    """模拟 astock.tencent_quote 的全字段 raw 输出（单一事实源）。"""
    return {"600519": {
        "name": "贵州茅台", "price": 1700.0, "last_close": 1680.0, "open": 1690.0,
        "change_pct": 2.3, "change_amt": 38.0, "amount_wan": 123456.0,
        "turnover_pct": 0.5, "pe_ttm": 30.0, "amplitude_pct": 3.2,
        "mcap_yi": 21000.0, "float_mcap_yi": 20900.0, "pb": 10.0,
        "limit_up": 1870.0, "limit_down": 1530.0, "vol_ratio": 2.1, "pe_static": 29.0,
    }}


def test_quote_endpoint_returns_quote_model(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")  # 测试关鉴权
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _raw_quote())

    r = client.get("/api/quote?codes=600519")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    q = body["data"]["600519"]
    # 新字段（前端消费的更名/新增）
    assert q["last_close"] == 1680.0
    assert q["turnover_rate"] == 0.5
    assert q["limit_up_price"] == 1870.0
    assert q["limit_down_price"] == 1530.0
    assert q["change_pct"] == 2.3
    assert q["price"] == 1700.0
    assert q["name"] == "贵州茅台"
    # 旧字段名不应出现（前端已更名，读到旧名会 undefined）
    for stale in ("turnover_pct", "limit_up", "limit_down"):
        assert stale not in q, f"旧字段 {stale} 不应出现在 Quote 响应"


def test_quote_endpoint_bad_codes(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    assert client.get("/api/quote?codes=abc").status_code == 400  # 非 6 位数字
