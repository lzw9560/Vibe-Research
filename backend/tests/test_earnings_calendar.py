"""S216 P2 EarningsCalendar /api/earnings-calendar 聚合 endpoint 测试。

聚合 per-code announcements + lockup_expiry，按 deadline 排序 + 未披露预警。
DANGER_MONTHS 是监管强制披露窗口（1.31/4.30/8.31）公开知识非臆造。
守工程底线：不臆造/私有数据隔离/em_get 防封。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402


def _client() -> TestClient:
    """TestClient with isolated app (no live network, no scheduler)."""
    import app as app_mod  # noqa: PLC0415
    return TestClient(app_mod.app)


def test_returns_danger_months() -> None:
    """返 3 个监管强制披露窗口（1/4/8 月），公开知识非臆造。"""
    client = _client()
    r = client.get("/api/earnings-calendar")
    assert r.status_code == 200
    data = r.json()["data"]
    months = data["danger_months"]
    assert len(months) == 3
    assert {m["month"] for m in months} == {1, 4, 8}
    for m in months:
        assert m["deadline"]
        assert m["reason"]
        assert m["label"]


def test_no_codes_returns_calendar_only() -> None:
    """无 codes 参数 → 返日历结构，无 per_code 聚合（不臆造 per-code 数据）。"""
    client = _client()
    r = client.get("/api/earnings-calendar")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["danger_months"]
    assert data.get("per_code") is None or data.get("per_code") == []
    assert data["data_status"] in ("ok", "empty")
    assert "note" in data


def test_with_codes_aggregates_per_code(monkeypatch) -> None:
    """提供 codes → per_code 聚合 announcements + lockup_expiry。"""
    def _fake_announcements(code: str, limit: int = 15):
        return [{"date": "2026-04-25", "title": f"{code} 年报", "type": "财报"}]

    def _fake_lockup(code: str, trade_date=None, forward_days=90, raise_on_failure=False):
        return {
            "history": [],
            "upcoming": [{"date": "2026-05-10", "type": "定增", "shares": 1000, "able_shares": 1000, "ratio": 0.1}],
        }

    # 防止真 em_get 裸调（em_get 防封底线）—— patch 掉确保测试不触网
    import data.sources.eastmoney as em_mod
    monkeypatch.setattr(em_mod, "em_get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("em_get 不该裸调")))
    import astock
    monkeypatch.setattr(astock, "announcements", _fake_announcements)
    monkeypatch.setattr(astock, "lockup_expiry", _fake_lockup)

    client = _client()
    r = client.get("/api/earnings-calendar?codes=600519,000001")
    assert r.status_code == 200
    data = r.json()["data"]
    per_code = data["per_code"]
    assert len(per_code) == 2
    assert per_code[0]["code"] == "600519"
    assert per_code[0]["announcements"]
    assert per_code[0]["lockup_expiries"]
    assert per_code[0]["data_status"] == "ok"


def test_partial_data_honest(monkeypatch) -> None:
    """某 code fetch 失败 → data_status=partial，其他 ok，不 crash 不臆造。"""
    def _fake_announcements(code: str, limit: int = 15):
        if code == "000001":
            raise RuntimeError("东财源断")
        return [{"date": "2026-04-25", "title": "年报"}]

    def _fake_lockup(code: str, trade_date=None, forward_days=90, raise_on_failure=False):
        if code == "000001":
            raise RuntimeError("东财源断")
        return {"history": [], "upcoming": []}

    import astock
    monkeypatch.setattr(astock, "announcements", _fake_announcements)
    monkeypatch.setattr(astock, "lockup_expiry", _fake_lockup)

    client = _client()
    r = client.get("/api/earnings-calendar?codes=600519,000001")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["data_status"] == "partial"
    per_code = data["per_code"]
    by_code = {p["code"]: p for p in per_code}
    assert by_code["600519"]["data_status"] == "ok"
    assert by_code["000001"]["data_status"] == "missing"


def test_invalid_codes_rejected() -> None:
    """非法 code 格式 → 400（输入验证，fail fast）。"""
    client = _client()
    r = client.get("/api/earnings-calendar?codes=abc,123")
    assert r.status_code == 400
