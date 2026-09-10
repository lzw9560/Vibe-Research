# -*- coding: utf-8 -*-
"""S178 — OFI 盘中数据只读看板 router 测试（read-only，非信号）。

仿 journal router 测试范式（TestClient）。用例：
- 有数据返 11 字段
- 空 DB 返 {snapshots:[],count:0} 不崩
- 缺 date→422
- limit 越界→422（>10000 或 <1）
- code 过滤生效
- truncated 标记
- 不 import chat/ai.tools/trade_journal（防 signal-creep）
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture
def ofi_client(tmp_path, monkeypatch):
    """独立 OFI DB（tmp_path）+ TestClient。"""
    import data.intraday_accumulation_store as store
    monkeypatch.setattr(store, "_DB_PATH", str(tmp_path / "test_ofi.db"))
    from routers.intraday_ofi import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _save(tmp_path, monkeypatch, **kw):
    from data.intraday_accumulation_store import save_ofi
    save_ofi(**kw)


class TestOfiRouter:
    def test_returns_snapshots_with_11_fields(self, ofi_client, tmp_path, monkeypatch):
        _save(tmp_path, monkeypatch, date="2026-09-10", ts="10:30", code="000001",
              ofi=0.333, ofi_abs=290.0, bid_ask_pressure=2.0,
              buy_vols_json="[100,200]", sell_vols_json="[50,100]",
              seal_amount=None, regime="strong_trend")
        resp = ofi_client.get("/api/intraday/ofi?date=2026-09-10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["truncated"] is False
        assert body["date"] == "2026-09-10"
        s = body["snapshots"][0]
        assert s["code"] == "000001"
        assert s["ofi"] == pytest.approx(0.333, abs=0.01)
        assert s["regime"] == "strong_trend"
        for k in ("date", "ts", "code", "ofi", "ofi_abs", "bid_ask_pressure",
                  "buy_vols_json", "sell_vols_json", "seal_amount", "regime", "snapshot_at"):
            assert k in s, f"缺字段 {k}"

    def test_empty_db_returns_empty_not_500(self, ofi_client):
        resp = ofi_client.get("/api/intraday/ofi?date=2026-09-10")
        assert resp.status_code == 200
        assert resp.json() == {"snapshots": [], "count": 0, "date": "2026-09-10", "truncated": False}

    def test_missing_date_returns_422(self, ofi_client):
        assert ofi_client.get("/api/intraday/ofi").status_code == 422

    def test_limit_out_of_range_returns_422(self, ofi_client):
        assert ofi_client.get("/api/intraday/ofi?date=2026-09-10&limit=200000").status_code == 422
        assert ofi_client.get("/api/intraday/ofi?date=2026-09-10&limit=0").status_code == 422

    def test_code_filter(self, ofi_client, tmp_path, monkeypatch):
        _save(tmp_path, monkeypatch, date="2026-09-10", ts="10:30", code="000001",
              ofi=0.3, ofi_abs=100, bid_ask_pressure=1.5,
              buy_vols_json="[]", sell_vols_json="[]", seal_amount=None, regime=None)
        _save(tmp_path, monkeypatch, date="2026-09-10", ts="10:30", code="000002",
              ofi=0.5, ofi_abs=200, bid_ask_pressure=2.0,
              buy_vols_json="[]", sell_vols_json="[]", seal_amount=None, regime=None)
        resp = ofi_client.get("/api/intraday/ofi?date=2026-09-10&code=000001")
        body = resp.json()
        assert body["count"] == 1
        assert body["snapshots"][0]["code"] == "000001"

    def test_truncated_flag(self, ofi_client, tmp_path, monkeypatch):
        for i in range(5):
            _save(tmp_path, monkeypatch, date="2026-09-10", ts="10:30", code=f"{i:06d}",
                  ofi=0.1, ofi_abs=10.0, bid_ask_pressure=1.0,
                  buy_vols_json="[]", sell_vols_json="[]", seal_amount=None, regime=None)
        resp = ofi_client.get("/api/intraday/ofi?date=2026-09-10&limit=2")
        body = resp.json()
        assert body["count"] == 2
        assert body["truncated"] is True

    def test_no_ai_or_trade_journal_import(self):
        """A6: router 不 import chat/ai.tools/trade_journal（防 signal-creep）。"""
        import inspect
        import routers.intraday_ofi as mod
        src = inspect.getsource(mod)
        assert "import chat" not in src
        assert "from ai.tools" not in src
        assert "trade_journal" not in src
