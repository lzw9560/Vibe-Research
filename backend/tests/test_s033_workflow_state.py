# -*- coding: utf-8 -*-
"""S033：状态机前端呈现后端单测（扩表 + 流转扩参 + 单股端点）。"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# R1：扩表——三列存在 + 旧数据 NULL
# ---------------------------------------------------------------------------


def test_workflow_state_columns(isolated_market_db):
    """workflow_state 有 entry_price/exit_price/strategy 三列；新行默认 NULL。"""
    import workflow_state_repo as wsr

    conn = wsr._get_connection()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(workflow_state)").fetchall()}
        assert {"entry_price", "exit_price", "strategy"} <= cols
    finally:
        conn.close()

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    state = wsr.get_state("600001", "2026-08-07")
    assert state["entry_price"] is None
    assert state["exit_price"] is None
    assert state["strategy"] is None


# ---------------------------------------------------------------------------
# R2：流转扩参——entry_price/exit_price/strategy 写入 + COALESCE 保持
# ---------------------------------------------------------------------------


def test_transition_with_price(isolated_market_db):
    """holding 带 entry_price+strategy 写入；settled 带 exit_price 时不覆盖已有值。"""
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    assert wsr.transition("600001", "2026-08-07", "watching", "")[0]
    assert wsr.transition("600001", "2026-08-07", "monitoring", "")[0]
    ok, _ = wsr.transition(
        "600001", "2026-08-07", "holding", "买入",
        entry_price=12.5, strategy="首板挖掘",
    )
    assert ok
    state = wsr.get_state("600001", "2026-08-07")
    assert state["entry_price"] == 12.5
    assert state["strategy"] == "首板挖掘"
    assert state["exit_price"] is None

    # COALESCE：settled 只传 exit_price，entry_price/strategy 保持
    ok, _ = wsr.transition("600001", "2026-08-07", "settled", "卖出", exit_price=13.8)
    assert ok
    state = wsr.get_state("600001", "2026-08-07")
    assert state["exit_price"] == 13.8
    assert state["entry_price"] == 12.5
    assert state["strategy"] == "首板挖掘"


# ---------------------------------------------------------------------------
# R3：单股端点——state + allowed_targets；无记录 404
# ---------------------------------------------------------------------------


def test_single_state_endpoint(isolated_market_db):
    """GET /api/workflow/state/{code} 返状态 + allowed_targets；无记录 404。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    client = TestClient(appmod.app)

    r = client.get("/api/workflow/state/600001", params={"date": "2026-08-07"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["code"] == "600001"
    assert data["status"] == "candidate"
    assert "watching" in data["allowed_targets"]
    assert "filtered" in data["allowed_targets"]

    r = client.get("/api/workflow/state/699999", params={"date": "2026-08-07"})
    assert r.status_code == 404


def test_watching_allowed_targets_includes_candidate(isolated_market_db):
    """S049 D7：watching 态 allowed_targets 含 candidate（取消观察）。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600002", "测试乙", "2026-08-07", "")
    assert wsr.transition("600002", "2026-08-07", "watching", "")[0]
    client = TestClient(appmod.app)

    r = client.get("/api/workflow/state/600002", params={"date": "2026-08-07"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "watching"
    assert "candidate" in data["allowed_targets"]  # 取消观察


def test_watching_to_candidate_transition(isolated_market_db):
    """S049 D7：watching→candidate 合法（取消观察回候选池）。"""
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600003", "测试丙", "2026-08-07", "")
    assert wsr.transition("600003", "2026-08-07", "watching", "")[0]
    ok, _ = wsr.transition("600003", "2026-08-07", "candidate", "取消观察")
    assert ok
    assert wsr.get_state("600003", "2026-08-07")["status"] == "candidate"


def test_transition_endpoint_with_price(isolated_market_db):
    """POST transition 带 entry_price/strategy 经端点写入。"""
    from fastapi.testclient import TestClient
    import app as appmod
    import workflow_state_repo as wsr

    wsr.ensure_candidate("600001", "测试甲", "2026-08-07", "")
    client = TestClient(appmod.app)

    # candidate→watching→monitoring→holding 链
    for target in ("watching", "monitoring"):
        r = client.post("/api/workflow/state/transition", json={
            "code": "600001", "date": "2026-08-07", "target": target})
        assert r.status_code == 200, r.text

    r = client.post("/api/workflow/state/transition", json={
        "code": "600001", "date": "2026-08-07", "target": "holding",
        "reason": "买入", "entry_price": 10.2, "strategy": "连板接力"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["entry_price"] == 10.2
    assert data["strategy"] == "连板接力"
