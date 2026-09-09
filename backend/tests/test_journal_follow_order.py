# -*- coding: utf-8 -*-
"""S175 T10 — follow-order API + 4 源 gap（dormant）测试（R14/R15）。

TestClient（memory devserver-port-occupied-use-testclient）+ VR_DATA_DIR 隔离。
"""
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


def _insert_paper(tmp_path, net_pnl=80.0, entry_price=10.0):
    """插一条 trade_journal paper 记录，返 signal_id。"""
    from engine.trade_journal import TradeJournal, JournalRecord
    tj = TradeJournal(db_path=tmp_path / "trade_journal.db")
    paper = JournalRecord.create(
        arm="breakout", stock_code="000001", entry_price=entry_price, entry_date="2026-01-15",
        exit_price=11.0, exit_date="2026-01-19", exit_reason="max_hold",
        net_pnl=net_pnl, is_realized=1,
    )
    tj.insert(paper)
    return paper.signal_id


class TestFollowOrder:
    def test_post_follow_order_computes_gap(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        signal_id = _insert_paper(tmp_path, net_pnl=80.0, entry_price=10.0)
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app import app  # noqa: PLC0415
        client = TestClient(app)
        resp = client.post("/api/journal/follow-order", json={
            "signal_id": signal_id,
            "real_entry_price": 10.2,  # 滑点 0.2 vs paper entry 10.0
            "real_exit_price": 10.8,
            "real_exit_date": "2026-01-19",
            "real_shares": 100.0,
            "real_cost_pct": 0.70,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["paper_pnl"] == 80.0
        # real_pnl = (10.8-10.2)*100 - 0.70/100*(10.2*100) = 60 - 7.14 = 52.86
        assert data["real_pnl"] == pytest.approx(52.86, abs=0.15)
        # gap = real - paper = 52.86 - 80 = -27.14
        assert data["gap"] == pytest.approx(-27.14, abs=0.15)
        assert data["gap_breakdown"]["dormant"] is False
        # 滑点 gap = (10.2-10.0)*100 = 20.0
        assert data["gap_breakdown"]["slippage"] == pytest.approx(20.0, abs=0.01)

    def test_get_gap_returns_order_after_post(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        signal_id = _insert_paper(tmp_path)
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app import app  # noqa: PLC0415
        client = TestClient(app)
        client.post("/api/journal/follow-order", json={
            "signal_id": signal_id,
            "real_entry_price": 10.0,
            "real_exit_price": 11.0,
            "real_shares": 100.0,
        })
        resp = client.get(f"/api/journal/gap?signal_id={signal_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal_id"] == signal_id
        assert data["gap_breakdown"]["dormant"] is False

    def test_get_gap_no_follow_returns_dormant(self, tmp_path, monkeypatch):
        """未跟单 → no_follow + dormant 标激活条件不可达（R15）。"""
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app import app  # noqa: PLC0415
        client = TestClient(app)
        resp = client.get("/api/journal/gap?signal_id=unknown-signal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_follow"
        assert data["gap_breakdown"]["dormant"] is True
        assert "激活条件当前不可达" in data["gap_breakdown"]["dormant_reason"]

    def test_follow_order_idempotent_insert_or_replace(self, tmp_path, monkeypatch):
        """同 signal_id 重复 POST → INSERT OR REPLACE（非新行）。"""
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
        signal_id = _insert_paper(tmp_path)
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app import app  # noqa: PLC0415
        client = TestClient(app)
        # 第一次 POST
        client.post("/api/journal/follow-order", json={
            "signal_id": signal_id, "real_entry_price": 10.0, "real_exit_price": 11.0,
        })
        # 第二次 POST（不同 real_exit）→ 替换非新行
        resp = client.post("/api/journal/follow-order", json={
            "signal_id": signal_id, "real_entry_price": 10.0, "real_exit_price": 12.0,
        })
        assert resp.status_code == 200
        assert resp.json()["real_pnl"] == pytest.approx(200.0, abs=0.01)  # (12-10)*100
        # follow_orders.json 只 1 条（INSERT OR REPLACE）
        from routers.journal import _load_follow_orders  # noqa: PLC0415
        orders = _load_follow_orders()
        assert len(orders) == 1
