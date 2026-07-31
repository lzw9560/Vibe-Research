# -*- coding: utf-8 -*-
"""S008 T9：/api/global/stock 返扁平 Quote（嵌套→扁平）+ GlobalMetrics。"""
from fastapi.testclient import TestClient

import app as app_module
import gstock

client = TestClient(app_module.app)


def _raw_us_hk():
    return {
        "code": "AAPL", "name": "苹果", "market": "NASDAQ",
        "quote": {"price": 185.0, "open": 186.0, "high": 188.0, "low": 184.0,
                  "prev_close": 182.0, "amount": 1.2e9, "mcap": 2.8e12, "change_pct": 1.5},
        "metrics": {"report_date": "2025-12-31", "revenue": 3e11, "eps": 6.5,
                    "roe": 0.4, "gross_margin": 0.46},
    }


def test_global_stock_flat_quote_and_metrics(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(gstock, "us_hk_stock", lambda symbol: _raw_us_hk())

    r = client.get("/api/global/stock?symbol=AAPL")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["code"] == "AAPL"
    assert d["market"] == "NASDAQ"
    q = d["quote"]
    # 扁平 + rename：amount→turnover、mcap→market_cap、prev_close→last_close
    assert q["price"] == 185.0
    assert q["turnover"] == 1.2e9
    assert q["market_cap"] == 2.8e12
    assert q["last_close"] == 182.0
    assert "amount" not in q and "mcap" not in q and "prev_close" not in q
    m = d["metrics"]
    assert m["eps"] == 6.5
    assert m["roe"] == 0.4


def test_global_stock_404_on_empty(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(gstock, "us_hk_stock", lambda symbol: {})
    assert client.get("/api/global/stock?symbol=ZZZ").status_code == 404


def test_global_stock_kr_metrics_null(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    raw = _raw_us_hk()
    raw["market"] = "KR"
    raw["metrics"] = None
    monkeypatch.setattr(gstock, "us_hk_stock", lambda symbol: raw)
    d = client.get("/api/global/stock?symbol=005930.KS").json()["data"]
    assert d["metrics"] is None
    assert d["quote"]["price"] == 185.0  # 行情仍在
