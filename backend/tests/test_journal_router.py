"""S149 Phase 3 P3-T5d — 交易日志 + 个人风控路由端点测试。

TestClient（同进程，新代码）+ VR_DATA_DIR tmp 隔离 + mock 网络（em_zt_topic_pool/
kline_multi/get_daily_review）。覆盖 journal 7 + risk 9 端点契约 + 与既有
routers/risk.py 市场级端点无碰撞。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # mock 网络：journal._stock_context（em_zt_topic_pool）+ _market_context（get_daily_review）
    # + excursion.bars（kline_multi）
    import journal
    monkeypatch.setattr(journal, "get_daily_review",
                        lambda d: {"date": d, "sti_phase": "发酵",
                                   "money_effect_median": 5.01, "zt_total": 39})
    monkeypatch.setattr(journal.astock, "em_zt_topic_pool",
                        lambda endpoint, date, sort="fbt:asc", raise_on_failure=False: [])
    import excursion
    monkeypatch.setattr(excursion.astock, "kline_multi", lambda code: ([], None))
    import app
    return TestClient(app.app)


def _add_body(code="605398", fills=None):
    return {
        "date": "2026-09-03", "code": code, "name": "新炬网络", "playbook": "打板",
        "fills": fills or [{"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100}],
        "planned_stop": 9.0,
    }


# ───────────────────────── journal CRUD ─────────────────────────
def test_journal_add_list_update_delete(client):
    # add
    r = client.post("/api/journal/add", json=_add_body())
    assert r.status_code == 200, r.text
    tid = r.json()["trade"]["id"]
    # list
    r = client.get("/api/journal/list")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    # update（补卖出）
    r = client.post("/api/journal/update", params={"trade_id": tid},
                    json={"fills": [{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100},
                                    {"side": "sell", "date": "2026-09-04", "price": 12, "shares": 100}]})
    assert r.status_code == 200, r.text
    assert r.json()["trade"]["settled"]["realized_pnl"] == 189.38
    # delete
    r = client.post("/api/journal/delete", params={"trade_id": tid})
    assert r.status_code == 200
    assert r.json()["removed"] == 1
    assert client.get("/api/journal/list").json()["total"] == 0


def test_journal_add_validates_playbook(client):
    r = client.post("/api/journal/add", json={**_add_body(), "playbook": "非打法"})
    assert r.status_code == 400


def test_journal_stats_empty(client):
    r = client.get("/api/journal/stats")
    assert r.status_code == 200
    assert r.json()["available"] is False


# ───────────────────────── journal fees ─────────────────────────
def test_journal_fees_get_default(client):
    r = client.get("/api/journal/fees")
    assert r.status_code == 200
    assert r.json()["is_default"] is True


def test_journal_fees_save(client):
    r = client.post("/api/journal/fees",
                    json={"commission_rate": 0.0003, "commission_min": 1.0})
    assert r.status_code == 200
    assert r.json()["fees"]["is_default"] is False
    assert client.get("/api/journal/fees").json()["commission_rate"] == 0.0003


# ───────────────────────── risk 端点 ─────────────────────────
def test_risk_rules_get_default(client):
    r = client.get("/api/risk/rules")
    assert r.status_code == 200
    assert r.json()["_is_default"] is True
    assert r.json()["max_positions"] == 3


def test_risk_rules_save(client):
    r = client.post("/api/risk/rules", json={"max_positions": 5, "max_loss_per_trade_pct": 3.0})
    assert r.status_code == 200
    assert r.json()["rules"]["max_positions"] == 5


def test_risk_equity_base(client):
    r = client.get("/api/risk/equity-base")
    assert r.status_code == 200
    assert r.json()["equity_base"] is None
    r = client.post("/api/risk/equity-base", json={"base": 100000})
    assert r.status_code == 200
    assert r.json()["equity_base"] == 100000
    assert client.get("/api/risk/equity-base").json()["equity_base"] == 100000


def test_risk_at_risk_no_positions(client):
    r = client.get("/api/risk/at-risk")
    assert r.status_code == 200
    assert r.json()["available"] is False   # 没有未平仓持仓


def test_risk_report(client):
    r = client.get("/api/risk/report")
    assert r.status_code == 200
    rep = r.json()
    assert "equity" in rep and "rolling" in rep
    assert "discipline" in rep and "violations" in rep


def test_risk_excursion_summary(client):
    r = client.get("/api/risk/excursion")
    assert r.status_code == 200
    assert r.json()["available"] is False   # 没有已平仓交易


def test_risk_attribution_degraded(client):
    """Vibe-Research 无 reflection 数据 → attribution 降级 available:False。"""
    r = client.get("/api/risk/attribution")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_risk_inbox_no_trades(client):
    r = client.get("/api/risk/inbox")
    assert r.status_code == 200
    assert r.json()["available"] is False


# ───────────────────────── 与既有市场级 risk 端点无碰撞 ─────────────────────────
def test_market_risk_dashboard_still_works(client):
    """既有 routers/risk.py /api/risk/dashboard（市场级）不被新个人 risk 端点破坏。"""
    r = client.get("/api/risk/dashboard")
    assert r.status_code in (200, 502)   # 可能数据源未启返 502，但不应是 404/500 路由错
    assert r.status_code != 404         # 路由存在（未被覆盖）
