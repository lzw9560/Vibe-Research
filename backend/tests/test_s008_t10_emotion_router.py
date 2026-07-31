# -*- coding: utf-8 -*-
"""S008 T10：/api/market/emotion 返 EmotionResponse（clean Emotion + lianban_stocks 并列）。"""
from fastapi.testclient import TestClient

import app as app_module
import market

client = TestClient(app_module.app)


def _raw_emotion():
    return {
        "date": "2026-07-30", "zt_count": 50, "dt_count": 5, "zb_count": 10,
        "max_boards": 7, "lianban_count": 30, "yzt_count": 40,
        "seal_rate": 0.7, "break_rate": 0.2, "promotion_rate": 0.3,
        "ladder": [{"boards": 2, "count": 10, "plus": False}],
        "lianban_stocks": [
            {"code": "600001", "name": "甲", "boards": 3, "price": 10.0, "pct": 10.0,
             "amount": 1e8, "float_cap": 5e9, "industry": "X"},
        ],
    }


def test_emotion_endpoint_emotion_response(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _raw_emotion())

    r = client.get("/api/market/emotion")
    assert r.status_code == 200
    d = r.json()["data"]
    # 顶层并列出口
    assert d["date"] == "2026-07-30"
    assert d["lianban_count"] == 30
    assert d["lianban_stocks"][0]["code"] == "600001"
    assert d["lianban_stocks"][0]["name"] == "甲"
    # emotion 子对象：clean（无 lianban_stocks）+ 字段更名
    e = d["emotion"]
    assert e["limit_up_count"] == 50      # zt_count→limit_up_count
    assert e["limit_down_count"] == 5     # dt_count→limit_down_count
    assert e["max_boards"] == 7
    assert e["seal_rate"] == 0.7
    assert e["broken_rate"] == 0.2        # break_rate→broken_rate
    assert e["advance_rate"] == 0.3       # promotion_rate→advance_rate
    assert "lianban_stocks" not in e       # Emotion 聚合零个股名
    # 旧字段名不在
    for stale in ("zt_count", "dt_count", "break_rate", "promotion_rate"):
        assert stale not in d
        assert stale not in e


def test_emotion_endpoint_empty_safe(monkeypatch):
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: {})
    r = client.get("/api/market/emotion")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["lianban_stocks"] == []
    assert d["emotion"]["limit_up_count"] is None
