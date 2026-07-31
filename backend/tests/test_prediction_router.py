"""Tests for routers.prediction — S017 T10 API surface.

Uses TestClient (no live network).  Snapshots are hand-built and stored via
cascade_store (no model training needed).
"""

from __future__ import annotations
import json

from fastapi.testclient import TestClient

import app as app_module
from predict.predict import Snapshot, cascade_store

client = TestClient(app_module.app)

_FORBIDDEN = ("买入", "卖出", "止损", "止盈", "荐股", "保证收益", "承诺收益")


# ── (a) intraday-framework ────────────────────────────────────────────


class TestIntradayFramework:
    def test_returns_checklist(self) -> None:
        r = client.get("/api/prediction/intraday-framework")
        assert r.status_code == 200
        body = r.json()
        assert body["stage"] == "s4"
        assert isinstance(body["items"], list) and body["items"]
        item = body["items"][0]
        for k in ("key", "label", "how_to_read", "reference", "current_value", "hint"):
            assert k in item
        assert item["current_value"] is None  # S008 pending, not fabricated

    def test_disclaimer_present(self) -> None:
        r = client.get("/api/prediction/intraday-framework")
        assert "不构成投资建议" in r.json()["disclaimer"]

    def test_no_forbidden_trade_words(self) -> None:
        r = client.get("/api/prediction/intraday-framework")
        text = json.dumps(r.json(), ensure_ascii=False)
        for w in _FORBIDDEN:
            assert w not in text, f"forbidden trade word in framework: {w}"


# ── (b) prediction endpoint ───────────────────────────────────────────


class TestPredictionEndpoint:
    def test_pending_when_no_snapshot(self) -> None:
        r = client.get("/api/prediction/short_sector?stage=s1&date=1999-01-01")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "no_snapshot"
        assert body["data"] is None
        assert "不构成投资建议" in body["disclaimer"]

    def test_returns_snapshot_when_present(self) -> None:
        snap = Snapshot(
            head="short_sector", stage="s1", t="2099-12-31", prob=0.6123,
            quantiles=(), shap_topk=(),
            features_used=("f0", "f1"), backends=("histgb", "catboost"),
            model_version="short_sector-v0",
        )
        cascade_store(snap)
        r = client.get("/api/prediction/short_sector?stage=s1&date=2099-12-31")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert abs(body["data"]["prob"] - 0.6123) < 1e-9
        assert body["data"]["features_used"] == ["f0", "f1"]
        assert "不构成投资建议" in body["disclaimer"]

    def test_invalid_stage_422(self) -> None:
        r = client.get("/api/prediction/short_sector?stage=s9")
        assert r.status_code == 422

    def test_unknown_head_404(self) -> None:
        r = client.get("/api/prediction/nope?stage=s1")
        assert r.status_code == 404
