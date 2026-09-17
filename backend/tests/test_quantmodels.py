"""S216 P2 QuantModels M2/M4 endpoint test——/api/expectation-gap + /api/transport/em-health。

守工程底线：缺数据返 data_status='empty' 不臆造；M4 只报 circuit_breaker 状态不裸调东财（em_get 防封）。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_mod  # noqa: E402

client = TestClient(app_mod.app)


def test_m2_expectation_gap_returns_score(monkeypatch):
    """M2 /api/expectation-gap 返 score + gap_pct + vol_ratio + data_status。"""
    fake_bars = [
        {"date": "2026-09-16", "close": 10.0, "open": 10.0, "volume": 100},
        {"date": "2026-09-17", "close": 11.0, "open": 10.5, "volume": 200},
    ]
    monkeypatch.setattr(
        "engine.bars_provider.KlineCacheBarsProvider.__call__",
        lambda self, code: fake_bars,
    )
    r = client.get("/api/expectation-gap", params={"code": "600519", "date": "2026-09-17"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["code"] == "600519"
    assert d["date"] == "2026-09-17"
    assert d["data_status"] == "ok"
    assert d["score"] > 0
    assert d["gap_pct"] == 5.0
    assert d["vol_ratio"] == 2.0


def test_m2_missing_code_returns_422():
    """M2 缺 code 参数返 422（FastAPI validation）。"""
    r = client.get("/api/expectation-gap")
    assert r.status_code == 422


def test_m2_empty_bars_returns_empty_status(monkeypatch):
    """M2 bars 不足返 data_status=empty 不臆造 score。"""
    monkeypatch.setattr(
        "engine.bars_provider.KlineCacheBarsProvider.__call__",
        lambda self, code: [],
    )
    r = client.get("/api/expectation-gap", params={"code": "000001"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["data_status"] == "empty"
    assert d["score"] == 0.0
    assert d["gap_pct"] is None


def test_m2_compute_exception_returns_error_status(monkeypatch):
    """M2 计算异常返 data_status=error 不 crash（honest 降级）。"""
    def boom(self, code):
        raise RuntimeError("boom")
    monkeypatch.setattr(
        "engine.bars_provider.KlineCacheBarsProvider.__call__", boom
    )
    r = client.get("/api/expectation-gap", params={"code": "000001"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["data_status"] == "error"
    assert d["score"] == 0.0


def test_m4_em_health_returns_breakers(monkeypatch):
    """M4 /api/transport/em-health 返 breakers + all_healthy=True。"""
    fake_breaker = SimpleNamespace(
        peek_state=lambda: SimpleNamespace(value="closed"),
        failure_count=0,
    )
    monkeypatch.setattr(
        "circuit_breaker.list_breakers",
        lambda: {"eastmoney": fake_breaker},
    )
    r = client.get("/api/transport/em-health")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["data_status"] == "ok"
    assert "eastmoney" in d["breakers"]
    assert d["breakers"]["eastmoney"]["state"] == "closed"
    assert d["all_healthy"] is True


def test_m4_no_breakers_returns_empty(monkeypatch):
    """M4 无 breaker 返 data_status=empty 不臆造。"""
    monkeypatch.setattr("circuit_breaker.list_breakers", lambda: {})
    r = client.get("/api/transport/em-health")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["data_status"] == "empty"
    assert d["breakers"] == {}


def test_m4_open_breaker_reports_unhealthy(monkeypatch):
    """M4 有 open breaker → all_healthy=False。"""
    fake_open = SimpleNamespace(
        peek_state=lambda: SimpleNamespace(value="open"),
        failure_count=5,
    )
    monkeypatch.setattr(
        "circuit_breaker.list_breakers",
        lambda: {"eastmoney_push2": fake_open},
    )
    r = client.get("/api/transport/em-health")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["all_healthy"] is False
    assert d["breakers"]["eastmoney_push2"]["state"] == "open"
    assert d["breakers"]["eastmoney_push2"]["failure_count"] == 5
