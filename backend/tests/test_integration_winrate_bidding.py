"""Quick integration check for winrate + bidding changes."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_winrate_records_post() -> None:
    payload = [
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "strategy_used": "涨停基因",
            "entry_date": "2025-01-02",
            "entry_price": 10.5,
            "exit_date": "2025-01-05",
            "exit_price": 11.0,
            "return_pct": 0.0476,
            "is_win": True,
            "gene_score": 80,
            "sti_label": "HIGH",
            "sector": "银行",
        }
    ]
    r = client.post("/api/winrate/records", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["added_count"] == 1
    assert data["error_count"] == 0
    print("winrate records post: ok")


def test_winrate_stats_after_insert() -> None:
    r = client.get("/api/winrate/stats?window_size=20")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total_trades"] >= 1
    print("winrate stats after insert: ok")


def test_bidding_monitor_endpoint() -> None:
    r = client.get("/api/auction/monitor")
    assert r.status_code == 200, r.text
    print("bidding monitor endpoint: ok")


def test_bidding_watchlist_endpoint() -> None:
    r = client.get("/api/auction/watchlist")
    assert r.status_code == 200, r.text
    print("bidding watchlist endpoint: ok")


if __name__ == "__main__":
    test_winrate_records_post()
    test_winrate_stats_after_insert()
    test_bidding_monitor_endpoint()
    test_bidding_watchlist_endpoint()
    print("all integration checks passed")
